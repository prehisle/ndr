"""
Domain layer package housing repository contracts and domain-specific helpers.
"""

from typing import Final

# 只有 output 类型的绑定关系计入 subtree_doc_count
COUNTED_RELATION_TYPE: Final[str] = "output"
