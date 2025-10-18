#!/usr/bin/env python3
"""Benchmark ltree index strategies for subtree queries.

This script populates a synthetic hierarchy, applies either a GIST or
GIN (btree_gist) index, and measures subtree query latency as well as
query plans. Results are printed in a table for quick comparison.

Usage:
    python scripts/benchmark_ltree.py --index gist
    python scripts/benchmark_ltree.py --index gin

Requires `ltree` and `btree_gist` extensions in the target database.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Integer, Text, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, mapped_column

from app.common.config import get_settings
from app.infra.db.session import get_engine, reset_engine
from app.infra.db.types import LtreeType

Base = declarative_base()


@dataclass
class BenchmarkResult:
    index_type: str
    query_ms_p50: float
    query_ms_p95: float
    avg_plan_cost: float
    sample_rows_examined: float


class Node(Base):
    __tablename__ = "benchmark_nodes"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    name = mapped_column(Text, nullable=False)
    path = mapped_column(LtreeType(), nullable=False)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    session = Session(engine, autoflush=False, autocommit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_extensions(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS ltree"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gin"))
        conn.commit()


def rebuild_schema(engine: Engine) -> None:
    Base.metadata.drop_all(engine, tables=[Node.__table__])
    Base.metadata.create_all(engine, tables=[Node.__table__])


def seed_hierarchy(engine: Engine, breadth: int, depth: int) -> None:
    with session_scope(engine) as session:
        session.execute(text("TRUNCATE benchmark_nodes RESTART IDENTITY"))
        stack = [("root", "root", 1)]
        while stack:
            name, path, level = stack.pop()
            session.add(Node(name=name, path=path))
            if level >= depth:
                continue
            for i in range(1, breadth + 1):
                child_name = f"{name}-{i}"
                child_path = f"{path}.{i}"
                stack.append((child_name, child_path, level + 1))


def configure_index(engine: Engine, index_type: str) -> None:
    with engine.connect() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_benchmark_nodes_path"))
        if index_type == "gist":
            for clause in ("gist_ltree_ops", "ltree_ops", None):
                try:
                    if clause:
                        conn.execute(
                            text(
                                f"CREATE INDEX ix_benchmark_nodes_path "
                                f"ON benchmark_nodes USING GIST(path {clause})"
                            )
                        )
                    else:
                        conn.execute(text("CREATE INDEX ix_benchmark_nodes_path ON benchmark_nodes USING GIST(path)"))
                    break
                except Exception:  # pragma: no cover - fallback across PG versions
                    conn.rollback()
            else:
                raise RuntimeError("Failed to create GIST index for ltree. Check extension installation.")
        elif index_type == "gin":
            for clause in ("gin_ltree_ops", "ltree_ops", None):
                try:
                    if clause:
                        conn.execute(
                            text(
                                f"CREATE INDEX ix_benchmark_nodes_path "
                                f"ON benchmark_nodes USING GIN(path {clause})"
                            )
                        )
                    else:
                        conn.execute(text("CREATE INDEX ix_benchmark_nodes_path ON benchmark_nodes USING GIN(path)"))
                    break
                except Exception:  # pragma: no cover - fallback across PG versions
                    conn.rollback()
            else:
                raise RuntimeError(
                    "Failed to create GIN index for ltree. Ensure ltree/ltree_gin support is available."
                )
        else:
            raise ValueError(f"Unsupported index type: {index_type}")
        conn.commit()


def operator_class_available(engine: Engine, method: str) -> bool:
    query = text(
        """
        SELECT 1
        FROM pg_opclass opc
        JOIN pg_am am ON am.oid = opc.opcmethod
        WHERE am.amname = :method
          AND opc.opcintype = 'ltree'::regtype
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        return conn.execute(query, {"method": method}).scalar_one_or_none() is not None


def run_explain_analyze(engine: Engine, path: str) -> tuple[float, float]:
    query = text(
        "EXPLAIN (ANALYZE, FORMAT JSON) "
        "SELECT * FROM benchmark_nodes WHERE path <@ CAST(:subtree AS ltree)"
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"subtree": path}).scalar_one()
    plan = rows[0]["Plan"]
    cost = plan["Total Cost"]
    rows_examined = plan.get("Plan Rows", 0)
    return cost, rows_examined


def run_benchmark(engine: Engine, index_type: str, samples: int, breadth: int, depth: int) -> BenchmarkResult:
    ensure_extensions(engine)
    rebuild_schema(engine)

    if index_type == "gin" and not operator_class_available(engine, "gin"):
        raise RuntimeError(
            "GIN operator class for ltree is not available on this PostgreSQL build. "
            "Re-run with --index gist or install ltree GIN support."
        )

    seed_hierarchy(engine, breadth=breadth, depth=depth)
    configure_index(engine, index_type)

    with engine.connect() as conn:
        paths = [row[0] for row in conn.execute(text("SELECT path::text FROM benchmark_nodes WHERE nlevel(path) > 2"))]

    chosen = random.sample(paths, min(samples, len(paths)))
    timings: list[float] = []
    plan_costs: list[float] = []
    rows_examined_list: list[float] = []

    query = text("SELECT * FROM benchmark_nodes WHERE path <@ CAST(:subtree AS ltree)")

    with engine.connect() as conn:
        for path in chosen:
            start = time.perf_counter()
            conn.execute(query, {"subtree": path}).fetchall()
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)

            cost, rows_examined = run_explain_analyze(engine, path)
            plan_costs.append(cost)
            rows_examined_list.append(rows_examined)

    return BenchmarkResult(
        index_type=index_type,
        query_ms_p50=statistics.median(timings),
        query_ms_p95=statistics.quantiles(timings, n=20)[18] if len(timings) >= 20 else max(timings),
        avg_plan_cost=sum(plan_costs) / len(plan_costs),
        sample_rows_examined=sum(rows_examined_list) / len(rows_examined_list),
    )


def print_results(results: list[BenchmarkResult]) -> None:
    headers = ["Index", "P50 ms", "P95 ms", "Avg plan cost", "Rows examined"]
    rows = [
        [
            r.index_type.upper(),
            f"{r.query_ms_p50:.3f}",
            f"{r.query_ms_p95:.3f}",
            f"{r.avg_plan_cost:.2f}",
            f"{r.sample_rows_examined:.1f}",
        ]
        for r in results
    ]
    col_widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    print(header_line)
    print(separator)
    for row in rows:
        print(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark ltree subtree queries under different indexes.")
    parser.add_argument("--index", choices=["gist", "gin"], action="append", required=False)
    parser.add_argument("--samples", type=int, default=30, help="Number of subtree queries to sample.")
    parser.add_argument("--breadth", type=int, default=5, help="Number of children per node.")
    parser.add_argument("--depth", type=int, default=4, help="Depth of the generated tree.")
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database URL (default uses application configuration DB_URL).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.index:
        args.index = ["gist", "gin"]

    if args.db_url:
        settings = get_settings()
        settings.DB_URL = args.db_url  # type: ignore[attr-defined]
        get_settings.cache_clear()  # type: ignore[attr-defined]
        reset_engine()

    engine = get_engine()
    results = []
    for index in args.index:
        print(f"Running benchmark for index: {index.upper()}")
        try:
            result = run_benchmark(engine, index, args.samples, args.breadth, args.depth)
        except RuntimeError as exc:
            print(f"  Skipped {index.upper()}: {exc}")
            continue
        results.append(result)
    if results:
        print_results(results)
    else:
        print("No benchmark results were produced.")


if __name__ == "__main__":
    main()
