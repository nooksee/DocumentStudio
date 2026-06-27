# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Import/sync DocumentStudio JSON sidecars back into a library.

This is the round-trip counterpart to :mod:`tagstudio.core.sidecars.json_sidecar`.
It exists so the SQLite library can be treated as replaceable local state: wipe
it, re-scan the source files, then re-import the durable JSON sidecars to
restore the applied tags and fields. Source document bytes are never modified.

Tags are matched by durable identity (name plus immediate parent names), not by
the local autoincrement database id, so a sidecar written by one library can be
re-applied to a freshly rebuilt one.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tagstudio.core.library.alchemy.fields import DatetimeField, TextField
from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.library.alchemy.models import Entry, Tag
from tagstudio.core.sidecars.paths import sidecar_path_for


@dataclass(frozen=True)
class ImportOptions:
    """Options that control JSON sidecar import behavior."""

    apply: bool = False
    limit: int | None = None


@dataclass
class ImportSummary:
    """Quantitative receipt for a sidecar import pass."""

    entries_seen: int = 0
    sidecars_found: int = 0
    sidecars_missing: int = 0
    sidecars_invalid: int = 0
    tags_created: int = 0
    tag_links_added: int = 0
    fields_added: int = 0
    errors: int = 0


class _TagResolver:
    """Resolve durable tag identity (name + parent names) to library tag ids.

    The index is built once from the current library state and then updated in
    place as new tags are created, so a single import pass never creates the
    same logical tag twice.
    """

    def __init__(self, library: Library) -> None:
        self.library = library
        self._by_key: dict[tuple[str, frozenset[str]], int] = {}
        tag_ids = [tag.id for tag in library.tags]
        hierarchy = library.get_tag_hierarchy(tag_ids)
        for tag_id, tag in hierarchy.items():
            self._by_key[self._key(tag.name, (p.name for p in tag.parent_tags))] = tag_id

    @staticmethod
    def _key(name: str, parent_names: Iterable[str]) -> tuple[str, frozenset[str]]:
        return name, frozenset(p for p in parent_names if p)

    def resolve_or_create(
        self, spec: dict[str, Any], summary: ImportSummary, *, apply: bool
    ) -> int | None:
        """Return the tag id for a sidecar tag spec, creating it when applying."""
        name = spec.get("name")
        if not name:
            return None

        parent_names = sorted({p for p in spec.get("parents", []) if p})
        key = self._key(name, parent_names)
        if key in self._by_key:
            return self._by_key[key]

        if not apply:
            return None

        # Ensure parents exist first. Sidecars only carry immediate parent names,
        # so parents are resolved/created by name with no deeper hierarchy.
        parent_ids: list[int] = []
        for parent_name in parent_names:
            parent_id = self.resolve_or_create(
                {"name": parent_name, "parents": []}, summary, apply=apply
            )
            if parent_id is not None:
                parent_ids.append(parent_id)

        created = self.library.add_tag(
            Tag(
                name=name,
                shorthand=spec.get("shorthand"),
                is_category=bool(spec.get("is_category", False)),
                is_hidden=bool(spec.get("is_hidden", False)),
            )
        )
        if created is None:
            summary.errors += 1
            return None

        for parent_id in parent_ids:
            self.library.add_parent_tag(parent_id, created.id)
        for alias in spec.get("aliases", []):
            if alias:
                self.library.add_alias(alias, created.id)

        self._by_key[key] = created.id
        summary.tags_created += 1
        return created.id


def _apply_fields(
    library: Library, entry: Entry, payload: dict[str, Any], summary: ImportSummary, *, apply: bool
) -> None:
    fields = payload.get("fields", {})

    existing_text = {(f.name, f.value, f.is_multiline) for f in entry.text_fields}
    for spec in fields.get("text", []):
        name = spec.get("name", "")
        value = spec.get("value")
        is_multiline = bool(spec.get("is_multiline", False))
        if (name, value, is_multiline) in existing_text:
            continue
        if apply and not library.add_field_to_entries(
            entry.id, TextField(name=name, value=value, is_multiline=is_multiline)
        ):
            summary.errors += 1
            continue
        summary.fields_added += 1

    existing_dt = {(f.name, f.value) for f in entry.datetime_fields}
    for spec in fields.get("datetime", []):
        name = spec.get("name", "")
        value = spec.get("value")
        if (name, value) in existing_dt:
            continue
        if apply and not library.add_field_to_entries(
            entry.id, DatetimeField(name=name, value=value)
        ):
            summary.errors += 1
            continue
        summary.fields_added += 1


def apply_sidecar_payload(
    library: Library,
    entry: Entry,
    payload: dict[str, Any],
    summary: ImportSummary,
    resolver: _TagResolver,
    *,
    apply: bool,
) -> None:
    """Apply one parsed sidecar payload's tags and fields to a library entry."""
    tag_ids: list[int] = []
    for spec in payload.get("tags", []):
        tag_id = resolver.resolve_or_create(spec, summary, apply=apply)
        if tag_id is not None:
            tag_ids.append(tag_id)

    if apply and tag_ids:
        summary.tag_links_added += library.add_tags_to_entries(entry.id, tag_ids)

    _apply_fields(library, entry, payload, summary, apply=apply)


def import_json_sidecars(
    library: Library,
    options: ImportOptions,
    *,
    entry_ids: Iterable[int] | None = None,
) -> ImportSummary:
    """Dry-run or apply JSON sidecars found beside the library's source files."""
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

        sidecar = sidecar_path_for(entry.path)
        if not sidecar.is_file():
            summary.sidecars_missing += 1
            continue

        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary.sidecars_invalid += 1
            continue

        if not isinstance(payload, dict):
            summary.sidecars_invalid += 1
            continue

        summary.sidecars_found += 1
        apply_sidecar_payload(library, entry, payload, summary, resolver, apply=options.apply)

    return summary
