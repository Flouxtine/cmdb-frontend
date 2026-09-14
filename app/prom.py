"""Prometheus 指标暴露（/api/metrics 文本格式）

注意：prometheus_client 的 Gauge.set() 在调用时更新值，generate_latest 输出当前值。
指标在导入本模块时创建（全局单例），采集逻辑定期更新这些 Gauge。
"""
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

from . import database as db

# ---- 告警指标 ----
alert_open_total = Gauge("ops_alert_open_total", "未解决+处理中告警总数")
alert_open_by_level = Gauge("ops_alert_open_by_level", "按级别的未解决告警数", ["level"])
alert_open_by_source = Gauge("ops_alert_open_by_source", "按来源的未解决告警数", ["source"])

# ---- 资产指标 ----
resource_total = Gauge("ops_resource_total", "云资源总数（CMDB）", ["type"])
credential_total = Gauge("ops_credential_total", "云账号总数")
cmdb_item_total = Gauge("ops_cmdb_item_total", "业务服务（CMDB 配置项）总数")
compliance_violation = Gauge("ops_compliance_violation_open", "未解决的合规违规告警数")

# ---- 服务采样指标（内部规则数据，按服务）----
sample_error_rate = Gauge("ops_service_error_rate", "最近服务错误率 %", ["service"])
sample_latency = Gauge("ops_service_latency", "最近服务延迟 ms", ["service"])


def collect():
    """采集平台运行态指标，更新各 Gauge（供后台周期调用或抓取前更新）"""
    # 告警分布
    open_rows = db.fetch_all("SELECT level, source FROM alert_events WHERE status IN ('open','in_progress')")
    alert_open_total.set(len(open_rows))
    by_level = {}
    by_source = {}
    for r in open_rows:
        by_level[r["level"]] = by_level.get(r["level"], 0) + 1
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    for lv in ("high", "medium", "low"):
        alert_open_by_level.labels(level=lv).set(by_level.get(lv, 0))
    for src in ("alertmanager", "custom", "internal", "compliance"):
        alert_open_by_source.labels(source=src).set(by_source.get(src, 0))

    # 资产
    resources = db.fetch_all("SELECT resource_type, COUNT(*) n FROM resources GROUP BY resource_type")
    by_type = {r["resource_type"]: r["n"] for r in resources}
    for t in ("ecs", "disk", "security_group", "oss"):
        resource_total.labels(type=t).set(by_type.get(t, 0))
    credential_total.set(db.fetch_one("SELECT COUNT(*) n FROM credentials")["n"])
    cmdb_item_total.set(db.fetch_one("SELECT COUNT(*) n FROM cmdb_items")["n"])
    compliance_violation.set(db.fetch_one(
        "SELECT COUNT(*) n FROM alert_events WHERE source='compliance' AND status='open'")["n"])

    # 服务采样（最近一条）
    for metric, gauge in (("error_rate", sample_error_rate), ("latency", sample_latency)):
        for service in ("demo-api",):
            row = db.fetch_one(
                "SELECT value FROM metric_samples WHERE service=? AND metric=? ORDER BY id DESC LIMIT 1",
                (service, metric))
            gauge.labels(service=service).set(row["value"] if row else 0)


def render():
    """返回 Prometheus 文本格式指标（抓取前刷新一次保证实时）"""
    collect()
    return generate_latest(), CONTENT_TYPE_LATEST