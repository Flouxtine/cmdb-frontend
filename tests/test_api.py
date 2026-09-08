"""M1 API 基础测试"""
from fastapi.testclient import TestClient

DEMO_CRED = {"name": "测试演示账号", "provider": "demo", "regions": ["cn-hangzhou"], "remark": "pytest"}


def create_demo_cred(client: TestClient) -> str:
    return client.post("/api/credentials", json=DEMO_CRED).json()["id"]


def test_providers(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    providers = {p["provider"] for p in r.json()}
    assert {"demo", "aliyun"} <= providers


def test_credential_crud(client):
    cid = create_demo_cred(client)
    assert client.get("/api/credentials").json()[0]["name"] == DEMO_CRED["name"]
    # 凭据字段应脱敏
    cred = client.get("/api/credentials").json()[0]
    assert cred["access_key"] == "******" or cred["access_key"] == ""
    assert client.delete(f"/api/credentials/{cid}").status_code == 200
    assert client.get("/api/credentials").json() == []


def test_demo_sync_and_ownership(client):
    cid = create_demo_cred(client)
    r = client.post(f"/api/credentials/{cid}/sync")
    assert r.status_code == 200
    data = r.json()
    assert data["synced"] == 12 and data["total"] == 12 and data["errors"] == []

    items = client.get("/api/resources?page_size=50").json()["items"]
    assert len(items) == 12
    assert all(i["credential_name"] == DEMO_CRED["name"] for i in items)
    types = {i["resource_type"] for i in items}
    assert {"ecs", "disk", "security_group", "oss"} == types


def test_sync_idempotent(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    client.post(f"/api/credentials/{cid}/sync")
    assert client.get("/api/resources?page_size=50").json()["total"] == 12


def test_pagination_sql(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    page1 = client.get("/api/resources?page=1&page_size=5").json()
    assert page1["total"] == 12 and len(page1["items"]) == 5
    page3 = client.get("/api/resources?page=3&page_size=5").json()
    assert len(page3["items"]) == 2
    # 过滤
    only_ecs = client.get("/api/resources?resource_type=ecs&page_size=50").json()
    assert only_ecs["total"] == 4


def test_resource_detail_and_cmdb_link(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    rid = client.get("/api/resources?page_size=1").json()["items"][0]["id"]

    # 业务服务 + 绑定
    item = client.post("/api/cmdb/items", json={"project": "核心交易", "type": "service", "name": "订单中心", "owner": "张三", "env": "prod"})
    iid = item.json()["id"]
    assert client.post(f"/api/cmdb/items/{iid}/link", json={"resource_id": rid}).status_code == 200

    # 资源详情应带 linked_items
    detail = client.get(f"/api/resources/{rid}").json()
    assert [i["name"] for i in detail["linked_items"]] == ["订单中心"]
    # 服务详情应聚合资源（含账号归属）
    svc = client.get(f"/api/cmdb/items/{iid}").json()
    assert len(svc["resources"]) == 1
    assert svc["resources"][0]["credential_name"] == DEMO_CRED["name"]

    # 解除绑定
    assert client.delete(f"/api/cmdb/items/{iid}/link/{rid}").status_code == 200
    assert client.get(f"/api/resources/{rid}").json()["linked_items"] == []


def test_deployments(client):
    r = client.post("/api/deployments", json={"service": "订单中心", "version": "v2.3.0", "commit": "abc", "author": "ops", "source": "github-actions"})
    assert r.status_code == 200
    rows = client.get("/api/deployments").json()
    assert rows[0]["version"] == "v2.3.0" and rows[0]["source"] == "github-actions"


def test_overview(client):
    r = client.get("/api/overview")
    assert r.status_code == 200
    assert "credential_count" in r.json()
