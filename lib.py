import hashlib
import os
import struct
from urllib import request

GIT_SUFFIX = "/info/refs?service=git-receive-pack"
G_GITHUB_REPO = "https://github.com/zhouzhaoxin/g.git"
USERNAME = "###"
PASSWORD = "###"


def read_file(path: str) -> bytes:
    """读取文件数据并返回其二进制内容"""
    with open(path, "rb") as f:
        return f.read()


def write_file(path: str, data: bytes) -> None:
    """向文件中写入二进制数据"""
    with open(path, "wb") as f:
        f.write(data)


def find_path(top: str = ".", dirname=".git") -> str:
    """
    递归寻找git工作目录，若没找到则抛出异常
    """
    path = os.path.realpath(top)
    git_path = os.path.join(path, dirname)
    if os.path.isdir(git_path):
        return git_path

    parent = os.path.realpath(os.path.join(path, ".."))
    if parent == path:
        raise FileExistsError(".git 工作目录不存在")

    return find_path(parent)


# noinspection PyUnresolvedReferences,PyTypeChecker,SpellCheckingInspection
def http_request(url: str, username: str, password: str, data: dict = None) -> bytes:
    """
    使用用户名密码访问网站，默认发送get请求如果 data 不为空则发送 post 请求
    """
    password_manager = request.HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, url, username, password)
    auth_handler = request.HTTPBasicAuthHandler(password_manager)
    opener = request.build_opener(auth_handler)
    f = opener.open(url, data=data)
    return f.read()


def extract_lines(data: bytes):
    """
    b"00770000000000000000000000000000000000000000 fbe4d37d027846070282f6051b338239cb2c33e2 refs/heads/master\x00 report-status\n
    0000
    PACK\x00\x00\x00\x02\x00\x00\x00\x03>x\x9c\xcbH\xcd\xc9\xc9\xe7*NIK\x01\x11\x00&\x9e\x05\x07\xa0\x02x\x9c340031Q(I-.a`\xbd\xa9\xec\xe5\x1d}I\xbd\x8e\x8f\xad\xb7\x87\xf7\xfaQ\xfe\xc0\x1f\x82\x00\x9b/\n\xb7\x96\x07x\x9cu\xca[\n\x80 \x10\x00\xc0\x7fO\xe1\x05\x82}\xb8\x99\xddFm\xc5\xc0\x10\xc4 :}'h\xbeg\x0eU\x9b$\x15\xc4\x98S\x00'TPp#\xe65b\x8e\x92\xfdQ\x80\x85\xd4\xbb\xcd\xc4{\xd6>\xec\xfb>\x96\x80`\x01^0X\xe4\x9ddw`r\xbf\xaesN\xfd\x1f\xa6jk\xdd|\xabA\x1f\xe1\xdc\xa8\xd7}\x1f\xbf3VA\xb2\xc6\x81\xef\x16\x7f\xb9\xeb\x87\xf6\xf5"
    根据 git 的 pack 协议格式化数据
    git 的 pack 协议将数据分割，数据的前4位是用 16 进制表示的本段数据的长度，同时最后以 `0000` 标记段落结尾
    以一个空的 github 库为例(注意：真实的数据没有这么多换行)：
    001f `第一段数据的长度为 31`
    # service=git-receive-pack\n `去除长度标记4位的数据长度为：31 - 4 = 27`
    0000 `第一段数据结束`
    009b `第二段数据的长度为 155`
        0000000000000000000000000000000000000000 `这是第二段数据，结尾有个空格共 40 字节`
        capabilities^{}\x00report-status delete-refs side-band-64k `这也是第二段数据，和上边连载一起，也有空格共 56 字节 `
        quiet atomic ofs-delta agent=git/github-g70eaaeb1276f\n `这是最后一个第二段数据 共 55 字节`
    0000 `第二段数据结束`
    >>> url = G_GITHUB_REPO + GIT_SUFFIX
    >>> USERNAME
    'singleorb@outlook.com'
    >>> PASSWORD
    'Chon159357'
    >>> data = http_request(url, username=USERNAME, password=PASSWORD)
    >>> lines = extract_lines(data)
    >>> lines
    """
    lines = []
    i = 0
    for _ in range(1000):
        line_length = int(data[i:i + 4], 16)
        line = data[i + 4:i + line_length]
        lines.append(line)
        # 读取到段尾标记位
        if line_length == 0:
            i += 4
        else:
            i += line_length
        if i >= len(data):
            break
    return lines


def build_lines_data(lines):
    """
    根据 pack 协议构造发送到 git 服务器的数据结构
    """
    result = []
    for line in lines:
        result.append('{:04x}'.format(len(line) + 5).encode())
        result.append(line)
        result.append(b'\n')
    result.append(b'0000')
    return b''.join(result)


def get_remote_master_hash(git_url, username, password) -> [str, None]:
    """
    获取远程 master 结点的 hash,如果没有就返回 None
    """
    url = git_url + GIT_SUFFIX
    response = http_request(url, username, password)
    lines = extract_lines(response)
    assert lines[0] == b'# service=git-receive-pack\n'
    assert lines[1] == b''
    if lines[2][:40] == b'0' * 40:
        return None
    master_sha1, master_ref = lines[2].split(b'\x00')[0].split()
    assert master_ref == b'refs/heads/master'
    assert len(master_sha1) == 40
    return master_sha1.decode()


def build_lines_data(lines):
    result = []
    for line in lines:
        result.append('{:04x}'.format(len(line) + 5).encode())
        result.append(line)
        result.append(b'\n')
    result.append(b'0000')
    return b''.join(result)
