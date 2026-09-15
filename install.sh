#!/usr/bin/env bash
# OpsScope 一键部署脚本（Linux/macOS）
# 用法:
#   ./install.sh                    拉取 GHCR 镜像部署（默认端口 8080）
#   ./install.sh --build            本地构建镜像（Dockerfile）
#   ./install.sh --port=9090        指定对外端口
set -e
cd "$(dirname "$0")"

MODE="pull"
PORT="8080"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --build) MODE="build"; shift ;;
    --port=*) PORT="${1#*=}"; shift ;;
    --help|-h) echo "用法: ./install.sh [--build] [--port=PORT]"; exit 0 ;;
    *) echo "未知参数: $1（--help 查看用法）"; exit 1 ;;
  esac
done

# ---- 1) 检测 Docker ----
command -v docker >/dev/null 2>&1 || { echo "❌ 需要 Docker：https://docs.docker.com/get-docker/"; exit 1; }
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "❌ 需要 docker compose 插件"; exit 1
fi
echo "✅ Docker 已安装（$(docker --version)）"

# ---- 2) .env ----
if [ ! -f .env ]; then
  cp .env.example .env
  echo "✅ 已生成 .env（可编辑 PORT / LLM_API_KEY 等，见 .env.example 注释）"
fi
# 端口写入/更新
if grep -q "^PORT=" .env 2>/dev/null; then
  sed -i.bak "s/^PORT=.*/PORT=$PORT/" .env && rm -f .env.bak
else
  echo "PORT=$PORT" >> .env
fi
echo "✅ 对外端口: $PORT"

# ---- 3) 镜像 ----
if [ "$MODE" = "build" ]; then
  echo "🛠 本地构建镜像（首次需数分钟）..."
  $DC build || { echo "❌ 构建失败，查看上方日志"; exit 1; }
else
  echo "📦 拉取镜像 ghcr.io/flouxtine/cmdb-frontend:latest ..."
  $DC pull || { echo "❌ 拉取失败，尝试 --build 本地构建"; exit 1; }
fi

# ---- 4) 启动 ----
$DC up -d || { echo "❌ 启动失败：$DC logs"; exit 1; }

# ---- 5) 健康检查 ----
echo -n "⏳ 等待服务就绪"
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/api/overview" >/dev/null 2>&1; then
    echo ""
    echo "✅ OpsScope（观云台）已就绪：http://127.0.0.1:$PORT"
    echo "   查看日志: $DC logs -f"
    exit 0
  fi
  echo -n "."
  sleep 2
done
echo ""
echo "⚠️  60s 内未就绪，请检查：$DC logs"
exit 1
