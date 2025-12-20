# 通用资料管理微服务（NDR）

本服务提供文档、节点以及两者关系的管理能力，基于 FastAPI + SQLAlchemy + PostgreSQL 搭建。

> 设计约束：NDR 不内置任何缓存组件，所有缓存与失效策略由调用方负责管理；服务本身仅聚焦节点、文档、节点-文档关系与文档版本的生命周期管理。

- 节点模型提供 `parent_id` 与 `position` 字段：新增节点默认追加到父节点末尾，可通过 `POST /api/v1/nodes/reorder` 批量调整同级排序，响应会返回重排后的节点列表，便于实现目录拖拽。
- 文档排序改为专用端点：`POST /api/v1/documents/reorder` 支持批量调整顺序且不会生成新的版本记录，`ordered_ids` 支持按需局部置顶，可选通过 `type` 仅重排某一类文档。
- 节点 slug 约束：仅允许小写字母、数字与下划线（`[a-z0-9_]`），长度 1..255，且禁止包含 `.`，以确保与 PostgreSQL ltree 类型兼容。
- 高危操作独立密钥：设置 `DESTRUCTIVE_API_KEY` 后，调用方需携带 `X-Admin-Key` 才能访问 `/api/v1/documents/{id}/purge` 与 `/api/v1/nodes/{id}/purge`，用于在软删后彻底清除数据及关联。
- 调试场景可设置 `TRACE_HTTP=true` 输出请求/响应体（默认截断 2048 字符），部署环境请保持关闭以避免泄露。

## 快速开始

1. **启动容器化环境**

   ```bash
   docker compose up --build
   ```

   - `postgres` 服务会自动启动 PostgreSQL 16 并持久化数据到 `pgdata` 卷。
   - `app` 服务会在启动时根据 `AUTO_APPLY_MIGRATIONS=true` 自动执行 Alembic 迁移，然后通过 Uvicorn 暴露接口。
   - 应用默认监听 http://localhost:9001（可通过 `APP_PORT` 调整），API 根路径为 `/api/v1`。

2. **本地开发（无需容器）**

   - 安装依赖：`pip install -r requirements.txt`
   - 安装 Git 钩子：`pre-commit install`
   - 准备数据库：确保本地 PostgreSQL 可用，创建数据库并在 `.env.development` 中设置 `DB_URL`。
   - 运行迁移与服务：
     ```bash
     alembic upgrade head
     uvicorn app.main:app --reload --port 9001
     TRACE_HTTP=true && uvicorn app.main:app --reload --host 0.0.0.0 --port 9001
     ```
3. **导出openapi.json文档**
   - `python scripts/export_openapi.py /home/yjxt/codes/ydms/docs/backend`

## 运行测试

测试依赖真实的 PostgreSQL 实例。提供 `TEST_DB_URL`（或复用 `DB_URL`）后执行：

```bash
pytest
```

测试夹具会在会话开始时自动执行 `alembic upgrade head` 并在每个用例后清理表数据。

## 发布镜像到 GHCR

仓库提供 `.github/workflows/publish.yml`，当向 `master` 分支推送或创建 `v*` 标签时，会自动构建容器镜像并推送至 `ghcr.io/<owner>/ndr-service`。流程默认使用 `GITHUB_TOKEN` 写入 GHCR，无需额外手动触发，只需确保仓库与组织允许 Packages 写权限。

如需手动发布，可在 GitHub 生成具备 `write:packages` 权限的 Personal Access Token，并执行：

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u <GitHub 用户名> --password-stdin
docker build -t ghcr.io/<owner>/ndr-service:latest .
docker push ghcr.io/<owner>/ndr-service:latest
```

若需要保留多个版本，可额外推送 `:vX.Y.Z` 等标签。

### 使用发布镜像

镜像地址（示例）：`ghcr.io/prehisle/ndr-service:latest`。在运行前需确保外部 PostgreSQL 已准备好并可通过环境变量 `DB_URL` 访问。

**使用 Docker CLI：**

```bash
docker pull ghcr.io/prehisle/ndr-service:latest
docker run --rm -p 9001:8000 \
  -e DB_URL="postgresql+psycopg2://user:password@db-host:5432/ndr" \
  ghcr.io/prehisle/ndr-service:latest
