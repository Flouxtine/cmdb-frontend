# OpsScope · 观云台

> GitHub 仓库：[Flouxtine/cmdb-frontend](https://github.com/Flouxtine/cmdb-frontend)

![CI](https://github.com/Flouxtine/cmdb-frontend/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

DevOps 集成式 AIOps 平台：**云账号 → 云资源 CMDB（归属可查）→ 告警接收分析 → 变更关联 → AI 排障**。
自用友好 · GitHub 开源 · `docker compose up` 即用。

> 设计文档见 [docs/DESIGN.md](docs/DESIGN.md) ｜ 部署文档见 [docs/DEPLOY.md](docs/DEPLOY.md)

## 快速开始

```bash
cp .env.example .env
docker compose up -d     # http://127.0.0.1:8080
```

详细部署（获取镜像 / 配置 / 升级 / 备份 / 安全）见 [docs/DEPLOY.md](docs/DEPLOY.md)。

首次使用建议创建「演示环境」账号 → 同步资源 → 体验资源归属/CMDB 呈现。

## 目录

```
app/           FastAPI 后端（providers/ 厂商抽象）
frontend/      单页前端（原生 JS+CSS，零构建）
docs/          DESIGN.md / DEPLOY.md
scripts/       report-release.sh 发布上报
.github/workflows/  CI/CD → GHCR
```

## Roadmap

- ✅ **M1**（v0.1.0）账号 + 云资源 CMDB + 业务服务关联（归属可查）
- ✅ **M2**（v0.2.0）告警接收与归一化（Alertmanager / 通用 Webhook）
- ✅ **M3**（v0.3.0）变更关联 + AI 排障分析
- ✅ **M4**（v1.0.0）GitHub 发布打磨
- ✅ **内部规则检测**：平台/服务指标采样 → 错误率突增/延迟超标自动告警（`/simulate/fault` 演示）
- ✅ **告警通知**：钉钉/飞书/自定义 Webhook 推送（`.env` 配 `ALERT_WEBHOOK_URL`）
- ✅ **合规中心**：安全基线扫描（安全组高危端口 / OSS 公共访问 / 云盘未加密），违规自动产生告警 + 合规率概览
- ✅ **告警处置协作**：认领负责人（自动进入处理中）、带时间戳追加处置备注，告警处置留痕
- ✅ **服务健康可视化**：指标曲线 + 阈值红线 + 实时刷新（错误率/延迟/QPS）
- ✅ **处置工作台**：告警负载看板（未解决/处理中/未认领 KPI + 认领人聚合 + 只看未认领筛选）
- ✅ **Prometheus 指标暴露**：`/api/metrics` 输出告警/资产/合规指标，对接外部监控
- ✅ **处置统计报表**：近 N 天告警产生/解决/平均解决时长 + 认领人工作量 + 按天趋势
- ✅ **合规修复建议**：违规告警给分步整改步骤（内置模板 / LLM 定制增强）
- ✅ **自愈规则**：告警触发自动执行动作（自动认领/通知推送/模拟自愈重启），可开关 + 审计日志
- ✅ **告警静默**：维护/发版窗口静默匹配告警（全局或按服务），不产生不通知不自愈
- ✅ **告警升级策略**：长时间未解决自动升级级别（high 30min→critical 等），通知 + 审计
- ✅ **CSV 导出**：告警列表（按当前筛选）与处置统计报表一键导出（Excel 兼容）
- ✅ **Webhook HMAC 签名**：`WEBHOOK_SECRET` 配置后强制签名校验（防伪造/防篡改），兼容 Token 模式

## License

Apache-2.0
