#!/usr/bin/env bash
# NAS 存储后端（预留实现）

# 检查 NAS 挂载点
_check_nas_mount() {
    if [[ -z "${NAS_MOUNT_POINT}" ]]; then
        log_error "NAS_MOUNT_POINT 未配置"
        return 1
    fi

    if ! mountpoint -q "${NAS_MOUNT_POINT}" 2>/dev/null; then
        log_error "NAS 未挂载: ${NAS_MOUNT_POINT}"
        return 1
    fi

    return 0
}

# 获取 NAS 备份目录
_get_nas_backup_dir() {
    echo "${NAS_MOUNT_POINT}/${NAS_BACKUP_PATH}"
}

# 保存备份到 NAS
backend_save() {
    local source_file="$1"
    local target_name="$2"

    _check_nas_mount || return 1

    local nas_dir target_path
    nas_dir=$(_get_nas_backup_dir)
    target_path="${nas_dir}/${target_name}"

    mkdir -p "${nas_dir}"

    if cp "${source_file}" "${target_path}"; then
        log_info "备份已保存到 NAS: ${target_path}"
        rm -f "${source_file}"
        return 0
    else
        log_error "保存备份到 NAS 失败"
        return 1
    fi
}

# 列出可用备份
backend_list() {
    _check_nas_mount || return 1

    local nas_dir
    nas_dir=$(_get_nas_backup_dir)

    if [[ -d "${nas_dir}" ]]; then
        find "${nas_dir}" -name "${BACKUP_PREFIX}_*.sql*" -type f | sort -r
    fi
}

# 获取备份文件用于恢复
backend_get() {
    local backup_name="$1"
    local target_path="$2"

    _check_nas_mount || return 1

    local nas_dir source_path
    nas_dir=$(_get_nas_backup_dir)
    source_path="${nas_dir}/${backup_name}"

    if [[ -f "${source_path}" ]]; then
        cp "${source_path}" "${target_path}"
        return 0
    else
        log_error "NAS 上备份文件不存在: ${source_path}"
        return 1
    fi
}

# 删除过期备份
backend_cleanup() {
    local retention_days="$1"

    _check_nas_mount || return 1

    local nas_dir deleted_count=0
    nas_dir=$(_get_nas_backup_dir)

    if [[ -d "${nas_dir}" ]]; then
        while IFS= read -r -d '' file; do
            rm -f "${file}"
            log_info "已删除 NAS 上的过期备份: ${file}"
            ((deleted_count++))
        done < <(find "${nas_dir}" -name "${BACKUP_PREFIX}_*.sql*" -type f -mtime +"${retention_days}" -print0)
    fi

    log_info "共删除 ${deleted_count} 个过期备份"
}

# 获取备份统计信息
backend_stats() {
    _check_nas_mount || return 1

    local nas_dir
    nas_dir=$(_get_nas_backup_dir)

    if [[ -d "${nas_dir}" ]]; then
        local count total_size
        count=$(find "${nas_dir}" -name "${BACKUP_PREFIX}_*.sql*" -type f | wc -l)
        total_size=$(du -sh "${nas_dir}" 2>/dev/null | cut -f1)
        echo "NAS 备份数量: ${count}"
        echo "总占用空间: ${total_size}"
        echo "挂载点: ${NAS_MOUNT_POINT}"
    else
        echo "NAS 备份目录不存在"
    fi
}
