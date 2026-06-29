# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Import portable XMP sidecars back into a DocumentStudio library.

The reciprocal of :mod:`tagstudio.core.sidecars.xmp_sidecar` export, and the
digiKam "re-read metadata from file" parity. Each ``<source>.xmp`` is read with
ExifTool, its portable properties are mapped back to tags and fields, and they
are applied through the same engine the JSON importer uses. Source bytes and the
XMP sidecar are never modified.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.sidecars.import_sidecar import (
    ImportOptions,
    ImportSummary,
    _TagResolver,
    apply_sidecar_payload,
)
from tagstudio.core.sidecars.paths import sidecar_path_for
from tagstudio.core.sidecars.xmp_mapping import XMP_READ_ARGS, xmp_json_to_payload

EXIFTOOL = shutil.which("exiftool")

__all__ = ["ImportOptions", "ImportSummary", "import_xmp_sidecars", "read_xmp_payload"]


def read_xmp_payload(sidecar_path: Path) -> dict[str, Any] | None:
    """Read one XMP sidecar via ExifTool into a JSON-sidecar-style payload.

    Returns None when ExifTool is unavailable or the sidecar cannot be parsed.
    """
    if EXIFTOOL is None:
        return None
    result = subprocess.run(
        [EXIFTOOL, "-q", "-j", *XMP_READ_ARGS, str(sidecar_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not rows:
        return None
    return xmp_json_to_payload(rows[0])


def import_xmp_sidecars(
    library: Library,
    options: ImportOptions,
    *,
    entry_ids: Iterable[int] | None = None,
) -> ImportSummary:
    """Dry-run or apply ``<source>.xmp`` sidecars found beside library files."""
    summary = ImportSummary()
    resolver = _TagResolver(library)

    if entry_ids is None:
        ids = sorted(entry.id for entry in library.all_entries())
    else:
        ids = list(entry_ids)

    # Materialize entries before mutating so the read session is closed first.
    entries = list(library.get_entries_full(ids))
    for entry in entries:
        if options.limit is not None and summary.entries_seen >= options.limit:
            break
        summary.entries_seen += 1

        sidecar = sidecar_path_for(entry.path, ".xmp")
        if not sidecar.is_file():
            summary.sidecars_missing += 1
            continue

        payload = read_xmp_payload(sidecar)
        if payload is None:
            summary.sidecars_invalid += 1
            continue

        summary.sidecars_found += 1
        apply_sidecar_payload(library, entry, payload, summary, resolver, apply=options.apply)

    return summary
