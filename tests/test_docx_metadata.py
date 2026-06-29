# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for dependency-free ``.docx`` embedded metadata read/write."""

import zipfile
from pathlib import Path

from tagstudio.core.library.alchemy.fields import TextField
from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.library.alchemy.models import Entry, Tag
from tagstudio.core.sidecars.docx_metadata import (
    DocxEmbedOptions,
    embed_docx_metadata,
    entry_to_docx_core,
    read_core_properties,
    write_docx_metadata,
)
from tagstudio.core.utils.types import unwrap

XML_DECL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

CONTENT_TYPES = (
    XML_DECL
    + b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="rels" '
    b'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    b'<Default Extension="xml" ContentType="application/xml"/>'
    b'<Override PartName="/word/document.xml" ContentType="'
    b'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    b'<Override PartName="/docProps/core.xml" ContentType="'
    b'application/vnd.openxmlformats-package.core-properties+xml"/>'
    b"</Types>"
)

RELS = (
    XML_DECL
    + b'<Relationships xmlns="'
    b'http://schemas.openxmlformats.org/package/2006/relationships">'
    b'<Relationship Id="rId1" Target="word/document.xml" Type="'
    b'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
    b'<Relationship Id="rId2" Target="docProps/core.xml" Type="'
    b'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"/>'
    b"</Relationships>"
)

DOCUMENT_XML = (
    XML_DECL
    + b'<w:document xmlns:w="'
    b'http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>"
)

DEFAULT_CORE = (
    XML_DECL
    + b"<cp:coreProperties"
    b' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
    b' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    b' xmlns:dcterms="http://purl.org/dc/terms/"'
    b' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    b"<dc:title>Original Title</dc:title>"
    b'<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
    b"</cp:coreProperties>"
)


def _make_docx(path: Path, core_xml: bytes = DEFAULT_CORE) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("word/document.xml", DOCUMENT_XML)
        archive.writestr("docProps/core.xml", core_xml)
    return path


def _open_library(path: Path) -> Library:
    lib = Library()
    status = lib.open_library(path, in_memory=True)
    assert status.success
    return lib


def _entry_with(lib: Library, *, source: Path, tags=(), text=()) -> Entry:
    folder = unwrap(lib.folder)
    tag_ids: list[int] = []
    for index, name in enumerate(tags, start=100):
        assert lib.add_tag(Tag(id=index, name=name))
        tag_ids.append(index)
    fields = [TextField(name=n, value=v) for n, v in text]
    assert lib.add_entries([Entry(id=1, folder=folder, path=source, fields=fields)])
    if tag_ids:
        assert lib.add_tags_to_entries(1, tag_ids)
    return unwrap(lib.get_entry_full(1))


# --- core.xml read/write (pure) ---------------------------------------------


def test_read_core_properties(tmp_path: Path) -> None:
    assert read_core_properties(_make_docx(tmp_path / "a.docx"))["title"] == "Original Title"


def test_write_sets_fields_and_preserves_existing(tmp_path: Path) -> None:
    docx = _make_docx(tmp_path / "a.docx")
    status = write_docx_metadata(
        docx, {"title": "New Title", "keywords": "finance, q3", "creator": "Kevin"}, apply=True
    )
    assert status == "written"

    props = read_core_properties(docx)
    assert props["title"] == "New Title"
    assert props["keywords"] == "finance, q3"
    assert props["creator"] == "Kevin"

    with zipfile.ZipFile(docx) as archive:
        assert archive.testzip() is None
        assert "word/document.xml" in archive.namelist()
        core = archive.read("docProps/core.xml").decode("utf-8")
    # An existing property we do not map (created) survives the edit.
    assert "created" in core


def test_dry_run_does_not_modify(tmp_path: Path) -> None:
    docx = _make_docx(tmp_path / "a.docx")
    before = docx.read_bytes()
    assert write_docx_metadata(docx, {"title": "X"}, apply=False) == "would-write"
    assert docx.read_bytes() == before


def test_missing_core_part_is_reported(tmp_path: Path) -> None:
    docx = tmp_path / "b.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", DOCUMENT_XML)
    assert write_docx_metadata(docx, {"title": "X"}, apply=True) == "no-core"


def test_empty_properties_is_reported(tmp_path: Path) -> None:
    assert write_docx_metadata(_make_docx(tmp_path / "a.docx"), {}, apply=True) == "empty"


# --- entry mapping + library embed ------------------------------------------


def test_entry_to_docx_core(tmp_path: Path) -> None:
    lib = _open_library(tmp_path / "lib")
    entry = _entry_with(
        lib,
        source=tmp_path / "a.docx",
        tags=["finance", "q3"],
        text=[("Title", "Report"), ("Author", "Kevin"), ("Description", "Q3 figures")],
    )
    core = entry_to_docx_core(entry)
    assert core["title"] == "Report"
    assert core["keywords"] == "finance, q3"
    assert core["creator"] == "Kevin"
    assert core["description"] == "Q3 figures"


def test_embed_writes_into_docx(tmp_path: Path) -> None:
    docx = _make_docx(tmp_path / "report.docx")
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=docx, tags=["finance"], text=[("Title", "Quarterly")])

    summary = embed_docx_metadata(lib, DocxEmbedOptions(apply=True))
    assert summary.docx_seen == 1
    assert summary.written == 1
    assert read_core_properties(docx)["title"] == "Quarterly"


def test_embed_dry_run_does_not_touch_source(tmp_path: Path) -> None:
    docx = _make_docx(tmp_path / "report.docx")
    before = docx.read_bytes()
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=docx, text=[("Title", "X")])

    summary = embed_docx_metadata(lib, DocxEmbedOptions(apply=False))
    assert summary.would_write == 1
    assert summary.written == 0
    assert docx.read_bytes() == before


def test_embed_skips_non_docx(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(b"%PDF-1.4 test\n")
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=source, text=[("Title", "X")])

    summary = embed_docx_metadata(lib, DocxEmbedOptions(apply=True))
    assert summary.docx_seen == 0
    assert summary.written == 0
