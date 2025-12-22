#!/usr/bin/env bash
# 本地存储后端

# 保存备份到本地
backend_save() {
    local source_file="$1"
    local target_name="$2"
    local target_path="${BACKUP_DIR}/${target_name}"

    mv "${source_file}" "${target_path}"

    if [[ -f "${target_path}" ]]; then
        log_info "备份已保存到: ${target_path}"
        log_info "文件大小: $(du -h "${target_path}" | cut -f1)"
        return 0
    else
        log_error "保存备份失败: ${target_path}"
        return 1
    fi
}

# 列出可用备份
backend_list() {
    if [[ -d "${BACKUP_DIR}" ]]; then
        find "${BACKUP_DIR}" -name "${BACKUP_PREFIX}_*.sql*" -type f | sort -r
    fi
}

# 获取备份文件用于恢复
backend_get() {
    local backup_name="$1"
    local target_path="$2"
    local source_path="${BACKUP_DIR}/${backup_name}"

    if [[ -f "${source_path}" ]]; then
        cp "${source_path}" "${target_path}"
        return 0
    else
        log_error "备份文件不存在: ${source_path}"
        return 1
    fi
}

# 删除过期备份
backend_cleanup() {
    local retention_days="$1"
    local deleted_count=0

    if [[ -d "${BACKUP_DIR}" ]]; then
        while IFS= read -r -d '' file; do
            rm -f "${file}"
            log_info "已删除过期备份: ${file}"
            ((deleted_count++))
        done < <(find "${BACKUP_DIR}" -name "${BACKUP_PREFIX}_*.sql*" -type f -mtime +"${retention_days}" -print0)
    fi

    log_info "共删除 ${deleted_count} 个过期备份"
}

# 获取备份统计信息
backend_stats() {
    if [[ -d "${BACKUP_DIR}" ]]; then
        local count
        local total_size
        count=$(find "${BACKUP_DIR}" -name "${BACKUP_PREFIX}_*.sql*" -type f | wc -l)
        total_size=$(du -sh "${BACKUP_DIR}" 2>/dev/null | cut -f1)
        echo "备份数量: ${count}"
        echo "总占用空间: ${total_size}"
    else
        echo "备份目录不存在"
    fi
}
