#!/usr/bin/env bash
#
# PostgreSQL 数据库备份脚本
# 用法: ./backup.sh [--config <config_file>] [--backend <local|s3|nas>]
#
# 示例:
#   ./backup.sh                           # 使用默认配置
#   ./backup.sh --backend s3              # 使用 S3 存储后端
#   ./backup.sh --config /path/to/config  # 使用自定义配置文件
#

set -euo pipefail

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================
# 参数解析
# ============================================================

CONFIG_FILE="${SCRIPT_DIR}/config.sh"
BACKEND_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --backend)
            BACKEND_OVERRIDE="$2"
            shift 2
            ;;
        --help|-h)
            echo "用法: $0 [--config <config_file>] [--backend <local|s3|nas>]"
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

# ============================================================
# 加载配置
# ============================================================

if [[ ! -f "${CONFIG_FILE}" ]]; then
    echo "[ERROR] 配置文件不存在: ${CONFIG_FILE}" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "${CONFIG_FILE}"

# 覆盖存储后端（如果指定）
if [[ -n "${BACKEND_OVERRIDE}" ]]; then
    STORAGE_BACKEND="${BACKEND_OVERRIDE}"
fi

# 加载存储后端
BACKEND_FILE="${SCRIPT_DIR}/backends/${STORAGE_BACKEND}.sh"
if [[ ! -f "${BACKEND_FILE}" ]]; then
    log_error "存储后端不存在: ${BACKEND_FILE}"
    exit 1
fi

# shellcheck disable=SC1090
source "${BACKEND_FILE}"

# ============================================================
# 主流程
# ============================================================

main() {
    local start_time end_time duration
    local backup_filename temp_file
    local exit_code=0

    start_time=$(date +%s)

    log_info "=========================================="
    log_info "开始 PostgreSQL 数据库备份"
    log_info "=========================================="
    log_info "数据库: ${POSTGRES_DB}"
    log_info "存储后端: ${STORAGE_BACKEND}"
    log_info "压缩: ${ENABLE_COMPRESSION}"

    # 确保目录存在
    ensure_directories

    # 生成备份文件名
    backup_filename=$(generate_backup_filename)
    temp_file=$(create_temp_file "backup")
    trap 'rm -f "${temp_file}"' EXIT

    log_info "备份文件名: ${backup_filename}"

    # 获取 Docker Compose 命令
    COMPOSE_CMD=$(get_compose_cmd)
    if [[ -z "${COMPOSE_CMD}" ]]; then
        log_error "未找到 docker compose 命令"
        exit 1
    fi

    # 检查 compose 文件是否存在
    if [[ ! -f "${COMPOSE_FILE}" ]]; then
        log_error "Docker Compose 文件不存在: ${COMPOSE_FILE}"
        exit 1
    fi

    # 检查容器是否运行
    if ! ${COMPOSE_CMD} -f "${COMPOSE_FILE}" ps "${DB_SERVICE}" 2>/dev/null | grep -q "running\|Up"; then
        log_error "数据库容器未运行"
        exit 1
    fi

    # 执行备份
    log_info "正在执行 pg_dump..."

    if [[ "${ENABLE_COMPRESSION}" == "true" ]]; then
        # 压缩备份
        if ${COMPOSE_CMD} -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
            pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
            --no-owner --no-acl --clean --if-exists \
            | gzip > "${temp_file}"; then
            log_info "pg_dump 完成（已压缩）"
        else
            log_error "pg_dump 失败"
            exit_code=1
        fi
    else
        # 不压缩
        if ${COMPOSE_CMD} -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
            pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
            --no-owner --no-acl --clean --if-exists \
            > "${temp_file}"; then
            log_info "pg_dump 完成"
        else
            log_error "pg_dump 失败"
            exit_code=1
        fi
    fi

    # 验证备份文件
    if [[ ${exit_code} -eq 0 ]]; then
        if [[ ! -s "${temp_file}" ]]; then
            log_error "备份文件为空"
            exit_code=1
        else
            local file_size
            file_size=$(du -h "${temp_file}" | cut -f1)
            log_info "备份文件大小: ${file_size}"
        fi
    fi

    # 保存到存储后端
    if [[ ${exit_code} -eq 0 ]]; then
        if backend_save "${temp_file}" "${backup_filename}"; then
            log_info "备份已成功保存"
        else
            log_error "保存备份失败"
            exit_code=1
        fi
    fi

    # 清理临时文件
    rm -f "${temp_file}"

    # 执行备份轮转
    if [[ ${exit_code} -eq 0 ]]; then
        log_info "执行备份轮转（保留 ${BACKUP_RETENTION_DAYS} 天）..."
        backend_cleanup "${BACKUP_RETENTION_DAYS}"
    fi

    # 输出统计信息
    backend_stats

    # 计算耗时
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    log_info "=========================================="
    if [[ ${exit_code} -eq 0 ]]; then
        log_info "备份完成，耗时 ${duration} 秒"
    else
        log_error "备份失败，耗时 ${duration} 秒"
    fi
    log_info "=========================================="

    return ${exit_code}
}

# 运行主流程，并将输出同时写入日志文件
ensure_directories
LOG_FILE="${LOG_DIR}/backup_$(date +%Y%m%d).log"
main 2>&1 | tee -a "${LOG_FILE}"
exit ${PIPESTATUS[0]}
