# OpsScope（观云台）— 设计文档 v3（定稿）

DevOps 集成式 AIOps 平台：账号/资源 CMDB → 告警接收分析 → 变更关联 → AI 排障。
自用友好、GitHub 开源、Docker 部署。文档与代码同步演进；部署见 [DEPLOY.md](DEPLOY.md)。

## 1. 产品主张

> 看得见：云账号 → 云资源 → CMDB（谁家的资源、什么配置、属于哪个业务）
> 收得齐：告警统一接收（内部规则 + 外部系统），归一到同一事件模型
> 查得准：任何资源/告警都能回溯到「所属云账号 + 最近变更 + AI 分析」

## 2. 核心闭环

```
云账号(凭据,加密) → 资源同步 → 云资源(带账号归属) → 业务 CMDB(项目/服务) 关联
发布事件(CI/CLI/手动) → deployments
告警：内部规则 + Alertmanager/通用Webhook 接收 → 归一化 → 变更关联(30min) → AI 分析
```

## 3. 模块与页面

一级导航：概览 / 云账号 / 云资源 CMDB / 业务 CMDB / 告警分析 / 发布记录

| 页面 | 内容（M1 已含 *） |
|---|---|
| 概览* | KPI（账号/资源/服务/未处理告警）+ 资源类型分布 + 各账号资源占比 + 服务健康 + 实时告警流 |
| 云账号* | 账号卡（厂商/状态/AK 脱敏/Region/同步时间/资源数），行内 测试/同步/删除；添加（演示/阿里云） |
| 云资源 CMDB* | 过滤（账号/类型/关键词）表格；**抽屉详情：所属账号卡 → 属性 → 标签 → 关联业务服务** |
| 业务 CMDB* | 项目/类型筛选；服务详情聚合：关联资源清单（带账号列）+ 绑定/解除 |
| 告警分析 | （M2）来源徽标 + 级别 + 关联发布标签 + AI 抽屉 |
| 发布记录 | （M3 数据源已备）时间线 + 手动登记 + 回滚标记 |

## 4. UI 呈现规格（参考市面）

- 借鉴：Datadog（事件流/颜色语义/抽屉）、Grafana（信息密度）、CloudExplorer（左导航）、GitHub/Linear（右侧抽屉）。
- 布局：左侧分组导航 + 顶栏全局过滤（账号/项目）+ 内容区；浅色底白卡片；语义色固定（正常绿/告警红/无数据灰/AI 紫）。
- **详情一律右侧抽屉(Drawer)**（含 AI 分析）；空态给"引导式步骤"（1 添加账号 → 2 同步 → 3 体验）。

## 5. 定案记录

| 项 | 决策 |
|---|---|
| 仓库 | `Flouxtine/cmdb-frontend`，镜像 `ghcr.io/flouxtine/cmdb-frontend` |
| 外部告警源 | M2 先做 **Prometheus Alertmanager + 通用 Webhook**；阿里云云监控二期 |
| CMDB 类型 | service / app / middleware / device（首期 UI 聚焦 service/app） |
| 项目维度 | `project` 字段 + 过滤 + 分组视图（不做多租户权限） |
| 凭据安全 | AK/SK Fernet 加密（密钥文件 0600，随数据卷备份） |
| 语言基线 | Python 3.9+ 兼容（容器 3.11）；本地零前端构建 |

## 6. 数据模型

```sql
credentials  id,name,provider,ak(密),sk(密),regions[],status,last_error,last_sync_at
resources    id,credential_id→,provider,type(ecs/disk/security_group/oss),resource_id,name,region,attributes,tags,synced_at
cmdb_items   id,project,type,name,owner,env,attributes
cmdb_item_resource  item_id,resource_id            -- 服务↔资源 多对多
deployments  id,service,version,"commit",author,source,rollback,deployed_at
alert_events id,source,dedup_key,level,title,detail,resource_ref,item_id,related_deployment_id,status(open/resolved/expired),first_at,last_at,resolved_at
rules        rule_key,name,level,enabled
```
约束：`resources` 唯一 `(credential_id, resource_type, resource_id)`；同步为**全量替换式**。

