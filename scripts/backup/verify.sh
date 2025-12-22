#!/usr/bin/env bash
#
# PostgreSQL 备份验证脚本
# 用法: ./verify.sh [--file <backup_file>] [--latest]
#
# 验证内容:
#   1. 备份文件完整性（解压测试）
#   2. SQL 结构检查（统计表数量）
#   3. Dump 结尾完整性
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 加载配置
CONFIG_FILE="${SCRIPT_DIR}/config.sh"

# shellcheck disable=SC1090
source "${CONFIG_FILE}"

BACKEND_FILE="${SCRIPT_DIR}/backends/${STORAGE_BACKEND}.sh"
# shellcheck disable=SC1090
source "${BACKEND_FILE}"

# 参数解析
BACKUP_FILE=""
CHECK_LATEST=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --file)
            BACKUP_FILE="$2"
            shift 2
            ;;
        --latest)
            CHECK_LATEST=true
            shift
            ;;
        --help|-h)
            echo "用法: $0 [--file <backup_file>] [--latest]"
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

# 获取要验证的备份文件
if [[ "${CHECK_LATEST}" == "true" ]]; then
    BACKUP_FILE=$(backend_list | head -1 | xargs -r basename 2>/dev/null || echo "")
fi

if [[ -z "${BACKUP_FILE}" ]]; then
    echo "请指定备份文件: --file <backup_file> 或 --latest"
    exit 1
fi

log_info "=========================================="
log_info "备份验证: ${BACKUP_FILE}"
log_info "=========================================="

# 创建临时目录
TEMP_DIR=$(mktemp -d)
trap 'rm -rf ${TEMP_DIR}' EXIT

# 获取备份文件
log_info "获取备份文件..."
TEMP_FILE="${TEMP_DIR}/${BACKUP_FILE}"
if ! backend_get "${BACKUP_FILE}" "${TEMP_FILE}"; then
    log_error "获取备份文件失败"
    exit 1
fi

# 验证 1: 文件完整性
log_info "验证文件完整性..."
if [[ "${BACKUP_FILE}" == *.gz ]]; then
    if gunzip -t "${TEMP_FILE}" 2>/dev/null; then
        log_info "[通过] Gzip 压缩文件完整"
        # 解压用于后续检查
        UNCOMPRESSED="${TEMP_DIR}/backup.sql"
        gunzip -c "${TEMP_FILE}" > "${UNCOMPRESSED}"
    else
        log_error "[失败] Gzip 文件损坏"
        exit 1
    fi
else
    UNCOMPRESSED="${TEMP_FILE}"
    log_info "[跳过] 非压缩文件"
fi

# 验证 2: 文件大小
FILE_SIZE=$(du -h "${TEMP_FILE}" | cut -f1)
UNCOMPRESSED_SIZE=$(du -h "${UNCOMPRESSED}" | cut -f1)
log_info "压缩大小: ${FILE_SIZE}"
log_info "解压大小: ${UNCOMPRESSED_SIZE}"

# 验证 3: SQL 基本结构
log_info "验证 SQL 结构..."

# 检查是否包含 PostgreSQL dump 标记
if head -50 "${UNCOMPRESSED}" | grep -q "PostgreSQL database dump"; then
    log_info "[通过] 包含 PostgreSQL dump 头"
else
    log_warn "[警告] 未找到 PostgreSQL dump 头"
fi

# 统计表数量
TABLE_COUNT=$(grep -c "^CREATE TABLE" "${UNCOMPRESSED}" || echo "0")
log_info "CREATE TABLE 语句数: ${TABLE_COUNT}"

# 统计索引数量
INDEX_COUNT=$(grep -c -E "^CREATE INDEX|^CREATE UNIQUE INDEX" "${UNCOMPRESSED}" || echo "0")
log_info "CREATE INDEX 语句数: ${INDEX_COUNT}"

# 检查是否有数据
INSERT_COUNT=$(grep -c -E "^INSERT INTO|^COPY .* FROM stdin" "${UNCOMPRESSED}" || echo "0")
log_info "数据导入语句数: ${INSERT_COUNT}"

# 验证 4: 检查结尾完整性
if tail -20 "${UNCOMPRESSED}" | grep -q "PostgreSQL database dump complete"; then
    log_info "[通过] dump 结尾完整"
else
    log_warn "[警告] 未找到 dump 结尾标记，文件可能不完整"
fi

log_info "=========================================="
log_info "验证完成"
log_info "=========================================="
