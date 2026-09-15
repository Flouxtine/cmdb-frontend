"""内部规则检测引擎：平台/服务指标采样 → 规则检测 → 产生/收敛告警（source=internal）

设计（docs/DESIGN.md §7.1）：5-10s 采样入库 metric_samples，规则引擎基于最近
窗口均值判断（错误率突增/延迟超标），命中则复用 alerts.upsert_alert 产生告警，
并触发通知。支持 simulate/fault、simulate/recover 演示故障剧本。
"""
import logging
import random
import threading
import time

from . import alerts, config, database

logger = logging.getLogger("opsscope.metrics")

WINDOW = 6          # 检测窗口：最近 N 条采样
ERROR_THRESHOLD = 5.0    # 错误率 % 阈值
LATENCY_THRESHOLD = 500.0  # 延迟 ms 阈值

# 演示服务运行状态（内存态，供采样读取）
_demo = {"error_base": 0.3, "latency_base": 120.0, "qps": 200}


def set_demo_health(error_rate: float, latency: float):
    _demo["error_base"] = error_rate
    _demo["latency_base"] = latency


def get_demo_state():
    return dict(_demo)


def simulate_fault():
    """模拟故障：demo-api 错误率/延迟升高 → 触发内部规则告警"""
    set_demo_health(8.0, 700.0)
    return run_once()


def simulate_recover():
    """恢复：demo-api 指标回落 → 内部规则告警自动收敛"""
    set_demo_health(0.3, 120.0)
    return run_once()


def _sample_once():
    """采集一次：平台自身 + demo-api（带随机抖动），写入 metric_samples 并滚动清理"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        ("demo-api", "error_rate", round(max(0, _demo["error_base"] + random.uniform(-0.2, 0.5)), 2)),
        ("demo-api", "latency", round(max(10, _demo["latency_base"] + random.uniform(-15, 25)), 1)),
        ("demo-api", "qps", _demo["qps"] + random.randint(-15, 15)),
        (config.SERVICE_NAME, "error_rate", round(random.uniform(0, 0.2), 2)),
        (config.SERVICE_NAME, "latency", round(random.uniform(8, 40), 1)),
    ]
    with database.get_conn() as conn:
        conn.executemany(
            "INSERT INTO metric_samples(service, metric, value, ts) VALUES(?,?,?,?)",
            [(s, m, v, ts) for s, m, v in rows])
        conn.execute("DELETE FROM metric_samples WHERE id NOT IN "
                     "(SELECT id FROM metric_samples ORDER BY id DESC LIMIT 5000)")


def analyze_health(service="demo-api"):
    """健康模式分析：识别单指标异常 / 多指标共振（疑似服务级故障）/ 流量骤变"""
    errs = _recent_values(service, "error_rate")
    lats = _recent_values(service, "latency")
    qps_list = _recent_values(service, "qps")

    findings = []
    avg_err = _avg(errs)
    avg_lat = _avg(lats)

    err_high = avg_err is not None and avg_err >= ERROR_THRESHOLD
    lat_high = avg_lat is not None and avg_lat >= LATENCY_THRESHOLD

    if err_high and lat_high:
        findings.append({"type": "resonance", "level": "high",
                         "message": "疑似服务级故障：错误率与延迟同时超标（多指标共振）"})
    elif err_high:
        findings.append({"type": "error_rate", "level": "high",
                         "message": f"错误率突增（均值 {avg_err:.1f}% ≥ {ERROR_THRESHOLD:.0f}%）"})
    elif lat_high:
        findings.append({"type": "latency", "level": "medium",
                         "message": f"延迟超标（均值 {avg_lat:.0f}ms ≥ {LATENCY_THRESHOLD:.0f}ms）"})

    # 流量骤变：最新 QPS 相对窗口均值偏差 >50%
    if qps_list and len(qps_list) >= 3:
        base = sum(qps_list[1:]) / (len(qps_list) - 1)   # 除最新外的均值
        latest = qps_list[0]                              # 最新（列表按 id DESC）
        if base > 0 and abs(latest - base) / base > 0.5:
            direction = "激增" if latest > base else "骤降"
            findings.append({"type": "traffic", "level": "medium",
                             "message": f"流量{direction}（最新 {latest:.0f} QPS，窗口均值 {base:.0f}）"})

    state = "abnormal" if findings else "healthy"
    tips = []
    for f in findings:
        if f["type"] == "resonance":
            tips.append("建议进入「告警分析」查看相关告警并触发 AI 排障；确认是否由最近发布引起。")
        elif f["type"] in ("error_rate", "latency"):
            tips.append("对比「服务健康」单指标曲线与最近发布记录，必要时回滚或扩容。")
        elif f["type"] == "traffic":
            tips.append("确认是否有活动/爬虫等流量来源，评估限流或扩容。")
    if not findings:
        tips.append("指标平稳，无异常模式。")

    return {"service": service, "state": state, "findings": findings, "tips": tips}


def _recent_values(service, metric, n=WINDOW):
    rows = database.fetch_all(
        "SELECT value FROM metric_samples WHERE service=? AND metric=? ORDER BY id DESC LIMIT ?",
        (service, metric, n))
    return [r["value"] for r in rows]


def _avg(vals):
    return sum(vals) / len(vals) if vals else None


def _recent_avg(service: str, metric: str):
    vals = _recent_values(service, metric, WINDOW)
    return _avg(vals)


def run_once():
    """单次采样 + 规则检测（可手动调用/测试），返回本次检测摘要"""
    _sample_once()
    created = resolved = 0
    for service in ("demo-api", config.SERVICE_NAME):
        err = _recent_avg(service, "error_rate")
        lat = _recent_avg(service, "latency")
        if err is not None and err >= ERROR_THRESHOLD:
            r = alerts.upsert_alert({
                "source": "internal", "level": "high",
                "title": f"{service} 错误率突增", "detail": f"近 {WINDOW * int(config.SAMPLE_INTERVAL)}s 平均错误率 {err:.1f}% 超过阈值 {ERROR_THRESHOLD:.0f}%",
                "resource_ref": "", "status": "open",
                "dedup_key": alerts.dedup_key("internal", f"error_rate_spike:{service}")})
            created += r["action"] == "created"
        else:
            resolved += _resolve_rule_alert(service, "error_rate_spike")
        if lat is not None and lat >= LATENCY_THRESHOLD:
            r = alerts.upsert_alert({
                "source": "internal", "level": "medium",
                "title": f"{service} 平均延迟超标", "detail": f"近 {WINDOW * int(config.SAMPLE_INTERVAL)}s 平均延迟 {lat:.0f}ms 超过阈值 {LATENCY_THRESHOLD:.0f}ms",
                "resource_ref": "", "status": "open",
                "dedup_key": alerts.dedup_key("internal", f"latency_high:{service}")})
            created += r["action"] == "created"
        else:
            resolved += _resolve_rule_alert(service, "latency_high")
    return {"created": created, "resolved": resolved}


def _resolve_rule_alert(service: str, rule_key: str) -> int:
    """按 dedup_key 收敛同规则的 open 内部告警，返回收敛数"""
    key = alerts.dedup_key("internal", f"{rule_key}:{service}")
    return alerts.resolve_by_dedup_key(key)


def _loop():
    from . import escalation
    while True:
        time.sleep(config.SAMPLE_INTERVAL)
        try:
            run_once()
            escalation.run_escalation_check()
        except Exception as e:
            logger.warning("采样/检测异常: %s", e)


def start():
    threading.Thread(target=_loop, daemon=True).start()
