# Changelog

## v1.0.0 (M4) — 发布打磨

- 版本单源（`config.VERSION`）+ CHANGELOG + README 徽章
- Docker 镜像改为非 root 运行（安全加固）
- Makefile 常用任务（test / run / docker-build）
- 里程碑 M1-M3 全部完成，CI（pytest 19 用例）→ GHCR 镜像发布链路打通

## v0.3.0 (M3) — 变更关联 + AI 排障分析

- `POST /api/ai/explain`：告警上下文（资源/账号归属 + 业务服务 + 最近发布含"疑似关联"标记）→ LLM（OpenAI 兼容，deepseek 可配）分析；未配 key 走关键字规则回退
- 前端告警行"🤖 AI 分析"抽屉
- 告警过期扫描（open → expired）；rules 幂等种子数据
- 测试：+4（共 19）

## v0.2.0 (M2) — 告警接收与归一化

- `POST /api/webhooks/alertmanager`（标准格式）+ `/api/webhooks/generic`（通用格式，`WEBHOOK_TOKEN` 可选鉴权）
- 归一化：级别映射、`dedup_key` 去重、资源匹配 CMDB（带出所属账号）、变更关联（30min 发布窗口）、状态机
- 前端告警分析页（模拟外部告警 / 筛选 / 来源徽标 / 关联发布标签）
- 测试：+7

## v0.1.0 (M1) — 账号 + 云资源 CMDB

- 云账号管理（演示/阿里云、AK/SK Fernet 加密、测试连接、全量替换式同步）
- 云资源 CMDB：ECS/云盘/安全组/OSS，抽屉式详情展示所属账号与信息
- 业务 CMDB：service/app/middleware/device + 项目维度 + 服务-资源关联
- 发布上报 API（deployments）
- 工程件：Dockerfile / compose / GitHub Actions(GHCR) / report-release.sh / Apache-2.0
