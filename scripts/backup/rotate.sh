#!/usr/bin/env bash
#
# 备份轮转脚本
# 用法: ./rotate.sh [--days <N>] [--dry-run]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 加载配置
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/config.sh"
# shellcheck disable=SC1090
source "${SCRIPT_DIR}/backends/${STORAGE_BACKEND}.sh"

# 参数
RETENTION_DAYS="${BACKUP_RETENTION_DAYS}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --days)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "用法: $0 [--days <N>] [--dry-run]"
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

log_info "执行备份轮转"
log_info "保留天数: ${RETENTION_DAYS}"
log_info "存储后端: ${STORAGE_BACKEND}"

if [[ "${DRY_RUN}" == "true" ]]; then
    log_info "[模拟运行] 以下备份将被删除:"

    if [[ "${STORAGE_BACKEND}" == "local" ]]; then
        find "${BACKUP_DIR}" -name "${BACKUP_PREFIX}_*.sql*" -type f -mtime +"${RETENTION_DAYS}" -print 2>/dev/null || true
    fi
else
    backend_cleanup "${RETENTION_DAYS}"
fi

log_info "轮转完成"
backend_stats
