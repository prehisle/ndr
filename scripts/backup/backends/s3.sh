#!/usr/bin/env bash
# S3 存储后端（预留实现）

# 检查 AWS CLI 是否可用
_check_aws_cli() {
    if ! command -v aws >/dev/null 2>&1; then
        log_error "AWS CLI 未安装，请先安装: pip install awscli"
        return 1
    fi
    return 0
}

# 构建 S3 URI
_build_s3_uri() {
    local filename="$1"
    echo "s3://${S3_BUCKET}/${S3_PREFIX}/${filename}"
}

# 保存备份到 S3
backend_save() {
    local source_file="$1"
    local target_name="$2"

    _check_aws_cli || return 1

    local s3_uri
    s3_uri=$(_build_s3_uri "${target_name}")

    local aws_opts=()
    if [[ -n "${S3_ENDPOINT}" ]]; then
        aws_opts+=(--endpoint-url "${S3_ENDPOINT}")
    fi

    if aws "${aws_opts[@]}" s3 cp "${source_file}" "${s3_uri}"; then
        log_info "备份已上传到: ${s3_uri}"
        rm -f "${source_file}"
        return 0
    else
        log_error "上传备份到 S3 失败"
        return 1
    fi
}

# 列出可用备份
backend_list() {
    _check_aws_cli || return 1

    local aws_opts=()
    if [[ -n "${S3_ENDPOINT}" ]]; then
        aws_opts+=(--endpoint-url "${S3_ENDPOINT}")
    fi

    aws "${aws_opts[@]}" s3 ls "s3://${S3_BUCKET}/${S3_PREFIX}/" | \
        grep "${BACKUP_PREFIX}_" | \
        awk '{print $4}' | \
        sort -r
}

# 获取备份文件用于恢复
backend_get() {
    local backup_name="$1"
    local target_path="$2"

    _check_aws_cli || return 1

    local s3_uri
    s3_uri=$(_build_s3_uri "${backup_name}")

    local aws_opts=()
    if [[ -n "${S3_ENDPOINT}" ]]; then
        aws_opts+=(--endpoint-url "${S3_ENDPOINT}")
    fi

    if aws "${aws_opts[@]}" s3 cp "${s3_uri}" "${target_path}"; then
        log_info "已从 S3 下载备份: ${backup_name}"
        return 0
    else
        log_error "从 S3 下载备份失败: ${backup_name}"
        return 1
    fi
}

# 删除过期备份
backend_cleanup() {
    local retention_days="$1"

    _check_aws_cli || return 1

    local aws_opts=()
    if [[ -n "${S3_ENDPOINT}" ]]; then
        aws_opts+=(--endpoint-url "${S3_ENDPOINT}")
    fi

    local cutoff_date
    cutoff_date=$(date -d "${retention_days} days ago" +%Y-%m-%d 2>/dev/null || date -v-${retention_days}d +%Y-%m-%d)

    log_info "清理 ${cutoff_date} 之前的备份..."

    # 列出并删除过期文件
    aws "${aws_opts[@]}" s3 ls "s3://${S3_BUCKET}/${S3_PREFIX}/" | while read -r line; do
        local file_date file_name
        file_date=$(echo "${line}" | awk '{print $1}')
        file_name=$(echo "${line}" | awk '{print $4}')

        if [[ "${file_date}" < "${cutoff_date}" ]] && [[ "${file_name}" == ${BACKUP_PREFIX}_* ]]; then
            aws "${aws_opts[@]}" s3 rm "s3://${S3_BUCKET}/${S3_PREFIX}/${file_name}"
            log_info "已删除过期备份: ${file_name}"
        fi
    done
}

# 获取备份统计信息
backend_stats() {
    _check_aws_cli || return 1

    local aws_opts=()
    if [[ -n "${S3_ENDPOINT}" ]]; then
        aws_opts+=(--endpoint-url "${S3_ENDPOINT}")
    fi

    local count
    count=$(aws "${aws_opts[@]}" s3 ls "s3://${S3_BUCKET}/${S3_PREFIX}/" | grep "${BACKUP_PREFIX}_" | wc -l)
    echo "S3 备份数量: ${count}"
    echo "存储桶: ${S3_BUCKET}"
    echo "前缀: ${S3_PREFIX}"
}
