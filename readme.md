# 通用资料管理微服务（DMS）

本服务提供文档、节点以及两者关系的管理能力，基于 FastAPI + SQLAlchemy + PostgreSQL 搭建。

## 快速开始

1. **启动容器化环境**

   ```bash
   docker compose up --build
   ```

   - `postgres` 服务会自动启动 PostgreSQL 16 并持久化数据到 `pgdata` 卷。
   - `app` 服务会在启动时根据 `AUTO_APPLY_MIGRATIONS=true` 自动执行 Alembic 迁移，然后通过 Uvicorn 暴露接口。
   - 应用默认监听 http://localhost:8000，API 根路径为 `/api/v1`。

2. **本地开发（无需容器）**

   - 安装依赖：`pip install -r requirements.txt`
   - 准备数据库：确保本地 PostgreSQL 可用，创建数据库并在 `.env.development` 中设置 `DB_URL`。
   - 运行迁移与服务：
     ```bash
     alembic upgrade head
     uvicorn app.main:app --reload
     ```

## 运行测试

测试依赖真实的 PostgreSQL 实例。提供 `TEST_DB_URL`（或复用 `DB_URL`）后执行：

```bash
pytest
```

测试夹具会在会话开始时自动执行 `alembic upgrade head` 并在每个用例后清理表数据。

## 目录速览

- `app/`：应用主代码（API、配置、基础设施）
- `alembic/`：数据库迁移脚本
- `docs/`：技术方案、规划与当前状态文档
- `tests/`：API 集成测试与启动验证

## 后续工作指引

- 按照 `docs/03_当前状态.md` 中的建议，补齐节点移动的并发处理及基于 ltree 的子树查询与索引验证。
- 引入 `pre-commit` 与 CI 配置，巩固代码质量基线。
- 拆分 `api → app → domain` 分层，逐步丰富领域/仓储层的单元与集成测试。
