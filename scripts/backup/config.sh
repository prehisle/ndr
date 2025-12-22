#!/usr/bin/env bash
# PostgreSQL 备份配置文件
# 使用方式：source scripts/backup/config.sh

# ============================================================
# 基础配置
# ============================================================

# Docker Compose 项目目录（生产服务器上的路径）
COMPOSE_DIR="${COMPOSE_DIR:-/home/dy_prod/ndr9000}"

# Docker Compose 文件路径
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"

# PostgreSQL 容器服务名
DB_SERVICE="${DB_SERVICE:-db}"

# 备份根目录
BACKUP_ROOT="${BACKUP_ROOT:-${COMPOSE_DIR}/backups}"

# 备份子目录
BACKUP_DIR="${BACKUP_ROOT}/daily"
LOG_DIR="${BACKUP_ROOT}/logs"

# ============================================================
# 数据库配置（从 .env 文件读取或使用默认值）
# ============================================================

# 加载 .env 文件
if [[ -f "${COMPOSE_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${COMPOSE_DIR}/.env"
    set +a
fi

POSTGRES_DB="${POSTGRES_DB:-ndr}"
POSTGRES_USER="${POSTGRES_USER:-ndr}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-ndr}"

# ============================================================
# 备份策略配置
# ============================================================

# 保留天数（备份轮转）
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"

# 备份文件名前缀
BACKUP_PREFIX="${BACKUP_PREFIX:-ndr}"

# 备份文件时间戳格式
TIMESTAMP_FORMAT="${TIMESTAMP_FORMAT:-%Y%m%d_%H%M%S}"

# 是否启用压缩
ENABLE_COMPRESSION="${ENABLE_COMPRESSION:-true}"

# ============================================================
# 存储后端配置
# ============================================================

# 当前使用的存储后端：local, s3, nas
STORAGE_BACKEND="${STORAGE_BACKEND:-local}"

# S3 配置（预留）
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-backups/ndr}"
S3_ENDPOINT="${S3_ENDPOINT:-}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}"

# NAS 配置（预留）
NAS_MOUNT_POINT="${NAS_MOUNT_POINT:-}"
NAS_BACKUP_PATH="${NAS_BACKUP_PATH:-}"

# ============================================================
# 通知配置（预留）
# ============================================================

# 备份失败时是否发送通知
NOTIFY_ON_FAILURE="${NOTIFY_ON_FAILURE:-false}"

# 通知方式：email, slack, webhook
NOTIFY_METHOD="${NOTIFY_METHOD:-}"

# ============================================================
# 辅助函数
# ============================================================

# 获取 Docker Compose 命令
get_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
    else
        echo ""
    fi
}

# 日志函数
log_info() {
    printf '[%s][INFO] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log_warn() {
    printf '[%s][WARN] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

log_error() {
    printf '[%s][ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

# 生成备份文件名
generate_backup_filename() {
    local timestamp
    timestamp=$(date +"${TIMESTAMP_FORMAT}")
    local filename="${BACKUP_PREFIX}_${timestamp}.sql"
    if [[ "${ENABLE_COMPRESSION}" == "true" ]]; then
        filename="${filename}.gz"
    fi
    echo "${filename}"
}

# 校验备份文件名（防止路径穿越攻击）
validate_backup_filename() {
    local filename="$1"
    # 文件名必须是 basename（不含路径分隔符）
    if [[ "${filename}" != "$(basename -- "${filename}")" ]]; then
        log_error "无效的备份文件名（包含路径分隔符）: ${filename}"
        return 1
    fi
    # 不允许 .. 或空字节
    if [[ "${filename}" == *".."* ]] || [[ "${filename}" == *$'\0'* ]]; then
        log_error "无效的备份文件名（包含非法字符）: ${filename}"
        return 1
    fi
    # 必须匹配预期格式: prefix_YYYYMMDD_HHMMSS.sql[.gz]
    if ! [[ "${filename}" =~ ^${BACKUP_PREFIX}_[0-9]{8}_[0-9]{6}\.sql(\.gz)?$ ]]; then
        log_error "备份文件名格式不匹配: ${filename}"
        return 1
    fi
    return 0
}

# 创建安全的临时文件
create_temp_file() {
    local prefix="${1:-backup}"
    mktemp -p "${TMPDIR:-/tmp}" "${prefix}.XXXXXX"
}

# 确保目录存在
ensure_directories() {
    mkdir -p "${BACKUP_DIR}" "${LOG_DIR}"
}
