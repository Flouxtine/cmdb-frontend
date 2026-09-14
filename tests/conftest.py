"""测试夹具：使用独立临时数据目录，每个用例前清空业务表"""
import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="opsscope-test-")
os.environ["OPS_SCOPE_DATA"] = _TMP
os.environ["SAMPLE_INTERVAL"] = "9999"   # 测试期间禁用后台采样/升级线程的即时执行

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    from app import database
    with database.get_conn() as conn:
        for t in ["cmdb_item_resource", "cmdb_items", "resources", "deployments", "credentials", "alert_events", "metric_samples", "action_logs", "silences"]:
            conn.execute(f"DELETE FROM {t}")
        # 自愈动作复位为默认关闭
        conn.execute("UPDATE auto_actions SET enabled=0")
    yield


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
