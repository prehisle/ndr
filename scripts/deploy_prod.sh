#!/usr/bin/env bash

set -euo pipefail

REMOTE_HOST=${REMOTE_HOST:-192.168.1.31}
REMOTE_USER=${REMOTE_USER:-dy_prod}
REMOTE_DIR=${REMOTE_DIR:-/home/${REMOTE_USER}/ndr9000}
COMPOSE_SOURCE=${COMPOSE_SOURCE:-deploy/production/docker-compose.yml}
ENV_SOURCE=${ENV_SOURCE:-deploy/production/.env}
REGISTRY_HOST=${REGISTRY_HOST:-ghcr.io}
REGISTRY_USERNAME=${REGISTRY_USERNAME:-}
REGISTRY_PASSWORD=${REGISTRY_PASSWORD:-}
COMPOSE_PULL_SERVICE=${COMPOSE_PULL_SERVICE:-app}
BACKUP_SCRIPTS_SOURCE=${BACKUP_SCRIPTS_SOURCE:-scripts/backup}
SYNC_BACKUP_SCRIPTS=${SYNC_BACKUP_SCRIPTS:-true}

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"

log() {
  printf '[deploy] %s\n' "$*"
}

require_file() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    printf '[deploy][错误] 未找到文件：%s\n' "$file_path" >&2
    exit 1
  fi
}

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf '[deploy][错误] 本地缺少命令：%s\n' "$cmd" >&2
    exit 1
  fi
}

require_file "$COMPOSE_SOURCE"
require_file "$ENV_SOURCE"
require_command scp
require_command ssh

log "在远端创建部署目录 ${REMOTE_DIR}"
ssh "$SSH_TARGET" REMOTE_DIR="$REMOTE_DIR" 'bash -s' <<'EOF'
set -euo pipefail
mkdir -p "$REMOTE_DIR" "$REMOTE_DIR/runtime" "$REMOTE_DIR/data"
mkdir -p "$REMOTE_DIR/scripts/backup/backends" "$REMOTE_DIR/backups/daily" "$REMOTE_DIR/backups/logs"
EOF

log "同步 docker-compose.yml 与 .env"
scp "$COMPOSE_SOURCE" "$SSH_TARGET:${REMOTE_DIR}/docker-compose.yml"
scp "$ENV_SOURCE" "$SSH_TARGET:${REMOTE_DIR}/.env"

# 同步备份脚本
if [[ "${SYNC_BACKUP_SCRIPTS}" == "true" ]] && [[ -d "${BACKUP_SCRIPTS_SOURCE}" ]]; then
  log "同步备份脚本到远端"
  scp -r "${BACKUP_SCRIPTS_SOURCE}/"* "$SSH_TARGET:${REMOTE_DIR}/scripts/backup/"
  ssh "$SSH_TARGET" REMOTE_DIR="$REMOTE_DIR" 'bash -s' <<'EOF'
chmod +x "$REMOTE_DIR/scripts/backup/"*.sh "$REMOTE_DIR/scripts/backup/backends/"*.sh 2>/dev/null || true
EOF
fi

log "在远端拉取镜像并更新服务"
ssh "$SSH_TARGET" \
  REMOTE_DIR="$REMOTE_DIR" \
  REGISTRY_HOST="$REGISTRY_HOST" \
  REGISTRY_USERNAME="$REGISTRY_USERNAME" \
  REGISTRY_PASSWORD="$REGISTRY_PASSWORD" \
  COMPOSE_PULL_SERVICE="$COMPOSE_PULL_SERVICE" 'bash -s' <<'EOF'
set -euo pipefail

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[deploy][错误] 未找到 docker compose 或 docker-compose 命令" >&2
  exit 1
fi

cd "$REMOTE_DIR"

if [[ -n "$REGISTRY_USERNAME" && -n "$REGISTRY_PASSWORD" ]]; then
  echo "$REGISTRY_PASSWORD" | docker login "$REGISTRY_HOST" -u "$REGISTRY_USERNAME" --password-stdin >/dev/null
fi

if [[ -n "$COMPOSE_PULL_SERVICE" ]]; then
  "${COMPOSE_CMD[@]}" pull "$COMPOSE_PULL_SERVICE"
else
  "${COMPOSE_CMD[@]}" pull
fi

"${COMPOSE_CMD[@]}" up -d --force-recreate --remove-orphans

if [[ -n "$REGISTRY_USERNAME" && -n "$REGISTRY_PASSWORD" ]]; then
  docker logout "$REGISTRY_HOST" >/dev/null || true
fi
EOF

log "部署完成"
