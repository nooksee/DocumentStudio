# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Canonical DocumentStudio field <-> XMP property mapping.

XMP is the *interoperability* sidecar: it carries the portable subset of a
document's metadata so other tools (digiKam, Adobe apps, ExifTool) can read it.
The rich, authoritative representation stays in the JSON sidecar.

DocumentStudio's library model is hierarchical tags plus named text/datetime
fields. This module is the single source of truth for how those map onto
standard XMP properties:

| DocumentStudio        | XMP property            | Cardinality |
|-----------------------|-------------------------|-------------|
| tags (visible)        | XMP-dc:Subject          | bag (list)  |
| Title                 | XMP-dc:Title            | single      |
| Description           | XMP-dc:Description      | single      |
| Author, Artist        | XMP-dc:Creator          | seq (list)  |
| Source                | XMP-dc:Source           | single      |
| Publisher             | XMP-dc:Publisher        | single      |
| URL                   | XMP-dc:Identifier       | single      |
| Rating                | XMP-xmp:Rating          | single      |
| Date, Date Created    | XMP-xmp:CreateDate      | single      |
| Date Modified         | XMP-xmp:ModifyDate      | single      |

Anything without a mapping here stays JSON-only by design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tagstudio.core.library.alchemy.models import Entry

# XMP property that holds keyword tags.
TAG_PROPERTY = "XMP-dc:Subject"

# DocumentStudio text-field name (lowercased) -> XMP property.
TEXT_FIELD_MAP: dict[str, str] = {
    "title": "XMP-dc:Title",
    "description": "XMP-dc:Description",
    "author": "XMP-dc:Creator",
    "artist": "XMP-dc:Creator",
    "source": "XMP-dc:Source",
    "publisher": "XMP-dc:Publisher",
    "url": "XMP-dc:Identifier",
    "rating": "XMP-xmp:Rating",
}

# DocumentStudio datetime-field name (lowercased) -> XMP property.
DATETIME_FIELD_MAP: dict[str, str] = {
    "date created": "XMP-xmp:CreateDate",
    "date": "XMP-xmp:CreateDate",
    "date modified": "XMP-xmp:ModifyDate",
}

# Properties that hold an ordered/unordered list of values (rdf:Seq / rdf:Bag).
LIST_PROPERTIES: frozenset[str] = frozenset({"XMP-dc:Subject", "XMP-dc:Creator"})

RATING_PROPERTY = "XMP-xmp:Rating"


def is_valid_rating(value: str) -> bool:
    """Return True when `value` is an XMP-legal rating (-1 to 5)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return -1.0 <= number <= 5.0


def entry_to_xmp_properties(entry: Entry) -> dict[str, list[str]]:
    """Map one library entry to its portable XMP properties.

    Returns a stable mapping of `XMP property -> [values]`. List properties keep
    every value; single properties collapse to the last contributor in a
    deterministic order. Empty/invalid values are dropped. An entry with nothing
    portable returns an empty dict (no XMP sidecar should be written for it).
    """
    properties: dict[str, list[str]] = {}

    keywords = sorted(
        {tag.name for tag in entry.tags if tag.name and not tag.is_hidden},
        key=str.lower,
    )
    if keywords:
        properties[TAG_PROPERTY] = keywords

    text_fields = sorted(entry.text_fields, key=lambda field: (field.name.lower(), field.id))
    for field in text_fields:
        value = (field.value or "").strip()
        if not value:
            continue
        prop = TEXT_FIELD_MAP.get(field.name.strip().lower())
        if prop is None:
            continue
        if prop == RATING_PROPERTY and not is_valid_rating(value):
            continue
        properties.setdefault(prop, []).append(value)

    datetime_fields = sorted(
        entry.datetime_fields, key=lambda field: (field.name.lower(), field.id)
    )
    for field in datetime_fields:
        value = (field.value or "").strip()
        if not value:
            continue
        prop = DATETIME_FIELD_MAP.get(field.name.strip().lower())
        if prop is None:
            continue
        properties.setdefault(prop, []).append(value)

    # Single-value properties keep only the last deterministic contributor.
    for prop, values in list(properties.items()):
        if prop not in LIST_PROPERTIES and len(values) > 1:
            properties[prop] = [values[-1]]

    return properties
