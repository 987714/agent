# 目标：输入文件的绝对路径或相对路径，输出包含文件正文和文件名的字典

from pathlib import Path

def load_document(file_path):
    path = Path(file_path)  # Path用来把路径字符串变为路径对象
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    if path.suffix.lower() not in (".txt",".md"):
        raise ValueError("只支持.txt和.md文件")
    try:
        text = path.read_text(encoding="utf-8")         #把路径中的正文读到text中
    except UnicodeDecodeError as error:
        raise ValueError("文件无法按UTF-8读取，请将文件保存为UTF-8编码") from error
    if not text.strip():
        raise ValueError("文件内容不能为空")

    return {
        "text": text,
        "source": path.name
    }
