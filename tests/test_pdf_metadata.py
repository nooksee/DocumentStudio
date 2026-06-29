# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for PDF embedded metadata writing (ExifTool: XMP + Info dict)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tagstudio.core.library.alchemy.fields import TextField
from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.library.alchemy.models import Entry, Tag
from tagstudio.core.sidecars.pdf_metadata import (
    PdfEmbedOptions,
    embed_pdf_metadata,
    exiftool_available,
    write_pdf_metadata,
)
from tagstudio.core.utils.types import unwrap

needs_exiftool = pytest.mark.skipif(not exiftool_available(), reason="exiftool not installed")


def _make_pdf(path: Path) -> Path:
    """Write a strictly-valid minimal PDF (computed xref offsets) ExifTool will edit."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
    ]
    header = b"%PDF-1.4\n"
    body = b""
    offsets = []
    pos = len(header)
    for index, obj in enumerate(objs, 1):
        offsets.append(pos)
        chunk = b"%d 0 obj\n%s\nendobj\n" % (index, obj)
        body += chunk
        pos += len(chunk)
    xref_pos = len(header) + len(body)
    xref = b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        xref += b"%010d 00000 n \n" % off
    trailer = b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref_pos,
    )
    path.write_bytes(header + body + xref + trailer)
    return path


def _read(path: Path, *tags: str) -> dict:
    out = subprocess.run(
        [shutil.which("exiftool"), "-j", *tags, str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)[0]


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


def test_write_pdf_dry_run_does_not_modify(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf")
    before = pdf.read_bytes()
    status = write_pdf_metadata(pdf, {"XMP-dc:Title": ["X"]}, apply=False)
    assert status == "would-write"
    assert pdf.read_bytes() == before


def test_write_pdf_empty_is_reported(tmp_path: Path) -> None:
    assert write_pdf_metadata(_make_pdf(tmp_path / "a.pdf"), {}, apply=True) == "empty"


@needs_exiftool
def test_write_pdf_sets_info_and_xmp(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "report.pdf")
    props = {
        "XMP-dc:Title": ["Quarterly Report"],
        "XMP-dc:Creator": ["Kevin"],
        "XMP-dc:Description": ["Q3 figures"],
        "XMP-dc:Subject": ["finance", "q3"],
    }
    assert write_pdf_metadata(pdf, props, apply=True) == "written"

    # Info dict (what PDF viewers show in Properties).
    info = _read(pdf, "-FileType", "-Title", "-Author", "-Keywords")
    assert info["FileType"] == "PDF"  # still a readable PDF
    assert info["Title"] == "Quarterly Report"
    assert info["Author"] == "Kevin"
    keywords = info["Keywords"]
    keywords = keywords if isinstance(keywords, list) else [k.strip() for k in keywords.split(",")]
    assert sorted(keywords) == ["finance", "q3"]

    # XMP packet (modern interop) — read XMP tags only so dc:Subject is unambiguous.
    xmp = _read(pdf, "-XMP-dc:Title", "-XMP-dc:Subject", "-XMP-dc:Creator")
    assert xmp["Title"] == "Quarterly Report"
    subjects = xmp["Subject"] if isinstance(xmp["Subject"], list) else [xmp["Subject"]]
    assert sorted(subjects) == ["finance", "q3"]


@needs_exiftool
def test_embed_pdf_library(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "report.pdf")
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=pdf, tags=["finance"], text=[("Title", "Quarterly")])

    summary = embed_pdf_metadata(lib, PdfEmbedOptions(apply=True))
    assert summary.pdf_seen == 1
    assert summary.written == 1
    assert _read(pdf, "-Title")["Title"] == "Quarterly"


def test_embed_skips_non_pdf(tmp_path: Path) -> None:
    docx = tmp_path / "a.docx"
    docx.write_bytes(b"PK\x03\x04 fake")
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=docx, text=[("Title", "X")])

    summary = embed_pdf_metadata(lib, PdfEmbedOptions(apply=True))
    assert summary.pdf_seen == 0
    assert summary.written == 0
