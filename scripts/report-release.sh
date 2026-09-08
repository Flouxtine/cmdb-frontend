#!/usr/bin/env bash
# 发布上报：AIOPS_URL=http://host:8080 ./scripts/report-release.sh <service> <version> [commit] [author]
set -e
AIOPS_URL="${AIOPS_URL:-http://127.0.0.1:8080}"
SERVICE="${1:?服务名}"; VERSION="${2:?版本号}"; COMMIT="${3:-}"; AUTHOR="${4:-$USER}"
curl -s -X POST "$AIOPS_URL/api/deployments" -H "Content-Type: application/json" \
  -d "{\"service\":\"$SERVICE\",\"version\":\"$VERSION\",\"commit\":\"$COMMIT\",\"author\":\"$AUTHOR\",\"source\":\"cli\"}"
echo "  → 已上报 $SERVICE@$VERSION"
