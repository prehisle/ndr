from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, inspect, text
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_admin_key
from app.infra.db.alembic_support import get_head_revision
from app.infra.db.models import IdempotencyRecord

router = APIRouter(dependencies=[Depends(require_admin_key)])


@router.post("/admin/idempotency/cleanup")
def cleanup_idempotency(
    db: Session = Depends(get_db), hours: int | None = Query(default=None, ge=0)
):
    now = datetime.now(timezone.utc)
    threshold = now if hours is None else now - timedelta(hours=hours)
    to_delete = db.query(IdempotencyRecord).filter(
        IdempotencyRecord.expires_at <= threshold
    )
    count = to_delete.count()
    if count:
        db.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= threshold)
        )
        db.commit()
    return {"deleted": int(count), "threshold": threshold.isoformat()}


@router.get("/admin/self-check")
def self_check(db: Session = Depends(get_db)) -> dict[str, Any]:
    """返回数据库、迁移、扩展与关键索引的自检信息。"""
    bind = db.get_bind()
    inspector = inspect(bind)

    # 基础数据库就绪
    database_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    # 迁移版本
    head = get_head_revision()
    try:
        current = db.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    except Exception:
        current = None
    alembic = {
        "head": head,
        "current": current,
        "up_to_date": (head == current) if head and current else False,
    }

    # ltree 扩展（PostgreSQL）
    dialect = bind.dialect.name
    extensions: list[dict[str, str]] = []
    ltree: dict[str, bool | str | None] = {"present": None}
    if dialect == "postgresql":
        rows = db.execute(
            text(
                "SELECT extname, extversion FROM pg_extension "
                "WHERE extname IN ('ltree','btree_gist','btree_gin','pg_trgm')"
            )
        ).all()
        extensions = [{"name": row[0], "version": row[1]} for row in rows]
        ltree = {
            "present": any(row[0] == "ltree" for row in rows),
            "version": next((row[1] for row in rows if row[0] == "ltree"), None),
        }

    # 关键索引存在性
    expected_indexes = {
        "nodes": {
            "ix_nodes_path_tree",
            "uq_nodes_path_active",
            "uq_nodes_parent_name_active",
            "ix_nodes_type",
            "ix_nodes_parent_position",
            "ix_nodes_parent_id",
        },
        "documents": {
            "ix_documents_metadata_gin",
            "ix_documents_type",
            "ix_documents_position",
            "ix_documents_type_position",
        },
        "node_documents": {"ix_node_documents_document_id"},
    }
    index_report: dict[str, Any] = {}
    for table, names in expected_indexes.items():
        try:
            idx = inspector.get_indexes(table)
            existing = {i.get("name") for i in idx}
            missing = sorted(list(names - existing))
            details = [
                {
                    "name": i.get("name"),
                    "columns": i.get("column_names") or [],
                    "unique": bool(i.get("unique")),
                    "dialect": i.get("dialect_options") or {},
                }
                for i in idx
            ]
            index_report[table] = {
                "present": sorted(list(existing & names)),
                "missing": missing,
                "details": details,
            }
        except Exception as exc:
            index_report[table] = {"error": str(exc)}

    # 主要表行数
    table_counts: dict[str, int] = {}
    try:
        tables = set(inspector.get_table_names())
        for t in (
            "nodes",
            "documents",
            "node_documents",
            "document_versions",
            "idempotency_records",
        ):
            if t in tables:
                cnt = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()
                table_counts[t] = int(cnt)
    except Exception:
        pass

    return {
        "database": {"ok": database_ok, "dialect": dialect},
        "alembic": alembic,
        "ltree": ltree,
        "extensions": extensions,
        "indexes": index_report,
        "tables": table_counts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_tables(inspector, candidates: Iterable[str] | None) -> list[str]:
    existing = set(inspector.get_table_names())
    if not candidates:
        return sorted(existing)
    chosen = [t for t in candidates if t in existing]
    return sorted(chosen)


@router.post("/admin/reindex")
def reindex_or_analyze(
    db: Session = Depends(get_db),
    tables: list[str] | None = Query(default=None),
    method: str = Query(default="analyze", pattern="^(analyze|reindex)$"),
    confirm: bool = Query(default=False),
) -> dict[str, Any]:
    """对指定表执行 ANALYZE 或 REINDEX（PostgreSQL）。

    - method=analyze（默认）：对目标表执行 ANALYZE，快速、低风险。
    - method=reindex：仅在 PostgreSQL 下可用，需 confirm=true 以避免误触。
    - tables 未指定时对全部现有表执行。
    """
    bind = db.get_bind()
    inspector = inspect(bind)
    target_tables = _normalize_tables(inspector, tables)
    if not target_tables:
        return {"executed": [], "method": method, "dialect": bind.dialect.name}

    executed: list[str] = []
    if method == "analyze":
        for t in target_tables:
            db.execute(text(f"ANALYZE {t}"))
            executed.append(t)
        db.commit()
        return {"executed": executed, "method": method, "dialect": bind.dialect.name}

    # reindex 分支
    if bind.dialect.name != "postgresql":
        return {
            "executed": [],
            "method": method,
            "dialect": bind.dialect.name,
            "error": "reindex is supported only on PostgreSQL",
        }
    if not confirm:
        return {
            "executed": [],
            "method": method,
            "dialect": bind.dialect.name,
            "error": "set confirm=true to proceed with REINDEX",
        }
    for t in target_tables:
        db.execute(text(f"REINDEX TABLE {t}"))
        executed.append(t)
    db.commit()
    return {"executed": executed, "method": method, "dialect": bind.dialect.name}
