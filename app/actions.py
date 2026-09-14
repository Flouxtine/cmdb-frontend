"""自动处置/自愈动作引擎

告警创建（created）时按启用的 auto_actions 自动执行预设动作，全部写 action_logs 审计。
动作实现为注册表函数：fn(alert) -> detail 字符串。
"""
import logging

from . import config, database as db
from .notify import send_alert_notification

logger = logging.getLogger("opsscope.actions")


def _auto_assign(alert):
    """未认领告警自动分配给机器人并进入处理中"""
    if (alert.get("assignee") or "").strip():
        return None  # 已有负责人，跳过
    db.execute(
        "UPDATE alert_events SET assignee='🤖 auto-ops', status='in_progress', last_at=datetime('now','localtime') WHERE id=?",
        (alert["id"],))
    return "已自动认领给 🤖 auto-ops（进入处理中）"


def _notify(alert):
    """推送告警通知到配置的 Webhook"""
    send_alert_notification(alert, "created")
    return "已推送告警通知（ALERT_WEBHOOK_URL）"


def _simulate_self_heal(alert):
    """演示自愈：模拟重启故障服务并留痕"""
    service = alert.get("resource_ref") or alert.get("title") or "unknown"
    detail = f"已执行自动重启指令（演示，未实际执行）目标={service}"
    db.execute(
        "UPDATE alert_events SET comment = CASE WHEN comment IS NULL OR comment='' THEN ? "
        "ELSE comment || char(10) || ? END WHERE id=?",
        (f"[{_now()}] 🤖 自愈: {detail}", f"[{_now()}] 🤖 自愈: {detail}", alert["id"]))
    return detail


def _now():
    import datetime as dt
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


# 动作注册表：新增动作在此追加（与 auto_actions 表 seed 的 action_key 对应）
ACTIONS = {
    "auto_assign_bot": {"name": "自动认领（机器人）", "fn": _auto_assign},
    "notify_webhook": {"name": "告警通知推送", "fn": _notify},
    "simulate_self_heal": {"name": "自愈-模拟重启服务", "fn": _simulate_self_heal},
}


def run_actions_for_alert(alert: dict):
    """告警创建后按启用动作依次执行，返回执行结果列表（未启用则空）"""
    if not alert or not alert.get("id"):
        return []
    enabled = db.fetch_all("SELECT action_key FROM auto_actions WHERE enabled=1")
    results = []
    for row in enabled:
        action = ACTIONS.get(row["action_key"])
        if not action:
            continue
        try:
            detail = action["fn"](alert)
            if detail is None:
                continue
            db.execute(
                "INSERT INTO action_logs(alert_id, action_key, name, detail) VALUES(?,?,?,?)",
                (alert["id"], row["action_key"], action["name"], detail))
            results.append({"action_key": row["action_key"], "name": action["name"], "detail": detail})
        except Exception as e:
            logger.warning("自愈动作 %s 执行失败: %s", row["action_key"], e)
    return results


def run_action_manually(action_key: str, alert_id: int):
    """手动触发指定动作（API 用）"""
    action = ACTIONS.get(action_key)
    if not action:
        raise ValueError("动作不存在")
    alert = db.fetch_one("SELECT * FROM alert_events WHERE id=?", (alert_id,))
    if not alert:
        raise ValueError("告警不存在")
    detail = action["fn"](alert)
    if detail:
        db.execute(
            "INSERT INTO action_logs(alert_id, action_key, name, detail) VALUES(?,?,?,?)",
            (alert_id, action_key, action["name"], detail))
    return {"action_key": action_key, "name": action["name"], "detail": detail or "已执行（无变更）"}
