"""告警通知：告警产生/收敛时推送到钉钉/飞书/自定义 Webhook（后台线程，不阻塞主流程）"""
import logging
import threading

import httpx

from . import config

logger = logging.getLogger("opsscope.notify")


def send_alert_notification(alert: dict, action: str):
    """异步推送告警通知。action: created / resolved / deduped"""
    if not config.ALERT_WEBHOOK_URL:
        return
    threading.Thread(target=_do_send, args=(alert, action), daemon=True).start()


def _do_send(alert: dict, action: str):
    action_label = {"created": "告警触发", "resolved": "告警恢复", "deduped": "告警重复"}.get(action, action)
    payload = {
        "title": f"[{action_label}] {alert.get('title', '')}",
        "level": alert.get("level", ""),
        "detail": alert.get("detail", ""),
        "resource_ref": alert.get("resource_ref", ""),
        "source": alert.get("source", ""),
        "status": alert.get("status", ""),
        "time": alert.get("last_at") or alert.get("first_at") or "",
    }
    try:
        with httpx.Client(timeout=8) as client:
            client.post(config.ALERT_WEBHOOK_URL, json=payload)
    except Exception as e:
        logger.warning("告警通知推送失败: %s", e)
