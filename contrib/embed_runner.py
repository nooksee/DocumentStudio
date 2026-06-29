# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Production-safe runner for DocumentStudio embedded-metadata writes (.docx, .pdf).

Dry-run by default. With ``--apply`` it first copies every document it will
actually write into a reversible backup directory (the quarantine), THEN embeds
(each writer verifies the rewritten file reopens before swapping). Reversibility
is the backup directory: restore by copying the backups back over the sources.

    .venv/bin/python contrib/embed_runner.py /path/to/library            # dry-run
    .venv/bin/python contrib/embed_runner.py /path/to/library --apply    # write (backed up)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.sidecars.docx_metadata import (
    DocxEmbedOptions,
    embed_docx_metadata,
    entry_to_docx_core,
)
from tagstudio.core.sidecars.pdf_metadata import PdfEmbedOptions, embed_pdf_metadata
from tagstudio.core.sidecars.xmp_mapping import entry_to_xmp_properties

if TYPE_CHECKING:
    from tagstudio.core.library.alchemy.models import Entry


def _has_writable_metadata(entry: Entry) -> bool:
    suffix = entry.suffix.lower()
    if suffix == "docx":
        return bool(entry_to_docx_core(entry))
    if suffix == "pdf":
        return bool(entry_to_xmp_properties(entry))
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Production-safe .docx/.pdf embed runner (dry-run by default)."
    )
    parser.add_argument("library", type=Path, help="DocumentStudio library root")
    parser.add_argument("--apply", action="store_true", help="Write into sources (else dry-run)")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Reversible backup directory")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    library = Library()
    status = library.open_library(args.library)
    if not status.success:
        sys.stdout.write(json.dumps({"error": status.message or "could not open library"}) + "\n")
        return 2

    backup_dir: Path | None = None
    backed_up = 0
    if args.apply:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = args.backup_dir or (args.library / ".embed-backups" / stamp)
        backup_dir.mkdir(parents=True, exist_ok=True)
        # Back up every document that actually has metadata to write, before any write.
        ids = sorted(entry.id for entry in library.all_entries())
        for entry in library.get_entries_full(ids):
            if entry.path.exists() and _has_writable_metadata(entry):
                shutil.copy2(entry.path, backup_dir / entry.path.name)
                backed_up += 1

    docx = embed_docx_metadata(library, DocxEmbedOptions(apply=args.apply, limit=args.limit))
    pdf = embed_pdf_metadata(library, PdfEmbedOptions(apply=args.apply, limit=args.limit))

    receipt = {
        "mode": "apply" if args.apply else "dry-run",
        "backed_up": backed_up,
        "backup_dir": str(backup_dir) if backup_dir else None,
        "library": str(args.library),
        "docx": asdict(docx),
        "pdf": asdict(pdf),
    }
    sys.stdout.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0 if (docx.errors + pdf.errors) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
