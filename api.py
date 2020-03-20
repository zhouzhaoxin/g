import operator
import os
import time
from typing import List

import click

import lib
from base import Index, Blob, IndexEntry, Status, Tree, Commit, Mixin
from lib import write_file, find_path, get_remote_master_hash, build_lines_data, http_request, extract_lines


# git init
def init() -> None:
    """
    初始化工作目录
    """
    git_path = os.path.join(os.getcwd(), ".git")
    if os.path.exists(git_path):
        click.echo("工作目录已存在")
        return
    os.mkdir(git_path)
    for name in ["objects", "refs", "refs/heads"]:
        os.mkdir(os.path.join(git_path, name))
    write_file(os.path.join(git_path, "HEAD"), b"ref: refs/heads/master")
    click.echo(f"完成初始化 git 工作目录 {git_path}")


# git add
def add(paths: List[str]) -> None:
    """
    添加 paths 的内容到 git 管理
    就是将这些路径中的文件添加到 ./git/objects ，
    然后再使用这些文件生成的 sha1 生成 .git/index 索引
    """
    git_path = find_path()

    index = Index(git_path)
    blob = Blob(git_path)

    # 若索引存在，则将没有数据变动的索引记录下来，放到 entries 中
    all_entries = index.read_index()
    entries = [e for e in all_entries if e.path not in paths]

    # 将有变动的文件重新生成加密的对象，放入索引中
    for path in paths:
        sha1 = blob.compress(path)
        st, flags = os.stat(path), len(path.encode())
        assert flags < (1 << 12)
        entry = IndexEntry(
            int(st.st_ctime), 0, int(st.st_mtime), 0, st.st_dev,
            st.st_ino, st.st_mode, st.st_uid, st.st_gid, st.st_size,
            bytes.fromhex(sha1), flags, path)
        entries.append(entry)
    # 根据 path 排序
    entries.sort(key=operator.attrgetter('path'))
    index.write_index(entries)


# git status
def status():
    """
    获取当前工作目录状态
    """
    changed, new, deleted = Status().get_status()
    if changed:
        click.echo("文件改变:")
        for path in changed:
            print('   ', path)
    if new:
        click.echo("文件新增")
        for path in new:
            print('   ', path)
    if deleted:
        click.echo("文件删除")
        for path in deleted:
            print('   ', path)


# git diff
def diff():
    Status().diff()


# git commit
def commit(message, author):
    path = find_path()
    tree_obj = Tree(path)
    commit_obj = Commit(path)
    tree = tree_obj.write_tree()
    parent = commit_obj.get_local_master_hash()
    auth_time = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = ['tree ' + tree]
    if parent:
        lines.append('parent ' + parent)
    lines.append('author {} {}'.format(author, auth_time))
    lines.append('committer {} {}'.format(author, auth_time))
    lines.append('')
    lines.append(message)
    lines.append('')
    data = '\n'.join(lines).encode()
    sha1 = commit_obj.compress(data)
    master_path = os.path.join(commit_obj.get_master_path())
    write_file(master_path, (sha1 + '\n').encode())
    print('committed to master: {:7}'.format(sha1))
    return sha1


def push(git_url=None, username=None, password=None):
    commit_obj = Commit()
    username = lib.USERNAME
    password = lib.PASSWORD
    git_url = lib.G_GITHUB_REPO
    mixin_obj = Mixin()
    remote_sha1 = get_remote_master_hash(git_url, username, password)
    local_sha1 = commit_obj.get_local_master_hash()
    missing = commit_obj.find_missing_objects(local_sha1, remote_sha1)
    print(
        f"{remote_sha1 or '没有提交'} 到 {local_sha1} {len(missing)} 个对象{'' if len(missing) == 1 else 's'}")
    lines = ['{} {} refs/heads/master\x00 report-status'.format(
        remote_sha1 or ('0' * 40), local_sha1).encode()]
    data = build_lines_data(lines) + mixin_obj.create_pack(missing)
    url = git_url + '/git-receive-pack'
    response = http_request(url, username, password, data=data)
    lines = extract_lines(response)
    assert len(lines) >= 2, \
        'expected at least 2 lines, got {}'.format(len(lines))
    assert lines[0] == b'unpack ok\n', \
        "expected line 1 b'unpack ok', got: {}".format(lines[0])
    assert lines[1] == b'ok refs/heads/master\n', \
        "expected line 2 b'ok refs/heads/master\n', got: {}".format(lines[1])
    return (remote_sha1, missing)

push()