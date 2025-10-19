# Document Version History & Diff Plan

## 背景与目标

- 当前 DMS 原先仅覆盖文档的最新状态 CRUD，缺乏历史追溯、差异比对与按版本恢复能力。
- 产品需求要求：
  - 自动保存版本历史，记录每次写入的内容快照与操作人。
  - 可按版本列出内容、查看差异，并将文档恢复到任一历史版本。
  - 方案需兼容现有 API/服务分层，保持事务语义与软删逻辑。

## 实施状态

- ✅ `documents.content` 字段与 `document_versions` 表已落地，所有写操作会在同一事务内持久化快照。
- ✅ 对外 API：`GET /documents/{id}/versions`、`GET /versions/{n}`、`GET /versions/{n}/diff`、`POST /versions/{n}/restore` 已上线，对应测试见 `tests/api/test_document_versions_api` 与 demo 用例。
- ✅ `DocumentVersionService` 负责快照生成、版本号递增、差异比对与恢复辅助逻辑；`DocumentService.restore_document_version` 在恢复前后自动记录保护快照。
- ⏳ 后续可按需扩展版本保留策略、diff 深度、以及带内容的压缩策略。

## 可行性分析

| 维度 | 现状 | 影响评估 |
| ---- | ---- | -------- |
| 架构 | 已实现 `api → app → domain → infra` 分层，文档操作集中在 `DocumentService` | 可在服务层统一挂钩版本写入，易于维护事务一致性。 |
| 数据库 | PostgreSQL + Alembic 已在线，`documents` 表使用 JSONB | 新增版本表 & GIN 索引可无缝集成；需设计清理策略防止表膨胀。 |
| API | `/api/v1/documents` 已暴露 CRUD/恢复接口 | 可扩展版本相关 REST 路由，沿用现有鉴权 & 审计约束。 |
| 依赖 | 现有依赖无 JSON diff 库 | 若需结构化 diff，可选择轻量三方（如 `jsondiff`）或自研递归比较。 |

结论：实现具备较高可行性，需新增数据模型与服务逻辑，但不会破坏现有架构。

## 设计原则

1. 版本记录应与文档写操作处于同一事务，确保状态与历史同步。
2. 保留完整快照，diff 在读取时按需计算，避免写时开销过大。
3. 对外 API 与现有风格保持一致，所有写操作继续要求 `X-User-Id`。
4. 支持软删文档的版本访问（默认仅展示未删文档，提供 `include_deleted` 参数）。
5. 兼顾性能与存储：提供按文档的版本保留上限或归档扩展点。

## 数据建模

新增表 `document_versions`（示例字段）：

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| `id` | bigint PK | 自增主键 |
| `document_id` | bigint FK → `documents.id` | 版本所属文档 |
| `version_number` | integer | 文档内部递增版本号（1 开始） |
| `snapshot_title` | text | 当次标题快照 |
| `snapshot_metadata` | JSONB | 元数据快照 |
| `snapshot_content` | JSONB/Text | 可选，存储文档主体内容（若引入 `content` 字段，建议 JSONB 以支持结构化内容） |
| `change_summary` | JSONB | 可选，存储轻量 diff 或业务标签 |
| `created_at` | timestamptz | 版本创建时间 |
| `created_by` | text | 触发写操作的用户 |

索引建议：
- `(document_id, version_number)` 唯一索引，便于按版本排序与恢复。
- `GIN` on `snapshot_metadata`（按需），支持基于元数据的历史检索。

迁移策略：
- Alembic 迁移创建新表与索引。
- 可选：为现存文档回填一条初始版本（使用当前状态）。

## 服务层改动

### DocumentService 扩展

- `create_document`：创建文档后写入版本 `version_number=1`。
- `update_document`：更新前先复制快照写入新版本；版本号按当前最大值 +1。
- `restore_document`：
  - 新增参数指定目标版本 ID/号。
  - 恢复前先将“当前最新状态”存入版本表（形成保护快照），再将目标版本内容回写到主表。
  - 恢复完成后额外写入一条记录，标记此次恢复操作与来源版本号。
