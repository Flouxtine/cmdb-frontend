# OpsScope 部署文档

> 适用版本：v0.1.0（M1：账号管理 + 云资源 CMDB + 业务服务关联）
> 推荐部署方式：**Docker Compose**（源码 / GHCR 镜像二选一）

## 1. 架构与组件

| 组件 | 说明 |
|---|---|
| OpsScope 主服务 | FastAPI + 内置前端单页，**单容器**（自带 SQLite，无外部依赖） |
| 数据 | SQLite（WAL），挂载卷持久化；含凭据加密密钥 `.secret` |
| 外部可选 | LLM API（M3 AI 分析用）；Prometheus（可抓 `/metrics`） |

## 2. 前置要求

- Linux/macOS（Windows 用 WSL2）；Docker ≥ 20.10（含 compose 插件）
- ≥ 512MB RAM；镜像约 300MB；数据卷小（万级资源 ≈ 几十 MB）
- 端口默认 8080（`PORT` 可改）

## 3. 获取方式

### A. 源码构建
```bash
git clone git@github.com:Flouxtine/cmdb-frontend.git && cd cmdb-frontend
cp .env.example .env
docker compose up -d --build
```

### B. 使用 GitHub 发布镜像（推荐生产）
```bash
# docker-compose.yml 中 image: ghcr.io/flouxtine/cmdb-frontend:0.1.0
docker compose pull && docker compose up -d
```

## 4. 快速部署

```bash
cp .env.example .env        # 按需修改 PORT / LLM key（可选）
docker compose up -d
curl -s http://127.0.0.1:8080/api/overview   # 验证
```
访问 `http://<IP>:8080`。

## 5. 配置清单（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` | `8080` | 对外端口（容器内 8000） |
| `SERVICE_NAME` | `opsscope` | 服务标识 |
| `LLM_API_KEY` | 空 | M3 AI 密钥（OpenAI 兼容）；留空走内置规则回退 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | 任意兼容端点 |
| `LLM_MODEL` | `deepseek-chat` | 模型 |

数据目录 `./data`（容器 `/data`）：`opsscope.db` 全部业务数据；`.secret` 凭据加密密钥（**随卷备份，丢失无法解密 AK/SK**）。

## 6. 首次使用

1. 「云账号」添加：**演示环境**（免密钥，同步得 12 示例资源）或**阿里云**（RAM 只读 AK/SK + Region）
2. 「云资源 CMDB」查看资源及其所属账号
3. 「业务服务」新增服务并绑定资源 → 服务→资源→账号 视图

## 7. 升级 / 8. 备份恢复

```bash
docker compose pull && docker compose up -d        # 升级（数据卷不动）
docker compose stop && tar -czf bak.tar.gz ./data && docker compose start   # 备份
```
恢复：解压替换 `./data` 后 `docker compose up -d`。

## 9. 健康检查与日志

```bash
docker compose ps          # HEALTHCHECK 每 30s 探测 /api/overview
docker logs -f opsscope
```
平台自身暴露 `/metrics`（Prometheus 格式）。

## 10. 安全建议

- 内网为主；外网访问置于反向代理 + TLS
- 云账号 RAM 子账号最小只读；AK/SK 加密存储
- `.env` 权限 `chmod 600`，勿提交仓库
- 备份时 `.db` 与 `.secret` 一起拷贝

## 11. 卸载

```bash
docker compose down && rm -rf ./data
```

## 12. FAQ

| 现象 | 处理 |
|---|---|
| 端口占用 | 改 `.env` PORT 后 `up -d` |
| 阿里云同步部分失败 | 看返回 `errors`，多为 RAM 权限/Region；补授权重试 |
| 容器起不来 | `docker compose logs opsscope` |
| .secret 丢失 | 凭据需重新录入 |
| M3 AI 无输出 | 未配 key 走规则回退属正常设计 |

## 13. 与 GitHub 发布流水线

`.github/workflows/ci.yml`：push `v*` tag → 检查 → 构建推送 GHCR → 上报发布。
```bash
git tag v0.1.0 && git push origin v0.1.0
```
上报：CI 配 `secrets.OPS_SCOPE_WEBHOOK_URL`，或 `AIOPS_URL=http://host:8080 ./scripts/report-release.sh <服务> <版本> <commit> <作者>`。

## 14. 无 Docker 源码部署（备选）

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
OPS_SCOPE_DATA=$PWD/data ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```
