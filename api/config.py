import os
import json
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        # 直接从环境变量读取 DATABASE_URL，如果没有则从组件构建
        self.DATABASE_URL = os.getenv("DATABASE_URL", "")

        # 如果环境变量中没有 DATABASE_URL，则从 POSTGRES_* 构建（兼容旧方式）
        if not self.DATABASE_URL:
            POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
            POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
            POSTGRES_USER = os.getenv("POSTGRES_USER", "code_analyzer")
            POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "secure_pass")
            POSTGRES_DB = os.getenv("POSTGRES_DB", "code_analyzer_db")
            self.DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

        # LLM 配置
        self.LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-9ec67bb280064a25b993d6adf8ef0349")
        self.LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
        self.LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")

        self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/code_analysis")
        self.API_KEYS = json.loads(os.getenv("API_KEYS", '{"mvp_key": "default_project"}'))

        # 搜索配置
        self.SEARCH_DEFAULT_LIMIT = int(os.getenv("SEARCH_DEFAULT_LIMIT", "20"))
        self.SEARCH_MAX_LIMIT = int(os.getenv("SEARCH_MAX_LIMIT", "100"))

        # 确保临时目录存在
        os.makedirs(self.TEMP_DIR, exist_ok=True)


# 创建全局配置实例
config = Config()