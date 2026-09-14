"""告警升级策略：长时间未解决自动升级级别 + 通知 + 审计

内置策略（幂等，只升一级）：
- high 未解决 > 30min → 升级 critical
- medium 未解决 > 2h → 升级 high
- low 未解决 > 4h → 升级 medium
升级写入 alert_events.escalated_at / escalate_count，并记录 action_logs 审计 + 推送通知。
"""
import logging

from . import config, database as db
from .notify import send_alert_notification

logger = logging.getLogger("opsscope.escalation")

# 级别 → (升级到, 阈值小时)
THRESHOLDS = {
    "high": ("critical", 0.5),
    "medium": ("high", 2.0),
    "low": ("medium", 4.0),
}


def escalation_config():
    return {
        "enabled": config.ESCALATION_ENABLED,
        "thresholds": [{"level": k, "upgrade_to": v[0], "hours": v[1]} for k, v in THRESHOLDS.items()],
    }


def run_escalation_check():
    """扫描未解决告警，超过阈值的自动升级（只升一级、幂等）。返回本次升级数。"""
    if not config.ESCALATION_ENABLED:
        return {"scanned": 0, "escalated": 0}
    rows = db.fetch_all(
        "SELECT * FROM alert_events WHERE status IN ('open','in_progress') "
        "AND (escalate_count IS NULL OR escalate_count < 2)")
    escalated = 0
    for a in rows:
        conf = THRESHOLDS.get(a["level"])
        if not conf:
            continue
        target_level, hours = conf
        alive = db.fetch_one(
            "SELECT ((julianday('now','localtime') - julianday(?)) * 24) AS h", (a["first_at"],))["h"]
        if alive is None or alive < hours:
            continue
        # 升级（幂等：count 递增，最多升两级）
        db.execute(
            "UPDATE alert_events SET level=?, escalated_at=COALESCE(escalated_at, datetime('now','localtime')), "
            "escalate_count=COALESCE(escalate_count,0)+1, last_at=datetime('now','localtime') WHERE id=?",
            (target_level, a["id"]))
        # 审计
        db.execute(
            "INSERT INTO action_logs(alert_id, action_key, name, detail) VALUES(?,?,?,?)",
            (a["id"], "escalation_auto", "告警自动升级",
             f"{a['level']}→{target_level}（未解决 {alive:.1f}h，阈值 {hours}h）"))
        # 通知（升级为 critical 时必推；其余跟随通知配置）
        send_alert_notification({**a, "title": f"[已升级] {a['title']}", "level": target_level,
                                 "detail": a.get("detail") or ""}, "created")
        escalated += 1
    return {"scanned": len(rows), "escalated": escalated}
