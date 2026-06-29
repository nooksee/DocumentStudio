# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Write embedded metadata into PDF documents via ExifTool.

PDF is the one document type ExifTool writes natively (safe incremental update).
We write both the XMP packet (modern interop, reusing the canonical XMP mapping)
and the PDF Info dictionary (Title/Author/Subject/Keywords — what most viewers
show in Properties), so the metadata is visible *and* portable.

Writes the source, so it is dry-run by default and only replaces the source with
a temp copy that has been verified to reopen as a readable PDF.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tagstudio.core.sidecars.xmp_mapping import entry_to_xmp_properties
from tagstudio.core.sidecars.xmp_sidecar import EXIFTOOL, build_exiftool_merge_args

if TYPE_CHECKING:
    from tagstudio.core.library.alchemy.library import Library


def exiftool_available() -> bool:
    """Return True when an ExifTool binary is on PATH."""
    return EXIFTOOL is not None


def pdf_info_args(xmp_properties: dict[str, list[str]]) -> list[str]:
    """Derive PDF Info-dictionary args from the canonical XMP properties.

    The Info dict is what most PDF viewers display in Properties, so we mirror
    the portable fields there in addition to the XMP packet.
    """
    args: list[str] = []
    title = xmp_properties.get("XMP-dc:Title")
    description = xmp_properties.get("XMP-dc:Description")
    creators = xmp_properties.get("XMP-dc:Creator")
    keywords = xmp_properties.get("XMP-dc:Subject")
    # Qualify to the PDF group so an unqualified tag can't bleed into XMP.
    if title:
        args.append(f"-PDF:Title={title[-1]}")
    if description:
        args.append(f"-PDF:Subject={description[-1]}")
    if creators:
        args.append(f"-PDF:Author={'; '.join(creators)}")
    if keywords:
        args.append(f"-PDF:Keywords={', '.join(keywords)}")
    return args


def write_pdf_metadata(source: Path, xmp_properties: dict[str, list[str]], *, apply: bool) -> str:
    """Write XMP + Info metadata into a PDF.

    Returns ``empty``, ``would-write``, or ``written``. On apply the write happens
    on a temp copy that is verified to reopen as a readable PDF before it replaces
    the source, so a failed write never corrupts the source.
    """
    if not xmp_properties:
        return "empty"
    if EXIFTOOL is None:
        raise RuntimeError("exiftool not found on PATH")
    if not apply:
        return "would-write"

    temp_path = source.with_name(f"{source.name}.tmp")
    shutil.copy2(source, temp_path)
    args = [*build_exiftool_merge_args(xmp_properties), *pdf_info_args(xmp_properties)]
    result = subprocess.run(
        [EXIFTOOL, "-q", "-overwrite_original", *args, str(temp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "exiftool failed to write pdf")

    # Verify the rewritten file is still a readable PDF before swapping.
    verify = subprocess.run(
        [EXIFTOOL, "-q", "-s3", "-FileType", str(temp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if verify.returncode != 0 or verify.stdout.strip() != "PDF":
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("rewritten pdf failed its readability check")

    temp_path.replace(source)
    return "written"


@dataclass(frozen=True)
class PdfEmbedOptions:
    """Options for embedding metadata into PDF sources."""

    apply: bool = False
    limit: int | None = None


@dataclass
class PdfEmbedSummary:
    """Quantitative receipt for a PDF embed pass."""

    entries_seen: int = 0
    pdf_seen: int = 0
    source_missing: int = 0
    empty: int = 0
    would_write: int = 0
    written: int = 0
    errors: int = 0


def embed_pdf_metadata(
    library: Library,
    options: PdfEmbedOptions,
    *,
    entry_ids: Iterable[int] | None = None,
) -> PdfEmbedSummary:
    """Dry-run or write embedded metadata into the library's PDF sources."""
    summary = PdfEmbedSummary()

    if entry_ids is None:
        ids = sorted(entry.id for entry in library.all_entries())
    else:
        ids = list(entry_ids)

    for entry in library.get_entries_full(ids):
        if options.limit is not None and summary.entries_seen >= options.limit:
            break
        summary.entries_seen += 1

        source = entry.path
        if source.suffix.lower() != ".pdf":
            continue
        summary.pdf_seen += 1
        if not source.exists():
            summary.source_missing += 1
            continue

        properties = entry_to_xmp_properties(entry)
        if not properties:
            summary.empty += 1
            continue

        try:
            status = write_pdf_metadata(source, properties, apply=options.apply)
        except (OSError, RuntimeError):
            summary.errors += 1
            continue

        if status == "would-write":
            summary.would_write += 1
        elif status == "written":
            summary.written += 1

    return summary
