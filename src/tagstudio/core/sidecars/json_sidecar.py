# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""JSON sidecar export support for DocumentStudio library entries."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm.exc import DetachedInstanceError

from tagstudio.core.constants import VERSION
from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.library.alchemy.models import Entry, Tag
from tagstudio.core.sidecars.paths import is_media_suffix, sidecar_path_for

SCHEMA_NAME = "documentstudio.sidecar.v2"


@dataclass(frozen=True)
class ExportOptions:
    """Options that control JSON sidecar export behavior."""

    write: bool = False
    overwrite: bool = False
    limit: int | None = None


@dataclass
class ExportSummary:
    """Quantitative receipt for a sidecar export pass."""

    entries_seen: int = 0
    media_skipped: int = 0
    source_missing: int = 0
    sidecars_existing: int = 0
    sidecars_would_write: int = 0
    sidecars_written: int = 0
    sidecars_skipped_existing: int = 0
    errors: int = 0


def serialize_datetime(value: Any) -> str | None:
    """Serialize supported date-like values without guessing missing information."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def tag_payload(tag: Tag) -> dict[str, Any]:
    """Return a stable, portable representation of a DocumentStudio tag.

    Tag identity is durable: parents are recorded by name, not by the local
    autoincrement database id, so the tag survives a database rebuild or a move
    to another library. The numeric id is deliberately omitted.
    """
    try:
        aliases = sorted(alias.name for alias in tag.aliases)
    except DetachedInstanceError:
        aliases = []

    try:
        parents = sorted(parent.name for parent in tag.parent_tags)
    except DetachedInstanceError:
        parents = []

    return {
        "name": tag.name,
        "shorthand": tag.shorthand,
        "parents": parents,
        "aliases": aliases,
        "is_category": tag.is_category,
        "is_hidden": tag.is_hidden,
    }


def entry_to_sidecar_payload(entry: Entry) -> dict[str, Any]:
    """Convert one loaded library entry into the primary JSON sidecar payload."""
    tags = sorted(entry.tags, key=lambda tag: (tag.name.lower(), tag.id))
    text_fields = sorted(entry.text_fields, key=lambda field: (field.name.lower(), field.id))
    datetime_fields = sorted(
        entry.datetime_fields, key=lambda field: (field.name.lower(), field.id)
    )
    return {
        "schema": SCHEMA_NAME,
        "generated": {
            "tool": "DocumentStudio",
            "tool_version": VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "source": {
            "entry_id": entry.id,
            "path": entry.path.as_posix(),
            "filename": entry.filename,
            "suffix": entry.suffix,
            "date_created": serialize_datetime(entry.date_created),
            "date_modified": serialize_datetime(entry.date_modified),
            "date_added": serialize_datetime(entry.date_added),
        },
        "keywords": sorted(
            {tag.name for tag in tags if tag.name and not tag.is_hidden},
            key=lambda value: value.lower(),
        ),
        "tags": [tag_payload(tag) for tag in tags],
        "fields": {
            "text": [
                {
                    "id": field.id,
                    "name": field.name,
                    "value": field.value,
                    "is_multiline": field.is_multiline,
                }
                for field in text_fields
            ],
            "datetime": [
                {
                    "id": field.id,
                    "name": field.name,
                    "value": field.value,
                }
                for field in datetime_fields
            ],
        },
    }


def write_json_sidecar(sidecar_path: Path, payload: dict[str, Any], overwrite: bool) -> bool:
    """Write one JSON sidecar atomically.

    Returns true when a file was written and false when an existing sidecar was preserved.
    """
    if sidecar_path.exists() and not overwrite:
        return False

    temp_path = sidecar_path.with_name(f"{sidecar_path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(sidecar_path)
    return True


def iter_entries_full(library: Library, batch_size: int = 200) -> Iterator[Entry]:
    """Yield fully-loaded entries in stable ID order."""
    entry_ids = sorted(entry.id for entry in library.all_entries())
    for index in range(0, len(entry_ids), batch_size):
        yield from library.get_entries_full(entry_ids[index : index + batch_size])


def export_json_sidecars(
    library: Library,
    options: ExportOptions,
    *,
    entry_ids: Iterable[int] | None = None,
) -> ExportSummary:
    """Dry-run or write JSON sidecars for loaded DocumentStudio entries."""
    summary = ExportSummary()
    if entry_ids is None:
        entries = iter_entries_full(library)
    else:
        entries = library.get_entries_full(list(entry_ids))

    for entry in entries:
        if options.limit is not None and summary.entries_seen >= options.limit:
            break

        summary.entries_seen += 1
        # digiKam boundary: catalog media, but never write a sidecar for it.
        if is_media_suffix(entry.suffix):
            summary.media_skipped += 1
            continue
        source_path = entry.path
        sidecar_path = sidecar_path_for(source_path)

        if not source_path.exists():
            summary.source_missing += 1

        if sidecar_path.exists():
            summary.sidecars_existing += 1
            if not options.overwrite:
                summary.sidecars_skipped_existing += 1
                continue

        if not options.write:
            summary.sidecars_would_write += 1
            continue

        try:
            payload = entry_to_sidecar_payload(entry)
            if write_json_sidecar(sidecar_path, payload, overwrite=options.overwrite):
                summary.sidecars_written += 1
            else:
                summary.sidecars_skipped_existing += 1
        except OSError:
            summary.errors += 1

    return summary
