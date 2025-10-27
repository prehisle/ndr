# AI Agent 上手指南

> 适用对象：在 NDR 仓库执行任务的 AI Agent。  
> 目标：在最短时间内获取上下文、遵循协作约定、避免重复劳动。

---

## 协作约定速览

- 默认使用简体中文撰写交流、文档与代码注释。
- 未经明确授权不得执行 `git commit`/`git push`；保持工作目录改动可追踪。
- 运行 Python/pytest 时优先使用虚拟环境：`.venv/bin/python`、`.venv/bin/pytest`。
- 完整约定详见项目根目录的 [AGENTS.md](../../AGENTS.md)，执行任务前请快速复核。

---

## 会话初始化建议

1. 阅读 [docs/README.md](../README.md) 了解文档分布，确认需要加载的上下文。
2. 先行查看《[状态看板](../状态看板.md)》与《[项目规划与方案](../项目规划与方案.md)》，掌握近期进展与长期计划。
3. 若涉及部署或排障，参考《[维护指南](../维护指南.md)》，其中第 13 章提供运维速查。
4. 需要了解测试结构或代码目录，可回看仓库根目录的 `readme.md` “目录速览”章节。

---

## 常用操作清单

- **依赖安装**：`.venv/bin/python -m pip install -r requirements.txt`
- **数据库迁移**：`alembic upgrade head`（必要时确认 PostgreSQL 已启用 `ltree`/`btree_gist`/`btree_gin`）
- **运行服务**：`uvicorn app.main:app --reload --port 9001`
- **运行测试**：`.venv/bin/pytest` 或 `.venv/bin/pytest -k <关键字>` 聚焦调试
- **导出 OpenAPI**：`.venv/bin/python scripts/export_openapi.py <输出目录>`
- 以上命令的背景说明与更多变种可在《维护指南》第 3、6、13 章找到。

---

## 交付前校验

- 代码变更是否符合 `app/api → app/app → app/domain → app/infra` 的分层约定。
- 是否已运行必要的单元/集成测试；如无法执行，请在回复中说明阻碍与验证建议。
- 新增依赖、环境变量、脚本是否在相关文档（`docs/README.md`、《维护指南》、compose 文件）中同步。
- 若改动影响文档或任务看板，请更新《状态看板》或在回复中提醒维护责任人。

---

## 常见引用

- 质量基线：`.github/workflows/`、`pre-commit` 钩子、`mypy.ini`
- 数据层：`alembic/versions`、`app/infra/db`、`scripts/benchmark_ltree.py`
- 服务层：`app/app/services`、`app/domain/repositories`
- API 层：`app/api/v1/routers`、`app/api/v1/schemas`

如发现信息缺失或过期，请在回复中记录，并酌情更新对应文档以维护单一事实来源。
