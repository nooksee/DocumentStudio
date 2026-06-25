# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Command-line entry point for DocumentStudio sidecar maintenance."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.sidecars.json_sidecar import ExportOptions, export_json_sidecars


def parse_args() -> argparse.Namespace:
    """Parse sidecar maintenance arguments."""
    parser = argparse.ArgumentParser(description="Export DocumentStudio JSON sidecars.")
    parser.add_argument("library_dir", type=Path, help="DocumentStudio library root directory")
    parser.add_argument("--write", action="store_true", help="Write sidecar files")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing sidecars")
    parser.add_argument("--limit", type=int, default=None, help="Maximum entries to inspect")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary instead of plain text",
    )
    return parser.parse_args()


def main() -> int:
    """Run the sidecar exporter."""
    args = parse_args()
    library = Library()
    status = library.open_library(args.library_dir)
    if not status.success:
        sys.stderr.write(f"error: {status.message or 'could not open library'}\n")
        return 2

    summary = export_json_sidecars(
        library,
        ExportOptions(write=args.write, overwrite=args.overwrite, limit=args.limit),
    )
    payload = asdict(summary)
    payload["mode"] = "write" if args.write else "dry-run"
    payload["library_dir"] = args.library_dir.as_posix()

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        for key in sorted(payload):
            sys.stdout.write(f"{key}: {payload[key]}\n")
    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
