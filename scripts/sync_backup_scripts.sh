#!/usr/bin/env bash
#
# 同步备份脚本到生产服务器
# 用法: ./sync_backup_scripts.sh
#
# 此脚本将 scripts/backup 目录同步到生产服务器
#

set -euo pipefail

# 配置（可通过环境变量覆盖）
REMOTE_HOST=${REMOTE_HOST:-192.168.1.31}
REMOTE_USER=${REMOTE_USER:-dy_prod}
REMOTE_DIR=${REMOTE_DIR:-/home/${REMOTE_USER}/ndr9000}

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPTS_DIR="${SCRIPT_DIR}/backup"

log() {
    printf '[sync] %s\n' "$*"
}

# 检查本地备份脚本目录是否存在
if [[ ! -d "${BACKUP_SCRIPTS_DIR}" ]]; then
    printf '[sync][错误] 备份脚本目录不存在: %s\n' "${BACKUP_SCRIPTS_DIR}" >&2
    exit 1
fi

# 检查必要命令
for cmd in scp ssh; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        printf '[sync][错误] 本地缺少命令: %s\n' "$cmd" >&2
        exit 1
    fi
done

log "同步备份脚本到 ${SSH_TARGET}:${REMOTE_DIR}/scripts/"

# 在远端创建目录
log "在远端创建脚本目录..."
ssh "$SSH_TARGET" REMOTE_DIR="$REMOTE_DIR" 'bash -s' <<'EOF'
set -euo pipefail
mkdir -p "$REMOTE_DIR/scripts/backup/backends" "$REMOTE_DIR/backups/daily" "$REMOTE_DIR/backups/logs"
EOF

# 同步脚本文件
log "上传备份脚本..."
scp -r "${BACKUP_SCRIPTS_DIR}/"* "${SSH_TARGET}:${REMOTE_DIR}/scripts/backup/"

# 设置执行权限
log "设置执行权限..."
ssh "$SSH_TARGET" REMOTE_DIR="$REMOTE_DIR" 'bash -s' <<'EOF'
chmod +x "$REMOTE_DIR/scripts/backup/"*.sh "$REMOTE_DIR/scripts/backup/backends/"*.sh 2>/dev/null || true
EOF

log "同步完成"
log ""
log "后续步骤:"
log "  1. 登录生产服务器: ssh ${SSH_TARGET}"
log "  2. 测试备份: cd ${REMOTE_DIR} && ./scripts/backup/backup.sh"
log "  3. 配置定时任务: crontab -e"
log ""
log "Cron 配置示例:"
log "  0 3 * * * ${REMOTE_DIR}/scripts/backup/backup.sh >> ${REMOTE_DIR}/backups/logs/cron.log 2>&1"