- 引入 `DocumentVersionService` 或在 `DocumentService` 内聚合版本相关逻辑（推荐拆分服务 + 仓储保持整洁）。

### 仓储层

- 新增 `DocumentVersionRepository`，支持：
  - `list_versions(document_id, include_deleted=False, page?, size?)`
  - `get_version(document_id, version_number)`
  - `create_version(...)`
  - `get_latest_version_number(document_id)`

## API 设计草案

新增路由（均位于 `/api/v1/documents`）：

| 路径 | 方法 | 功能 | 备注 |
| ---- | ---- | ---- | ---- |
| `/{id}/versions` | GET | 分页列出文档版本 | 支持 `page`、`size`、`include_deleted_versions` |
| `/{id}/versions/{version_number}` | GET | 获取指定版本快照 | 默认仅文档存在时可访问，`include_deleted` 控制 |
| `/{id}/versions/{version_number}/diff` | GET | 比较该版本与当前版本或指定对比版本 | `against=` 查询参数 |
| `/{id}/versions/{version_number}/restore` | POST | 恢复文档至指定版本 | 回传恢复后的文档；记录恢复者 |

请求守卫：
- 所有写操作继续要求 `X-User-Id`。
- 若文档处于软删状态，恢复前需单独调用文档恢复或允许直接恢复（需在产品上确认）。

## Diff 策略建议

1. MVP：返回字段级别差异，格式示例：
   ```json
   {
     "title": {"from": "Spec v1", "to": "Spec v2"},
     "metadata": {
       "added": {"new_field": "value"},
       "removed": ["old_field"],
       "changed": {"stage": {"from": "draft", "to": "final"}}
     },
     "content": {
       "changed": {...},  # 文档主体内容的差异（结构化或字符串 diff）
       "added": {...},
       "removed": {...}
     }
   }
   ```
2. 实现方式：
   - 纯 Python 递归对比（避免额外依赖），保持受控输出。
   - 若后续需求升级，可引入专门的 diff 库，但需在依赖治理中评估。

## 测试策略

- 单元测试：`DocumentVersionRepository`、`DocumentVersionService`。
- 服务层集成：覆盖创建/更新自动留痕、恢复逻辑、软删文档的版本访问。
- API 测试：新增 demo 测试 & FastAPI 集成测试，验证路由、分页、鉴权必填。
- 回归测试：确保现有 CRUD & 幂等行为不受影响。
- 性能评估：在版本量较大场景下做分页性能验证（可在后续慢流水线补充）。

## 迭代拆分建议

1. **Iteration 1**：数据库迁移、仓储、服务层基础能力（记录版本 + 列表 + 获取）。
2. **Iteration 2**：REST API & Pydantic 模型、diff 工具、恢复流程。
3. **Iteration 3**：策略完善（版本保留策略、批量清理、性能优化）、指标与审计补充。

每个迭代结束前需更新文档和 demo 测试，便于使用者快速理解。

## 风险与缓解

| 风险 | 描述 | 缓解措施 |
| ---- | ---- | -------- |
| 表数据膨胀 | 高频更新导致版本表快速增大 | 设计保留策略（按数量/时间），提供后台清理脚本。 |
| 恢复覆盖线上修改 | 恢复操作可能覆盖最近写入 | 恢复 API 加幂等键 / 乐观锁（`If-Match`）或在响应中提示。 |
| Diff 复杂度 | JSON 结构深且多类型，diff 逻辑易出错 | MVP 保持简单结构，增加单测；复杂需求再引入专业库。 |
| 事务耗时增加 | 写操作新增版本插入 | 确保版本写入与文档写入共用会话，必要时增加索引优化。 |

## 下一步

1. 与产品确认 diff 细节、恢复策略（软删文档、冲突处理、展示需求）。
2. 起草 Alembic 迁移与数据模型代码骨架。
3. 设计 API schema（Pydantic 模型），同步至 OpenAPI 文档。
