import collections
import difflib
import hashlib
import os
import re
import stat
import struct
import zlib
from functools import singledispatchmethod
from typing import List, Tuple

from lib import write_file, find_path, read_file

# .git/index 中索引的内容
IndexEntry = collections.namedtuple('IndexEntry', [
    'ctime_s', 'ctime_n', 'mtime_s', 'mtime_n', 'dev', 'ino', 'mode', 'uid',
    'gid', 'size', 'sha1', 'flags', 'path',
])


class HashObject:
    """
    格式化 git 对象, git 对象存储在 .git/objects 目录中
    compress:
        压缩需要 git 管理的文件，写入 objects 目录，并返回其 sha1 值
    decompress:
        根据 sha1 值寻找 objects 存储的文件，根据压缩规则解析并返回其中的内容
    find_object:
        根据hash值找到对象的存储路径
    """

    TYPE = None

    def __init__(self, git_path: str = ""):
        if git_path:
            self.git_path = git_path
        else:
            self.git_path = find_path()
        self.objs_path = os.path.join(self.git_path, "objects")

    def find_object(self, sha1: str):
        """
        根据 sha1 值找到对象并返回其目录
        """
        if len(sha1) < 2:
            raise ValueError("sha1 至少拥有两个字节")
        obj_dir = os.path.join(self.git_path, "objects", sha1[:2])
        objects = [name for name in os.listdir(obj_dir) if name.startswith(sha1[2:])]
        if not objects:
            raise ValueError(f"未找到对象 {sha1}")
        if len(objects) >= 2:
            raise ValueError(f"根据 {sha1} 找到多个对象 {len(objects)}")
        return os.path.join(obj_dir, objects[0])

    @singledispatchmethod
    def compress(self, arg):
        """
        压缩需要 git 管理的文件写入 objects 目录，并返回其 sha1 值
        """
        raise NotImplementedError()

    @compress.register
    def _(self, data: bytes) -> str:
        assert self.TYPE, f"类型错误 {self.TYPE}"
        full_data = self._build_head(self.TYPE, len(data)) + data
        sha1 = hashlib.sha1(full_data).hexdigest()
        path = os.path.join(self.objs_path, sha1[:2], sha1[2:])

        if not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path), exist_ok=True)

        if os.path.exists(path):
            return sha1

        write_file(path, zlib.compress(full_data))
        return sha1

    @compress.register
    def _(self, path: str) -> str:
        assert self.TYPE, f"类型错误 {self.TYPE}"
        data = read_file(path)
        return self.compress(data)

    def decompress(self, sha1: str) -> bytes:
        """
        解析 blob 数据，校验数据类型和大小，防止读取被修改过的文件
        """
        assert self.TYPE, f"类型错误 {self.TYPE}"
        path = self.find_object(sha1)
        full_data = zlib.decompress(read_file(path))

        nul_index = full_data.index(b'\x00')
        header = full_data[:nul_index]

        obj_type, size_str = header.decode().split()
        size = int(size_str)
        data = full_data[nul_index + 1:]

        assert size == len(data), f"数据长度应为 {size}, 得到 {len(data)} bytes"
        assert obj_type == self.TYPE, f"数据类型应为 {self.TYPE}，得到 {obj_type}"

        return data

    @staticmethod
    def _build_head(object_type: str, data_length: int) -> bytes:
        """
        构建对象的头部，以 NULL 结尾，即可以直接拼接对象内容
        头部由：对象类型 + 空格 + 对象长度组成 + \x00[NULL]
        :param object_type: 对象类型
        :param data_length: 对象长度
        :return: 对象头部
        """
        return f"{object_type} {data_length}\x00".encode()


class Blob(HashObject):
    TYPE = "blob"


class Commit(HashObject):
    TYPE = "commit"

    def get_master_path(self):
        master_path = os.path.join(self.git_path, "refs", "heads", "master")
        return master_path

    def get_local_master_hash(self):
        """
        获取本地的 master hash 值，没有就反回 None
        """
        try:
            master_path = self.get_master_path()
            return read_file(master_path).decode().strip()
        except FileNotFoundError:
            return None

    def find_commit_objects(self, commit_sha1, tree_obj):
        objects = {commit_sha1}
        commit = self.decompress(commit_sha1)
        lines = commit.decode().splitlines()
        tree = next(l[5:45] for l in lines if l.startswith('tree '))
        objects.update(tree_obj.find_tree_objects(tree))
        parents = (l[7:47] for l in lines if l.startswith('parent '))
        for parent in parents:
            objects.update(self.find_commit_objects(parent, tree_obj))
        return objects

    def find_missing_objects(self, local_sha1, remote_sha1):
        tree = Tree()
        local_objects = self.find_commit_objects(local_sha1, tree)
        if remote_sha1 is None:
            return local_objects
        remote_objects = self.find_commit_objects(remote_sha1, tree)
        return local_objects - remote_objects


