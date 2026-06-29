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
from tagstudio.core.sidecars.docx_metadata import DocxEmbedOptions, embed_docx_metadata
from tagstudio.core.sidecars.import_sidecar import ImportOptions, import_json_sidecars
from tagstudio.core.sidecars.json_sidecar import ExportOptions, export_json_sidecars
from tagstudio.core.sidecars.pdf_metadata import PdfEmbedOptions, embed_pdf_metadata
from tagstudio.core.sidecars.xmp_import import import_xmp_sidecars
from tagstudio.core.sidecars.xmp_sidecar import XmpExportOptions, export_xmp_sidecars


def parse_args() -> argparse.Namespace:
    """Parse sidecar maintenance arguments."""
    parser = argparse.ArgumentParser(
        description="Export or import DocumentStudio JSON/XMP sidecars."
    )
    parser.add_argument("library_dir", type=Path, help="DocumentStudio library root directory")
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="Import sidecars into the library instead of exporting them",
    )
    parser.add_argument(
        "--xmp",
        action="store_true",
        help="Export portable XMP sidecars (via ExifTool) instead of JSON",
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        help="Write metadata INTO source documents (.docx, .pdf); modifies sources",
    )
    parser.add_argument(
        "--include-media",
        action="store_true",
        help="Opt in to writing sidecars for media too (off by default; the digiKam boundary)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply changes (write sidecar files on export, mutate the library on import)",
    )
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

    if args.embed:
        docx = embed_docx_metadata(library, DocxEmbedOptions(apply=args.write, limit=args.limit))
        pdf = embed_pdf_metadata(library, PdfEmbedOptions(apply=args.write, limit=args.limit))
        embed_payload = {
            "direction": "embed",
            "mode": "write" if args.write else "dry-run",
            "library_dir": args.library_dir.as_posix(),
            "docx": asdict(docx),
            "pdf": asdict(pdf),
        }
        if args.json:
            sys.stdout.write(json.dumps(embed_payload, indent=2, sort_keys=True) + "\n")
        else:
            for key in sorted(embed_payload):
                sys.stdout.write(f"{key}: {embed_payload[key]}\n")
        return 0 if (docx.errors + pdf.errors) == 0 else 1

    if args.do_import and args.xmp:
        summary = import_xmp_sidecars(
            library,
            ImportOptions(apply=args.write, limit=args.limit),
        )
        direction = "import"
        sidecar_format = "xmp"
    elif args.do_import:
        summary = import_json_sidecars(
            library,
            ImportOptions(apply=args.write, limit=args.limit),
        )
        direction = "import"
        sidecar_format = "json"
    elif args.xmp:
        summary = export_xmp_sidecars(
            library,
            XmpExportOptions(
                write=args.write,
                overwrite=args.overwrite,
                limit=args.limit,
                include_media=args.include_media,
            ),
        )
        direction = "export"
        sidecar_format = "xmp"
    else:
        summary = export_json_sidecars(
            library,
            ExportOptions(
                write=args.write,
                overwrite=args.overwrite,
                limit=args.limit,
                include_media=args.include_media,
            ),
        )
        direction = "export"
        sidecar_format = "json"

    payload = asdict(summary)
    payload["direction"] = direction
    payload["format"] = sidecar_format
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
