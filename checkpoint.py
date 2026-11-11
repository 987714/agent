"""47课：管理流程检查点，和database.py的聊天历史分开。"""
from contextlib import contextmanager          #只负责打开检查点保存器，交给外面使用，用完关闭连接
from pathlib import Path                       #检查点起到模型/工具节点执行完之后，存档的作用
from langgraph.checkpoint.sqlite import SqliteSaver

CHECKPOINT_PATH = Path(__file__).resolve().parent / "checkpoints.db"

@contextmanager
def get_checkpointer():
    # with期间连接有效；操作结束后关闭。文件保留，重启后仍能读取。
    with SqliteSaver.from_conn_string(str(CHECKPOINT_PATH)) as checkpointer:
        yield checkpointer
