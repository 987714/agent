"""只读取本课目录中的.env，不在代码里填写密钥。"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
API_KEY = os.getenv("API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "")
MODEL_NAME = os.getenv("MODEL_NAME", "")
