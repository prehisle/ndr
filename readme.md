# 通用资料管理微服务（NDR）

本服务提供文档、节点以及两者关系的管理能力，基于 FastAPI + SQLAlchemy + PostgreSQL 搭建。

> 设计约束：NDR 不内置任何缓存组件，所有缓存与失效策略由调用方负责管理；服务本身仅聚焦节点、文档、节点-文档关系与文档版本的生命周期管理。

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
   - 安装 Git 钩子：`pre-commit install`
   - 准备数据库：确保本地 PostgreSQL 可用，创建数据库并在 `.env.development` 中设置 `DB_URL`。
   - 运行迁移与服务：
     ```bash
     alembic upgrade head
     uvicorn app.main:app --reload --port 9001
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
- `docs/`：核心文档（《[项目规划与方案](docs/%E9%A1%B9%E7%9B%AE%E8%A7%84%E5%88%92%E4%B8%8E%E6%96%B9%E6%A1%88.md)》《[当前进度与待办](docs/%E5%BD%93%E5%89%8D%E8%BF%9B%E5%BA%A6%E4%B8%8E%E5%BE%85%E5%8A%9E.md)》）
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

- 按照《[当前进度与待办](docs/%E5%BD%93%E5%89%8D%E8%BF%9B%E5%BA%A6%E4%B8%8E%E5%BE%85%E5%8A%9E.md)》中列出的事项，补齐节点移动的并发处理及基于 ltree 的子树查询与索引验证。
- 引入 CI 流水线与自动化脚本，巩固质量门槛。
- 拆分 `api → app → domain` 分层，逐步丰富领域/仓储层的单元与集成测试。
