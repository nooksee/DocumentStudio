# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Read and write embedded metadata in ``.docx`` documents, dependency-free.

ExifTool writes embedded metadata only for PDF among documents. But a ``.docx``
is an Open Packaging Conventions ZIP whose document properties live in a small
``docProps/core.xml`` part (Dublin Core + the OOXML core-properties namespace).
We can edit that part with nothing but the standard library, so DocumentStudio
gets native ``.docx`` metadata read/write with no new dependency.

This writes the source document, so it is dry-run by default and only ever
replaces the source with a temp package that has been verified to reopen.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tagstudio.core.library.alchemy.library import Library
    from tagstudio.core.library.alchemy.models import Entry

CORE_PART = "docProps/core.xml"

_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC = "http://purl.org/dc/elements/1.1/"
_DCTERMS = "http://purl.org/dc/terms/"
_DCMITYPE = "http://purl.org/dc/dcmitype/"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"

for _prefix, _uri in (
    ("cp", _CP),
    ("dc", _DC),
    ("dcterms", _DCTERMS),
    ("dcmitype", _DCMITYPE),
    ("xsi", _XSI),
):
    ET.register_namespace(_prefix, _uri)

# DocumentStudio core field -> fully-qualified core.xml element name.
CORE_FIELDS: dict[str, str] = {
    "title": f"{{{_DC}}}title",
    "creator": f"{{{_DC}}}creator",
    "subject": f"{{{_DC}}}subject",
    "description": f"{{{_DC}}}description",
    "keywords": f"{{{_CP}}}keywords",
}


def read_core_properties(docx_path: Path) -> dict[str, str]:
    """Return the populated core properties already inside a ``.docx``."""
    with zipfile.ZipFile(docx_path) as archive:
        if CORE_PART not in archive.namelist():
            return {}
        root = ET.fromstring(archive.read(CORE_PART))

    result: dict[str, str] = {}
    for field, qname in CORE_FIELDS.items():
        element = root.find(qname)
        if element is not None and element.text:
            result[field] = element.text
    return result


def apply_to_core_xml(existing: bytes, properties: dict[str, str]) -> bytes:
    """Return updated ``core.xml`` bytes, preserving any properties we do not map."""
    root = ET.fromstring(existing)
    for field, value in properties.items():
        qname = CORE_FIELDS[field]
        element = root.find(qname)
        if value:
            if element is None:
                element = ET.SubElement(root, qname)
            element.text = value
        elif element is not None:
            root.remove(element)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def entry_to_docx_core(entry: Entry) -> dict[str, str]:
    """Map one library entry to ``.docx`` core properties (free-text subset)."""
    properties: dict[str, str] = {}

    keywords = sorted(
        {tag.name for tag in entry.tags if tag.name and not tag.is_hidden},
        key=str.lower,
    )
    if keywords:
        properties["keywords"] = ", ".join(keywords)

    creators: list[str] = []
    for field in sorted(entry.text_fields, key=lambda item: (item.name.lower(), item.id)):
        value = (field.value or "").strip()
        if not value:
            continue
        name = field.name.strip().lower()
        if name == "title":
            properties["title"] = value
        elif name == "description":
            properties["description"] = value
        elif name in ("author", "artist"):
            creators.append(value)
    if creators:
        properties["creator"] = "; ".join(creators)

    return properties


def write_docx_metadata(source: Path, properties: dict[str, str], *, apply: bool) -> str:
    """Write core properties into a ``.docx``.

    Returns one of ``no-core``, ``empty``, ``would-write``, or ``written``.
    On apply, the new package is written to a temp file and verified to reopen
    before it replaces the source, so a failed write never corrupts the source.
    """
    if not properties:
        return "empty"

    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if CORE_PART not in names:
            return "no-core"
        new_core = apply_to_core_xml(archive.read(CORE_PART), properties)
        if not apply:
            return "would-write"
        parts = [(name, new_core if name == CORE_PART else archive.read(name)) for name in names]

    temp_path = source.with_name(f"{source.name}.tmp")
    with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in parts:
            out.writestr(name, data)

    # Verify the rewritten package reopens and its core.xml parses before swapping.
    with zipfile.ZipFile(temp_path) as check:
        if check.testzip() is not None:
            temp_path.unlink()
            raise OSError("rewritten docx failed its integrity check")
        ET.fromstring(check.read(CORE_PART))

    temp_path.replace(source)
    return "written"


@dataclass(frozen=True)
class DocxEmbedOptions:
    """Options for embedding metadata into ``.docx`` sources."""

    apply: bool = False
    limit: int | None = None


@dataclass
class DocxEmbedSummary:
    """Quantitative receipt for a ``.docx`` embed pass."""

    entries_seen: int = 0
    docx_seen: int = 0
    source_missing: int = 0
    no_core: int = 0
    empty: int = 0
    would_write: int = 0
    written: int = 0
    errors: int = 0


def embed_docx_metadata(
    library: Library,
    options: DocxEmbedOptions,
    *,
    entry_ids: Iterable[int] | None = None,
) -> DocxEmbedSummary:
    """Dry-run or write core properties into the library's ``.docx`` sources."""
    summary = DocxEmbedSummary()

    if entry_ids is None:
        ids = sorted(entry.id for entry in library.all_entries())
    else:
        ids = list(entry_ids)

    for entry in library.get_entries_full(ids):
        if options.limit is not None and summary.entries_seen >= options.limit:
            break
        summary.entries_seen += 1

        source = entry.path
        if source.suffix.lower() != ".docx":
            continue
        summary.docx_seen += 1
        if not source.exists():
            summary.source_missing += 1
            continue

        try:
            status = write_docx_metadata(source, entry_to_docx_core(entry), apply=options.apply)
        except (OSError, ET.ParseError, zipfile.BadZipFile):
            summary.errors += 1
            continue

        if status == "no-core":
            summary.no_core += 1
        elif status == "empty":
            summary.empty += 1
        elif status == "would-write":
            summary.would_write += 1
        elif status == "written":
            summary.written += 1

    return summary
