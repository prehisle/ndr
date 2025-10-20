#!/usr/bin/env python3

"""Export the FastAPI OpenAPI schema into a target directory."""

import argparse
import json
import sys
from pathlib import Path


from app.main import create_app  # noqa: E402


def export_openapi(target_dir: Path) -> Path:
    """Generate openapi.json under target_dir and return the file path."""
    app = create_app()
    schema = app.openapi()

    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / "openapi.json"
    with output_path.open("w", encoding="utf-8") as fp:
        json.dump(schema, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export NDR service OpenAPI spec to a directory."
    )
    parser.add_argument(
        "target_dir",
        type=Path,
        help="Directory where openapi.json will be written (created if missing).",
    )
    args = parser.parse_args()

    output_path = export_openapi(args.target_dir.resolve())
    print(f"OpenAPI schema exported to {output_path}")


if __name__ == "__main__":
    main()