```

镜像默认监听 `8000` 端口，可根据需要映射到其它端口；如需启用自动迁移、API Key 等功能，可继续传入对应环境变量。

**在 docker-compose.yml 中引用：**

```yaml
services:
  app:
    image: ghcr.io/prehisle/ndr-service:latest
    environment:
      DB_URL: postgresql+psycopg2://user:password@postgres:5432/ndr
      AUTO_APPLY_MIGRATIONS: "true"
    ports:
      - "${APP_PORT:-9001}:8000"
    depends_on:
      - postgres
```

如需锁定版本，可将 `latest` 替换为具体 Tag（例如 `v4.1.0`）。默认镜像内置 `uvicorn app.main:app --host 0.0.0.0 --port 8000` 的启动命令，无需额外覆盖。

## 目录速览

- `app/`：应用主代码（API、配置、基础设施）
- `alembic/`：数据库迁移脚本
- `docs/`：核心文档（参见《[文档索引](docs/README.md)》，涵盖《[项目规划与方案](docs/%E9%A1%B9%E7%9B%AE%E8%A7%84%E5%88%92%E4%B8%8E%E6%96%B9%E6%A1%88.md)》《[状态看板](docs/%E7%8A%B6%E6%80%81%E7%9C%8B%E6%9D%BF.md)》等）
- `tests/api/`：API 集成与协议一致性测试
- `tests/app/`：应用启动、观测性等集成测试
- `tests/db/`：数据库与仓储相关验证
- `tests/security/`：安全开关、鉴权行为测试
- `tests/services/`：应用/领域服务单元测试
- `tests/demo/`：最小示例（便于本地验收或教学）

## 代码规范

项目使用 `pre-commit` 管理 ruff、black、isort、mypy 等校验。首次克隆后执行：

```bash
pip install pre-commit
pre-commit install          # 安装 git hook，可选
pre-commit run --all-files
```

## 性能与基准

仓库提供 `scripts/benchmark_ltree.py` 用于对 GIST/GIN 索引下的子树查询进行基准测试（若 GIN 运算符类不可用会自动跳过）：

```bash
.venv/bin/python scripts/benchmark_ltree.py --index gist --index gin --samples 30 --breadth 5 --depth 4
```

> 运行前请确保目标 PostgreSQL 实例已启用 `ltree`、`btree_gist` 与 `btree_gin` 扩展，并在环境变量 `DB_URL` 中指向该实例。部分版本可能缺少 ltree 的 GIN 支持，脚本会提示改用 GIST 并自动跳过 GIN。

常用参数说明：
- `--index gist` / `--index gin` 控制基准的索引类型，可重复指定（缺省会比较两者）。
- `--samples` 控制随机选取的子树查询次数。
- 如果 GIN 运算符类缺失，脚本会输出 skip 信息但继续执行其他指标。

## 后续工作指引

- 按照《[状态看板](docs/%E7%8A%B6%E6%80%81%E7%9C%8B%E6%9D%BF.md)》中的事项，补齐节点移动的并发处理及基于 ltree 的子树查询与索引验证。
- 引入 CI 流水线与自动化脚本，巩固质量门槛。
- 拆分 `api → app → domain` 分层，逐步丰富领域/仓储层的单元与集成测试。
### CI 与质量门禁

- 预提交（ruff/black/isort/mypy）在 CI 中全量执行；
- 单元与集成测试覆盖率阈值：85%（`pytest --cov`）；
- 依赖安全扫描：`pip-audit` 与 `safety`，报告作为构件上传；
- mypy 使用 `mypy.ini` 基础配置，后续将逐步提升严格度（分模块推进）。
