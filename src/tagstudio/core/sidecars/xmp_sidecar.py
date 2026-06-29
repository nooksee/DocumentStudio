# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Write DocumentStudio XMP sidecars via ExifTool.

XMP is the portable interoperability export. We never modify the source bytes;
we write a standalone ``<source>.xmp`` sidecar that digiKam, Adobe apps, and
ExifTool can read. ExifTool is the engine, mirroring the proven picture lane.

Like the JSON exporter, this is dry-run by default, preserves existing sidecars
unless ``overwrite`` is explicit, and writes atomically via a temp file.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.sidecars.paths import is_media_suffix, sidecar_path_for
from tagstudio.core.sidecars.xmp_mapping import LIST_PROPERTIES, entry_to_xmp_properties

EXIFTOOL = shutil.which("exiftool")


@dataclass(frozen=True)
class XmpExportOptions:
    """Options that control XMP sidecar export behavior."""

    write: bool = False
    overwrite: bool = False
    limit: int | None = None
    # digiKam boundary switch: default off keeps media out of our writes.
    # Flip to True to let DocumentStudio write media sidecars too (the "all-media" path).
    include_media: bool = False


@dataclass
class XmpExportSummary:
    """Quantitative receipt for an XMP sidecar export pass."""

    entries_seen: int = 0
    media_skipped: int = 0
    source_missing: int = 0
    sidecars_existing: int = 0
    sidecars_would_write: int = 0
    sidecars_written: int = 0
    sidecars_skipped_existing: int = 0
    sidecars_empty: int = 0
    errors: int = 0


def exiftool_available() -> bool:
    """Return True when an ExifTool binary is on PATH."""
    return EXIFTOOL is not None


def build_exiftool_args(properties: dict[str, list[str]]) -> list[str]:
    """Build ExifTool tag-assignment args for a mapped property dict.

    List properties use ``-Tag+=value`` per value (rdf:Bag/Seq); single
    properties use ``-Tag=value`` with the last value.
    """
    args: list[str] = []
    for prop in sorted(properties):
        values = properties[prop]
        if not values:
            continue
        if prop in LIST_PROPERTIES:
            args.extend(f"-{prop}+={value}" for value in values)
        else:
            args.append(f"-{prop}={values[-1]}")
    return args


def build_exiftool_merge_args(properties: dict[str, list[str]]) -> list[str]:
    """Build args that update only our fields in an EXISTING sidecar.

    List properties are cleared then re-added so our values replace only ours;
    single properties are set. Foreign fields (digiKam's faces, GPS, hierarchy,
    labels) are never named, so they survive untouched.
    """
    args: list[str] = []
    for prop in sorted(properties):
        values = properties[prop]
        if not values:
            continue
        if prop in LIST_PROPERTIES:
            args.append(f"-{prop}=")
            args.extend(f"-{prop}+={value}" for value in values)
        else:
            args.append(f"-{prop}={values[-1]}")
    return args


def write_xmp_sidecar(
    sidecar_path: Path, properties: dict[str, list[str]], *, overwrite: bool
) -> bool:
    """Write one XMP sidecar via ExifTool.

    A new sidecar is created from scratch. An existing sidecar is preserved by
    default; with ``overwrite`` it is **merged** — only our fields change and
    every foreign field (e.g. digiKam's faces, GPS, hierarchical tags) is kept.
    """
    if not properties:
        return False
    if EXIFTOOL is None:
        raise RuntimeError("exiftool not found on PATH")

    if sidecar_path.exists():
        if not overwrite:
            return False
        result = subprocess.run(
            [
                EXIFTOOL,
                "-q",
                "-overwrite_original",
                *build_exiftool_merge_args(properties),
                str(sidecar_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "exiftool failed to merge sidecar")
        return True

    result = subprocess.run(
        [EXIFTOOL, "-q", "-o", str(sidecar_path), *build_exiftool_args(properties)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not sidecar_path.exists():
        raise RuntimeError(result.stderr.strip() or "exiftool failed to write sidecar")
    return True


def export_xmp_sidecars(
    library: Library,
    options: XmpExportOptions,
    *,
    entry_ids: Iterable[int] | None = None,
) -> XmpExportSummary:
    """Dry-run or write portable ``<source>.xmp`` sidecars for library entries."""
    summary = XmpExportSummary()

    if entry_ids is None:
        ids = sorted(entry.id for entry in library.all_entries())
    else:
        ids = list(entry_ids)

    for entry in library.get_entries_full(ids):
        if options.limit is not None and summary.entries_seen >= options.limit:
            break
        summary.entries_seen += 1
        # digiKam boundary: catalog media, but never write a sidecar for it
        # unless the operator explicitly opts in (the all-media switch).
        if not options.include_media and is_media_suffix(entry.suffix):
            summary.media_skipped += 1
            continue

        source_path = entry.path
        if not source_path.exists():
            summary.source_missing += 1

        properties = entry_to_xmp_properties(entry)
        if not properties:
            summary.sidecars_empty += 1
            continue

        sidecar_path = sidecar_path_for(source_path, ".xmp")
        if sidecar_path.exists():
            summary.sidecars_existing += 1
            if not options.overwrite:
                summary.sidecars_skipped_existing += 1
                continue

        if not options.write:
            summary.sidecars_would_write += 1
            continue

        try:
            if write_xmp_sidecar(sidecar_path, properties, overwrite=options.overwrite):
                summary.sidecars_written += 1
            else:
                summary.sidecars_skipped_existing += 1
        except (OSError, RuntimeError):
            summary.errors += 1

    return summary
