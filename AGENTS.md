# Codex 协作约定

1. 总是使用简体中文，包含与用户交互、撰写文档与代码注释等场景。
2. 仅在用户明确要求时执行代码提交或推送操作。
3. 运行 Python 脚本或 pytest 时，优先使用仓库内的 `.venv` 虚拟环境（例如 `.venv/bin/python`、`.venv/bin/pytest`）。

# Repository Guidelines

## 项目结构与模块组织
核心代码位于 `app/`，按分层拆分为：`api/` 负责 FastAPI 路由，`app/` 组织依赖与配置，`domain/` 封装业务规则，`infra/` 处理持久化与外部网关。数据库迁移脚本存放在 `alembic/`。`tests/` 目录与运行层级一一对应，例如 `tests/api/`、`tests/services/`。规划资料集中在 `docs/`，辅助脚本位于 `scripts/`，涵盖 OpenAPI 导出与性能基准测试工具。

## 构建、测试与开发命令
- `docker compose up --build` 启动 PostgreSQL 与应用服务，并自动执行迁移。
- `pip install -r requirements.txt` 安装本地开发所需依赖。
- `alembic upgrade head` 将数据库更新到最新版本，推荐在本地测试前运行。
- `uvicorn app.main:app --reload --port 9001` 在热重载模式下启动 API。
- `pytest` 使用 `TEST_DB_URL` 执行完整测试套件。

## 代码风格与命名约定
Python 代码遵循 PEP 8，统一使用四空格缩进和有意义的 snake_case 函数名。FastAPI 路由应位于 `app/api`，并保持版本化路径（如 `/api/v1/...`）。启用 `pre-commit` 可在提交前自动运行 `ruff`、`black`、`isort` 与 `mypy`（示例：`pre-commit run --all-files`）。在领域层与基础设施层优先补充类型标注，确保 mypy 校验通过。

## 测试准则
Pytest 夹具依赖真实 PostgreSQL，可设置 `TEST_DB_URL` 或复用 `DB_URL`。集成测试会自动通过 Alembic 重建 schema，无需手动清理。测试文件命名建议为 `test_<feature>`，并与对应模块保持同级目录。使用 `pytest -k 关键字` 聚焦调试，将新增用例优先放在服务层，必要时再扩展至 API 冒烟测试。

## 提交与合并请求规范
最新提交兼有惯用前缀（如 `feat(nodes): ...`、`fix(db): ...`）与简洁中文摘要。首行控制在 80 字符内，并标注受影响的模块；若涉及复杂迁移，可追加段落解释背景。提交合并请求时请关联任务单，说明数据库或配置改动，必要时附上 API 文档截图，并确认 `pytest` 与 `pre-commit` 均已通过。

## 安全与配置提示
密钥与访问令牌请放在各环境 `.env` 文件中，勿入库。`TRACE_HTTP=true` 仅用于本地调试，避免在共享环境泄露请求负载。配置 `DESTRUCTIVE_API_KEY` 后，调用方必须携带 `X-Admin-Key` 才能访问清理型端点。新增环境变量时更新 `docs/` 以及示例 compose 配置，确保运维同步。

## 代理协作约定
与仓库内协作者沟通、撰写文档与代码注释时统一使用简体中文。若需执行 Python 脚本或运行 pytest，请使用 `.venv` 虚拟环境中的解释器（示例：`.venv/bin/python scripts/...`、`.venv/bin/pytest`）。提交或推送代码前务必获得用户的明确指示，保持版本历史受控。
