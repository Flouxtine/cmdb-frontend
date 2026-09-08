"""M3 AI 排障分析：告警上下文 → LLM（OpenAI 兼容）→ 原因/处置建议；未配 key 回退规则启发式。

设计（docs/DESIGN.md §8）：可解释、零样本、可回退。
上下文 = 告警 + 资源归属（账号）+ 业务服务 + 最近发布（含关联标记），让模型判断"是否发布导致"。
"""
import httpx

from . import config, database


def build_context(alert: dict) -> str:
    """组装排障上下文（全部来自平台已有数据，无需外部依赖）"""
    lines = [f"告警: {alert['title']}（级别:{alert['level']}）", f"详情: {alert.get('detail') or '-'}",
             f"来源: {alert.get('source')}"]

    if alert.get("resource_id"):
        r = database.fetch_one(
            "SELECT r.*, c.name AS account FROM resources r LEFT JOIN credentials c ON c.id=r.credential_id WHERE r.id=?",
            (alert["resource_id"],))
        if r:
            lines.append(f"资源: {r['name']}（{r['resource_type']} / region={r.get('region', '-')} / 所属账号:{r.get('account', '-')}）")
    if alert.get("item_id"):
        i = database.fetch_one("SELECT * FROM cmdb_items WHERE id=?", (alert["item_id"],))
        if i:
            lines.append(f"业务服务: {i['name']}（{i['type']} / 项目:{i['project']} / 负责人:{i.get('owner', '-')}）")

    deploys = database.fetch_all("SELECT * FROM deployments ORDER BY deployed_at DESC LIMIT 5")
    if deploys:
        lines.append("最近发布记录:")
        for d in deploys:
            mark = "  ← 疑似关联本次发布" if alert.get("related_deployment_id") == d["id"] else ""
            lines.append(
                f"  {d['deployed_at']} service={d['service']} version={d['version']} "
                f"commit={(d.get('commit') or '-')[:8]} author={d.get('author', '-')}{mark}")
    else:
        lines.append("最近发布记录: 无")
    return "\n".join(lines)


def heuristic_analysis(alert: dict) -> str:
    """未配置 LLM key 时的内置规则解释"""
    title = alert.get("title") or ""
    base = ("请按以下顺序排查：① 若存在'疑似关联发布'，对比发布部署时间与告警首次时间，"
            "必要时回滚该版本；② 检查资源/服务近期变更与依赖；③ 结合所属账号与业务服务查看资产详情。")
    if any(k in title for k in ["CPU", "cpu", "负载", "load"]):
        return "CPU 类告警常见原因：流量突增、慢请求堆积、配额不足或最近发布引入性能回归。建议先确认是否与发布时间吻合，再看实例规格与连接数。" + base
    if any(k in title for k in ["内存", "memory", "mem"]):
        return "内存类告警常见原因：内存泄漏、突发流量、缓存增长或配置不当。建议抓取堆转储/监控内存趋势，并对比最近发布。" + base
    if any(k in title for k in ["延迟", "latency", "超时", "timeout", "慢"]):
        return "延迟类告警常见原因：慢 SQL、下游依赖变慢（级联）、资源竞争或发布引入。建议按 发布→依赖→资源 顺序排查。" + base
    if any(k in title for k in ["宕机", "down", "不可用", "挂", "无数据", "健康"]):
        return "可用性类告警常见原因：进程退出、网络中断、资源耗尽或发布失败。建议先确认实例存活与日志，再核对最近发布。" + base
    return "通用排障建议：" + base


async def explain_alert(alert_id: int) -> dict:
    alert = database.fetch_one("SELECT * FROM alert_events WHERE id=?", (alert_id,))
    if not alert:
        raise ValueError("告警不存在")
    context = build_context(alert)
    fallback = heuristic_analysis(alert)

    if config.LLM_API_KEY:
        try:
            return await _ask_llm(alert, context)
        except Exception as e:
            return {"engine": "llm-fallback", "model": config.LLM_MODEL, "alert": alert,
                    "context": context, "analysis": f"LLM 调用失败（{e}），已回退内置规则分析。\n\n{fallback}"}
    return {"engine": "heuristic", "alert": alert, "context": context, "analysis": fallback}


async def _ask_llm(alert: dict, context: str) -> dict:
    prompt = (
        "你是一名资深 SRE。基于以下告警与上下文，用中文输出：\n"
        "1) 最可能的原因（结合'疑似关联发布'的部署时间与告警时间，判断是否由该发布导致）\n"
        "2) 排查/处置建议（分步骤、可执行，必要时给出回滚建议）\n\n"
        f"告警标题: {alert['title']}（级别:{alert['level']}）\n"
        f"告警详情: {alert.get('detail') or '-'}\n----\n{context}"
    )
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(
            f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            json={"model": config.LLM_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.2, "max_tokens": 800},
        )
        resp.raise_for_status()
        data = resp.json()
    return {"engine": "llm", "model": config.LLM_MODEL, "alert": alert,
            "context": context, "analysis": data["choices"][0]["message"]["content"]}
