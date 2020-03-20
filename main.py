import click
import api


@click.group()
def cli():
    pass


@click.command(help="初始化 .git 工作目录")
def init():
    api.init()


@click.command(help="添加 git 文件, 目前只支持单个文件")
@click.argument("path")
def add(path):
    api.add([path])


@click.command(help="提交")
@click.argument("message")
@click.argument("auth")
def commit(message, auth):
    api.commit(message, auth)


@click.command(help="提交")
def push():
    api.push()


@click.command(help="获取当前工作 git 状态")
def status():
    api.status()


@click.command(help="查询 git 改变")
def diff():
    api.diff()


cli.add_command(init)
cli.add_command(add)
cli.add_command(commit)
cli.add_command(status)
cli.add_command(diff)
cli.add_command(push)
