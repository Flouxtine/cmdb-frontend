# OpsScope · 观云台

> GitHub 仓库：[Flouxtine/cmdb-frontend](https://github.com/Flouxtine/cmdb-frontend)

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
- ⬜ **M2**（v0.2.0）告警接收与归一化（Alertmanager / 通用 Webhook）
- ⬜ **M3**（v0.3.0）变更关联 + AI 排障分析
- ⬜ **M4**（v1.0.0）GitHub 发布打磨

## License

Apache-2.0