class Tree(HashObject):
    TYPE = "tree"

    def __init__(self, git_path: str = ""):
        if git_path:
            path = git_path
        else:
            path = find_path()
        super().__init__(path)
        self.index = Index(path)

    def write_tree(self):
        """
        根据 .git/index 文件生成 tree
        """
        tree_entries = []
        for entry in self.index.read_index():
            assert '/' not in entry.path
            mode_path = '{:o} {}'.format(entry.mode, entry.path).encode()
            tree_entry = mode_path + b'\x00' + entry.sha1
            tree_entries.append(tree_entry)
        return self.compress(b''.join(tree_entries))

    def read_tree(self, sha1: str):
        data = self.decompress(sha1)
        i = 0
        entries = []
        for _ in range(1000):
            end = data.find(b'\x00', i)
            if end == -1:
                break
            mode_str, path = data[i:end].decode().split()
            mode = int(mode_str, 8)
            digest = data[end + 1:end + 21]
            entries.append((mode, path, digest.hex()))
            i = end + 1 + 20
        return entries

    def find_tree_objects(self, tree_sha1):
        objects = {tree_sha1}
        for mode, path, sha1 in self.read_tree(sha1=tree_sha1):
            if stat.S_ISDIR(mode):
                objects.update(self.find_tree_objects(sha1))
            else:
                objects.add(sha1)
        return objects


class Tag(HashObject):
    TYPE = "tag"


