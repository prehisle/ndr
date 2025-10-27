# 生产环境部署指南

本文档说明如何使用一键部署脚本，将本项目部署到生产服务器 `192.168.1.31`。所有步骤均在开发机执行，通过免密 SSH 完成镜像传输和服务更新。

## 前置条件
- 开发机已安装 Docker 与 docker compose 插件（或 `docker-compose`）。  
- 已配置对 `dy_prod@192.168.1.31` 的 SSH 免密访问。  
- 仓库根目录存在 `.venv` 虚拟环境（可选，用于运行校验脚本）。

## 目录结构
```text
deploy/production/
├─ docker-compose.yml    # 生产编排模板
├─ .env.example          # 环境变量模板
└─ README.md             # 当前文档
```

生产服务器目标目录默认为 `~/ndr9000/`，脚本会创建以下内容：
```text
~/ndr9000/
├─ docker-compose.yml    # 最新生产配置
├─ .env                  # 生产环境变量（请勿提交到仓库）
├─ data/                 # 持久化数据（数据库等）
└─ runtime/              # 临时文件（镜像归档）
```

## 配置环境变量
1. 在仓库内复制模板：
   ```bash
   cp deploy/production/.env.example deploy/production/.env
   ```
2. 根据实际情况修改以下字段：  
   - `POSTGRES_PASSWORD`：必须改为强密码；  
   - 请同步将 `DB_URL` 中的密码替换为与 `POSTGRES_PASSWORD` 相同的值，避免应用连库失败；  
   - 如需开放 API Key、跨域等功能，在此文件中填写对应值；  
   - 若数据库运行在独立主机，请同步调整 `DB_URL`。
3. `.env` 会被 `.gitignore` 自动忽略，请勿提交到版本库。

## 运行部署脚本
1. 确保脚本可执行：
   ```bash
   chmod +x scripts/deploy_prod.sh
   ```
2. 在仓库根目录执行：
   ```bash
   scripts/deploy_prod.sh
   ```
3. 部署步骤包括：  
   - 本地构建镜像 `ndr:prod`；  
   - `docker save` 导出并通过 `scp` 传输到服务器；  
   - 同步最新 `docker-compose.yml` 与 `.env`；  
   - 服务器端加载镜像并使用 `docker compose up -d --force-recreate --remove-orphans` 更新服务。

## 自定义参数
脚本支持以下环境变量，执行前可按需覆盖：
- `REMOTE_HOST`（默认 `192.168.1.31`）
- `REMOTE_USER`（默认 `dy_prod`）
- `REMOTE_DIR`（默认 `/home/<REMOTE_USER>/ndr9000`）
- `LOCAL_IMAGE`（默认 `ndr:prod`）
- `IMAGE_ARCHIVE`（默认 `ndr_prod.tar`）
- `COMPOSE_SOURCE`（默认 `deploy/production/docker-compose.yml`）
- `ENV_SOURCE`（默认 `deploy/production/.env`）

示例（部署到测试机）：
```bash
REMOTE_HOST=192.168.1.50 REMOTE_DIR=/srv/ndr scripts/deploy_prod.sh
```

## 多实例部署
若需在同一台服务器上部署多套 NDR，可按实例拆分目录与端口：
- 为每个实例准备独立的 `.env` 文件，并设置唯一的 `COMPOSE_PROJECT_NAME`，确保数据卷和网络互不干扰；
- 修改 `APP_PORT`、`POSTGRES_HOST_PORT`（以及外部依赖端口）避免端口冲突；
- 运行脚本时覆盖 `REMOTE_DIR` 指向不同目录，例如 `REMOTE_DIR=~/ndr9001`；
- 如需分配不同镜像标签，可覆盖 `LOCAL_IMAGE` 并在 `.env` 内同步调整 `APP_IMAGE`。

## 注意事项
- 首次部署前务必填写 `.env` 并确认数据库密码安全。  
- 如需回滚，可使用 Git 标签重新构建旧版本镜像再运行脚本。  
- 如果服务器上既没有 `docker compose` 也没有 `docker-compose`，脚本会终止并提示安装依赖。  
- 生产环境出现故障时，可通过 `ssh` 登录服务器执行 `docker compose logs`、`docker compose ps` 调试。
