"""OpsScope 配置（环境变量驱动）"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("OPS_SCOPE_DATA", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "opsscope.db"
SECRET_FILE = DATA_DIR / ".secret"

VERSION = "1.0.0"

SERVICE_NAME = os.environ.get("SERVICE_NAME", "opsscope")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# 安全：CORS 白名单（逗号分隔，默认 * 仅适合内网/本地）
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
# Webhook 鉴权令牌（M2 告警接收使用；留空则不校验）
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
