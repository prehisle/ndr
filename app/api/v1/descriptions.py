METADATA_FILTERS_DESCRIPTION = """
支持动态 `metadata.<field>[operator]=value` 查询参数，用于元数据筛选：

- 等值（默认）：`metadata.stage=draft`，重复参数按 OR 组合；
- IN：`metadata.stage[in]=draft,final`（也可重复参数）；
- 模糊：`metadata.title[like]=设计`，若未包含 `%` 自动按 `%值%` 处理；
- 范围：`metadata.price[gt]=10` / `[gte]` / `[lt]` / `[lte]`，值必须是数字；
- 数组包含：`metadata.tags[any]=alpha`（包含任一值）、`metadata.tags[all]=alpha&metadata.tags[all]=beta`（同时包含所有值）。

更多示例见 `docs/当前进度与待办.md` 的 “Metadata 过滤语法速查”。
""".strip()


SUBTREE_DOCUMENTS_DESCRIPTION = (
    METADATA_FILTERS_DESCRIPTION
    + "\n\n另外，可通过 `include_descendants` 控制仅当前节点或整棵子树。"
)