class Index:
    """
    管理 .git/index 文件
    """

    def __init__(self, git_path: str = ""):
        if git_path:
            self.git_path = git_path
        else:
            self.git_path = find_path()

    def write_index(self, entries):
        """
        将 entries 写入 .git/index 文件，这个 index 的生成规则和现有的 git 一样
        index 文件存储被 git 管理的文件索引，以 path 排序，每一行都包含 [path 名称, 修改时间, 文件 sha1 值] 等
        index 文件的前 12 个字节为头部[signature, version, entry length]，最后的 20 个字节为 index 索引文件的 sha1 值,
        中间的内容就是索引数据，索引属于以62个字节的头部+path和一些NULL组成，索引数据以 NULL 结尾
        """
        packed_entries = []
        for entry in entries:
            # 62 字节的索引头部
            entry_head = struct.pack('!LLLLLLLLLL20sH',
                                     entry.ctime_s, entry.ctime_n, entry.mtime_s, entry.mtime_n,
                                     entry.dev, entry.ino, entry.mode, entry.uid, entry.gid,
                                     entry.size, entry.sha1, entry.flags)

            path = entry.path.encode()

            # 对齐索引文件
            length = ((62 + len(path) + 8) // 8) * 8
            # 62 字节头部 + path + NULL
            packed_entry = entry_head + path + b'\x00' * (length - 62 - len(path))
            packed_entries.append(packed_entry)

        # 12 字节的 index 文件头部
        header = struct.pack('!4sLL', b'DIRC', 2, len(entries))
        all_data = header + b''.join(packed_entries)
        digest = hashlib.sha1(all_data).digest()
        write_file(os.path.join(self.git_path, 'index'), all_data + digest)

    def read_index(self) -> List[IndexEntry]:
        """
        读取 .git/index 文件并返回 IndexEntry 对象列表
        """
        try:
            data = read_file(os.path.join(self.git_path, 'index'))
        except FileNotFoundError:
            return []
        # 校验文件是否被改动
        digest = hashlib.sha1(data[:-20]).digest()
        assert digest == data[-20:], 'index 文件非法'

        # 获取 index 的头部
        signature, version, num_entries = struct.unpack('!4sLL', data[:12])
        assert signature == b'DIRC', f"签名不合法 {signature}"

        assert version == 2, f"版本不合法 {version}"

        # 解析 index 存储的对象索引
        entry_data = data[12:-20]
        entries = []
        i = 0
        while i + 62 < len(entry_data):
            fields_end = i + 62
            fields = struct.unpack('!LLLLLLLLLL20sH', entry_data[i:fields_end])
            path_end = entry_data.index(b'\x00', fields_end)
            path = entry_data[fields_end:path_end]
            entry = IndexEntry(*(fields + (path.decode(),)))
            entries.append(entry)
            entry_len = ((62 + len(path) + 8) // 8) * 8
            i += entry_len
        assert len(entries) == num_entries
        return entries


class Status:
    """
    管理文件状态
        对比文件的差异
    """

    def __init__(self, git_path: str = ""):
        if git_path:
            self.git_path = git_path
        else:
            self.git_path = find_path()
        self.work_path = os.path.realpath(os.path.join(self.git_path, ".."))
        self.index = Index(self.git_path)
        self.blob = Blob(self.git_path)
        ignore_file_name = ".gitignore"
        ignore_path = os.path.join(self.work_path, ignore_file_name)
        self.ignore_pattern = set()
        if os.path.exists(ignore_path):
            self.ignore = set(read_file(ignore_path).decode().splitlines())
            for ignore_item in self.ignore:
                if ignore_item.startswith(" patten "):
                    self.ignore_pattern.add(ignore_item[8:])
            self.ignore.add(ignore_file_name)
        else:
            self.ignore = []
        self.ignore -= self.ignore_pattern

    def get_status(self):
        paths = set()
        for root, dirs, files in os.walk(self.work_path):
            tmp = []
            for d in dirs:
                if d == ".git":
                    continue
                if d in self.ignore:
                    continue
                flag = True
                for p in self.ignore_pattern:
                    if re.match(p, d):
                        flag = False
                        break
                if not flag:
                    continue
                tmp.append(d)

            dirs[:] = tmp
            for file in files:
                if file in self.ignore:
                    continue
                flag = True
                for p in self.ignore_pattern:
                    if re.match(p, file):
                        flag = False
                        break
                if not flag:
                    continue
                path = file.replace('\\', '/')
                if path.startswith('./'):
                    path = path[2:]
                paths.add(path)
        entries_by_path = {e.path: e for e in self.index.read_index()}
        entry_paths = set(entries_by_path)
        changed = {p for p in (paths & entry_paths) if self.blob.compress(p) != entries_by_path[p].sha1.hex()}
        new = paths - entry_paths
        deleted = entry_paths - paths
        return sorted(changed), sorted(new), sorted(deleted)

    def diff(self):
        changed, _, _ = self.get_status()
        entries_by_path = {e.path: e for e in self.index.read_index()}
        for i, path in enumerate(changed):
            sha1 = entries_by_path[path].sha1.hex()
            data = self.blob.decompress(sha1)
            index_lines = data.decode().splitlines()
            working_lines = read_file(path).decode().splitlines()
            diff_lines = difflib.unified_diff(
                index_lines, working_lines,
                '{} (index)'.format(path),
                '{} (working copy)'.format(path),
                lineterm='')
            for line in diff_lines:
                print(line)
            if i < len(changed) - 1:
                print('-' * 70)


class Mixin(HashObject):
    OBJ_TYPE = {
        "commit": 1,
        "tree": 2,
        "blob": 3,
    }

    def decompress(self, sha1: str) -> Tuple[str, bytes]:
        """
        解析 blob 数据
        """
        path = self.find_object(sha1)
        full_data = zlib.decompress(read_file(path))

        nul_index = full_data.index(b'\x00')
        header = full_data[:nul_index]

        obj_type, size_str = header.decode().split()
        size = int(size_str)
        data = full_data[nul_index + 1:]

        assert size == len(data), f"数据长度应为 {size}, 得到 {len(data)} bytes"

        return obj_type, data

    def encode_pack_object(self, obj):
        obj_type, data = self.decompress(obj)
        type_num = self.OBJ_TYPE[obj_type]
        size = len(data)
        byte = (type_num << 4) | (size & 0x0f)
        size >>= 4
        header = []
        while size:
            header.append(byte | 0x80)
            byte = size & 0x7f
            size >>= 7
        header.append(byte)
        return bytes(header) + zlib.compress(data)

    def create_pack(self, objects):
        header = struct.pack('!4sLL', b'PACK', 2, len(objects))
        body = b''.join(self.encode_pack_object(o) for o in sorted(objects))
        contents = header + body
        sha1 = hashlib.sha1(contents).digest()
        data = contents + sha1
        return data




if __name__ == '__main__':
    # Repository()
    # b = Blob()
    # print(b.decompress("05d9234a4b5bd2277e0e068d8c0dd7c50f51f811"))
    # i = Index()
    # print(i.read_index())
    # print(b.compress(b"abc"))
    # print(b.decompress(b.compress(b"abc")))
    # print(b.compress("/Users/zhouzhaoxin/Projects/PycharmProjects/g/test"))
    # print(b.decompress(b.compress("/Users/zhouzhaoxin/Projects/PycharmProjects/g/test")))
    # s = Status()
    # print(s.get_status())
    tree = Tree()
    # print(tree.decompress('b5bf11acb90452f15182336a1ca5c7df0352e748'))
    # print(tree.read_tree('b5bf11acb90452f15182336a1ca5c7df0352e748'))
    # print(tree.find_tree_objects('b5bf11acb90452f15182336a1ca5c7df0352e748'))
    c = Commit()
    objects = c.find_commit_objects(c.get_local_master_hash(), tree)
    print(objects)
    # print(c.decompress('fbe4d37d027846070282f6051b338239cb2c33e2'))
    m = Mixin()
    print(m.create_pack(objects))
    pass
