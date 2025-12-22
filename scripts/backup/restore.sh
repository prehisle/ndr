#!/usr/bin/env bash
#
# PostgreSQL 数据库恢复脚本
# 用法: ./restore.sh [选项]
#
# 选项:
#   --list                    列出所有可用备份
#   --file <backup_file>      指定要恢复的备份文件
#   --latest                  恢复最新的备份
#   --config <config_file>    使用自定义配置文件
#   --backend <backend>       指定存储后端
#   --force                   跳过确认提示
#   --dry-run                 模拟运行，不实际执行恢复
#
# 示例:
#   ./restore.sh --list
#   ./restore.sh --latest
#   ./restore.sh --file ndr_20250101_030000.sql.gz
#   ./restore.sh --file ndr_20250101_030000.sql.gz --force
#

set -euo pipefail

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================
# 默认值
# ============================================================

CONFIG_FILE="${SCRIPT_DIR}/config.sh"
BACKEND_OVERRIDE=""
ACTION=""
BACKUP_FILE=""
FORCE_RESTORE=false
DRY_RUN=false

# ============================================================
# 参数解析
# ============================================================

while [[ $# -gt 0 ]]; do
    case "$1" in
        --list)
            ACTION="list"
            shift
            ;;
        --file)
            ACTION="restore"
            BACKUP_FILE="$2"
            shift 2
            ;;
        --latest)
            ACTION="restore_latest"
            shift
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --backend)
            BACKEND_OVERRIDE="$2"
            shift 2
            ;;
        --force)
            FORCE_RESTORE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            head -20 "$0" | tail -18
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

if [[ -n "${BACKEND_OVERRIDE}" ]]; then
    STORAGE_BACKEND="${BACKEND_OVERRIDE}"
fi

BACKEND_FILE="${SCRIPT_DIR}/backends/${STORAGE_BACKEND}.sh"
if [[ ! -f "${BACKEND_FILE}" ]]; then
    log_error "存储后端不存在: ${BACKEND_FILE}"
    exit 1
fi

# shellcheck disable=SC1090
source "${BACKEND_FILE}"

# ============================================================
# 函数定义
# ============================================================

# 列出可用备份
list_backups() {
    log_info "可用备份列表 (存储后端: ${STORAGE_BACKEND}):"
    echo ""

    local backups
    backups=$(backend_list)

    if [[ -z "${backups}" ]]; then
        echo "  (无可用备份)"
    else
        local index=1
        while IFS= read -r backup; do
            local filename size
            filename=$(basename "${backup}")

            # 尝试获取文件大小
            if [[ -f "${backup}" ]]; then
                size=$(du -h "${backup}" | cut -f1)
                printf "  %2d. %-40s (%s)\n" "${index}" "${filename}" "${size}"
            else
                printf "  %2d. %s\n" "${index}" "${filename}"
            fi
            ((index++))
        done <<< "${backups}"
    fi

    echo ""
    backend_stats
}

# 获取最新备份
get_latest_backup() {
    backend_list | head -1 | xargs -r basename 2>/dev/null || echo ""
}

# 执行恢复
do_restore() {
    local backup_name="$1"

    # 校验文件名安全性
    if ! validate_backup_filename "${backup_name}"; then
        log_error "备份文件名校验失败，操作中止"
        exit 1
    fi

    local temp_file
    temp_file=$(create_temp_file "restore")
    trap 'rm -f "${temp_file}"' EXIT

    log_info "=========================================="
    log_info "开始数据库恢复"
    log_info "=========================================="
    log_info "备份文件: ${backup_name}"
    log_info "目标数据库: ${POSTGRES_DB}"
    log_info "存储后端: ${STORAGE_BACKEND}"

    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "[模拟运行] 将执行以下操作："
        log_info "  1. 从 ${STORAGE_BACKEND} 获取备份文件"
        log_info "  2. 解压缩（如果需要）"
        log_info "  3. 使用 psql 恢复到数据库 ${POSTGRES_DB}"
        log_info "[模拟运行] 实际未执行任何操作"
        return 0
    fi

    # 确认操作
    if [[ "${FORCE_RESTORE}" != "true" ]]; then
        echo ""
        log_warn "警告: 此操作将覆盖现有数据库内容!"
        log_warn "数据库: ${POSTGRES_DB}"
        echo ""
        read -r -p "确定要继续吗? (输入 'yes' 确认): " confirm
        if [[ "${confirm}" != "yes" ]]; then
            log_info "操作已取消"
            exit 0
        fi
    fi

    # 从存储后端获取备份文件
    log_info "正在获取备份文件..."
    if ! backend_get "${backup_name}" "${temp_file}"; then
        log_error "获取备份文件失败"
        exit 1
    fi

    # 获取 Docker Compose 命令
    COMPOSE_CMD=$(get_compose_cmd)
    if [[ -z "${COMPOSE_CMD}" ]]; then
        log_error "未找到 docker compose 命令"
        rm -f "${temp_file}"
        exit 1
    fi

    # 检查容器是否运行
    if ! ${COMPOSE_CMD} -f "${COMPOSE_FILE}" ps "${DB_SERVICE}" 2>/dev/null | grep -q "running\|Up"; then
        log_error "数据库容器未运行"
        rm -f "${temp_file}"
        exit 1
    fi

    # 执行恢复
    log_info "正在恢复数据库..."

    if [[ "${backup_name}" == *.gz ]]; then
        # 解压缩后恢复
        if gunzip -c "${temp_file}" | ${COMPOSE_CMD} -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
            psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -1 --quiet; then
            log_info "数据库恢复成功"
        else
            log_error "数据库恢复失败"
            rm -f "${temp_file}"
            exit 1
        fi
    else
        # 直接恢复
        if ${COMPOSE_CMD} -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
            psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -1 --quiet < "${temp_file}"; then
            log_info "数据库恢复成功"
        else
            log_error "数据库恢复失败"
            rm -f "${temp_file}"
            exit 1
        fi
    fi

    # 清理临时文件
    rm -f "${temp_file}"

    log_info "=========================================="
    log_info "恢复完成"
    log_info "=========================================="
}

# ============================================================
# 主流程
# ============================================================

main() {
    case "${ACTION}" in
        list)
            list_backups
            ;;
        restore)
            if [[ -z "${BACKUP_FILE}" ]]; then
                log_error "请指定备份文件: --file <backup_file>"
                exit 1
            fi
            do_restore "${BACKUP_FILE}"
            ;;
        restore_latest)
            local latest
            latest=$(get_latest_backup)
            if [[ -z "${latest}" ]]; then
                log_error "没有可用的备份"
                exit 1
            fi
            log_info "最新备份: ${latest}"
            do_restore "${latest}"
            ;;
        *)
            echo "用法: $0 [--list | --latest | --file <backup_file>]"
            echo "使用 --help 查看详细帮助"
            exit 1
            ;;
    esac
}

main