## 7. M2 — 告警接收与归一化（设计）

### 7.1 统一模型 alert_events
外部告警经适配落到统一字段：`source`、`dedup_key`、`level`（映射高/中/低）、`title/detail`、`resource_ref`、`status` 状态机。

### 7.2 接收通道
| 通道 | 说明 |
|---|---|
| 内部规则 | 平台采样(5s)→规则检测→内部事件（error_rate/latency/心跳 3 条种子规则） |
| Prometheus Alertmanager | POST `/api/webhooks/alertmanager`，适配标准 `alerts[]` |
| 通用 Webhook | POST `/api/webhooks/generic`，接受 `{title,level,resource,detail,status}` + 可选令牌 |
| （二期）阿里云云监控 | 告警回调 JSON 适配 |

### 7.3 处理流水线
```
接收 → 格式适配(级别映射/时间解析) → 资源匹配CMDB → 去重(dedup_key+open窗口合并)
     → 变更关联(30min 同服务发布) → 落库 → 展示/通知
恢复事件→resolved；超时→expired
```

## 8. M3 — 变更关联 + AI 分析（设计）

- 变更关联：告警产生时查该服务最近 30 分钟发布 → `related_deployment_id`，UI 紫色标签「⚠️ v1.3.0」。
- AI：`POST /api/ai/explain {alert_id}` 组装上下文（指标采样+最近发布+资源/账号归属）→ OpenAI 兼容 chat API → 输出"最可能原因 + 分步处置"；未配 key 自动回退规则启发式。可解释/零样本/可回退。
- Prompt 骨架：`你是一名资深 SRE… 结合"最近发布"与指标拐点判断因果…`（temperature=0.2）。

## 9. M4 — GitHub 发布

`.github/workflows/ci.yml`：push main / tag `v*` → 语法检查 → 构建推送 GHCR（`latest`+`:tag`）→（可选）上报发布。配套 Dockerfile / docker-compose.yml / scripts/report-release.sh / Apache-2.0 LICENSE。

## 10. API 概览（现状）

```
GET/POST      /api/credentials（POST /{id}/test、/sync）
GET           /api/resources（?credential_id&resource_type&keyword&page）; /api/resources/{id}（含 linked_items）
GET/POST/DEL  /api/cmdb/items ; GET /api/cmdb/items/{id}（聚合资源带账号）; POST /link、DELETE /link/{rid}
GET/POST      /api/deployments（发布上报：github-actions/cli/manual）
GET           /api/overview ; GET /api/providers
M2 新增        /api/webhooks/alertmanager、/api/webhooks/generic、/api/alerts、/api/rules
M3 新增        /api/ai/explain
```

## 11. 技术栈

FastAPI + SQLite(WAL) + 原生前端（原生 JS/CSS、canvas、零构建）+ prometheus_client(`/metrics`) + Docker Compose + GitHub Actions(GHCR)
Provider 抽象：`providers/base.py` → demo/aliyun 实现 → registry 注册扩展。

## 12. 里程碑与验收

| 阶段 | 内容 | 验收标准 | tag |
|---|---|---|---|
| M1 ✅ | 账号+资源归属+业务服务关联 | 任一资源能查到所属账号与信息 | v0.1.0 |
| M2 | 告警接收归一化 | curl 模拟 Alertmanager/通用 webhook → 正确入库、归一到资源、去重 | v0.2.0 |
| M3 | 变更关联+AI | 模拟故障发布→告警→关联发布→AI 建议全链路 | v0.3.0 |
| M4 | 发布打磨 | tag 即出镜像，按 DEPLOY.md 可复现部署 | v1.0.0 |
