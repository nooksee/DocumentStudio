# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the DocumentStudio XMP sidecar layer (mapping + ExifTool writer)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tagstudio.core.library.alchemy.fields import DatetimeField, TextField
from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.library.alchemy.models import Entry, Tag
from tagstudio.core.sidecars.xmp_mapping import (
    entry_to_xmp_properties,
    is_valid_rating,
)
from tagstudio.core.sidecars.xmp_sidecar import (
    XmpExportOptions,
    build_exiftool_args,
    exiftool_available,
    export_xmp_sidecars,
)
from tagstudio.core.utils.types import unwrap

needs_exiftool = pytest.mark.skipif(not exiftool_available(), reason="exiftool not installed")


def _open_library(path: Path) -> Library:
    lib = Library()
    status = lib.open_library(path, in_memory=True)
    assert status.success
    return lib


def _entry_with(lib: Library, *, source: Path, tags=(), text=(), dates=()) -> Entry:
    folder = unwrap(lib.folder)
    tag_ids: list[int] = []
    for index, name in enumerate(tags, start=100):
        assert lib.add_tag(Tag(id=index, name=name))
        tag_ids.append(index)

    fields: list = [TextField(name=n, value=v) for n, v in text]
    fields += [DatetimeField(name=n, value=v) for n, v in dates]
    assert lib.add_entries([Entry(id=1, folder=folder, path=source, fields=fields)])
    if tag_ids:
        assert lib.add_tags_to_entries(1, tag_ids)
    return unwrap(lib.get_entry_full(1))


# --- mapping (pure) ---------------------------------------------------------


def test_entry_maps_portable_fields(tmp_path: Path) -> None:
    lib = _open_library(tmp_path / "lib")
    entry = _entry_with(
        lib,
        source=tmp_path / "report.pdf",
        tags=["finance", "q3"],
        text=[
            ("Title", "Quarterly Report"),
            ("Description", "Q3 figures"),
            ("Author", "Kevin"),
            ("Rating", "4"),
            ("Notes", "stays JSON-only"),
        ],
    )
    props = entry_to_xmp_properties(entry)

    assert props["XMP-dc:Subject"] == ["finance", "q3"]
    assert props["XMP-dc:Title"] == ["Quarterly Report"]
    assert props["XMP-dc:Description"] == ["Q3 figures"]
    assert props["XMP-dc:Creator"] == ["Kevin"]
    assert props["XMP-xmp:Rating"] == ["4"]
    # An unmapped field (Notes) is not exported to XMP.
    assert all("Notes" not in prop for prop in props)


def test_author_and_artist_both_feed_creator(tmp_path: Path) -> None:
    lib = _open_library(tmp_path / "lib")
    entry = _entry_with(
        lib,
        source=tmp_path / "a.pdf",
        text=[("Author", "Kevin"), ("Artist", "Nathan")],
    )
    # dc:Creator is a list property, so both contributors survive (order by field name).
    assert sorted(entry_to_xmp_properties(entry)["XMP-dc:Creator"]) == ["Kevin", "Nathan"]


def test_invalid_rating_is_dropped(tmp_path: Path) -> None:
    lib = _open_library(tmp_path / "lib")
    entry = _entry_with(lib, source=tmp_path / "a.pdf", text=[("Rating", "great")])
    assert "XMP-xmp:Rating" not in entry_to_xmp_properties(entry)


def test_entry_with_no_portable_fields_is_empty(tmp_path: Path) -> None:
    lib = _open_library(tmp_path / "lib")
    entry = _entry_with(lib, source=tmp_path / "a.pdf", text=[("Notes", "x")])
    assert entry_to_xmp_properties(entry) == {}


def test_is_valid_rating() -> None:
    assert is_valid_rating("0") and is_valid_rating("5") and is_valid_rating("-1")
    assert not is_valid_rating("6") and not is_valid_rating("nope")


def test_build_exiftool_args_lists_and_singles() -> None:
    args = build_exiftool_args(
        {"XMP-dc:Subject": ["a", "b"], "XMP-dc:Title": ["T"], "XMP-xmp:Rating": ["3"]}
    )
    assert "-XMP-dc:Subject+=a" in args
    assert "-XMP-dc:Subject+=b" in args
    assert "-XMP-dc:Title=T" in args
    assert "-XMP-xmp:Rating=3" in args


# --- export (dry-run + ExifTool round-trip) ---------------------------------


def test_export_dry_run_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4 test\n")
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=source, tags=["finance"], text=[("Title", "R")])

    summary = export_xmp_sidecars(lib, XmpExportOptions())
    assert summary.entries_seen == 1
    assert summary.sidecars_would_write == 1
    assert summary.sidecars_written == 0
    assert not (tmp_path / "report.pdf.xmp").exists()


def test_export_skips_entries_without_portable_metadata(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4 test\n")
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=source, text=[("Notes", "not portable")])

    summary = export_xmp_sidecars(lib, XmpExportOptions(write=True))
    assert summary.sidecars_empty == 1
    assert summary.sidecars_written == 0


@needs_exiftool
def test_export_writes_readable_xmp(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4 test\n")
    lib = _open_library(tmp_path / "lib")
    _entry_with(
        lib,
        source=source,
        tags=["finance", "q3"],
        text=[
            ("Title", "Quarterly Report"),
            ("Description", "Q3 figures"),
            ("Author", "Kevin"),
            ("Rating", "4"),
        ],
    )

    summary = export_xmp_sidecars(lib, XmpExportOptions(write=True))
    assert summary.sidecars_written == 1
    assert summary.errors == 0

    sidecar = tmp_path / "report.pdf.xmp"
    assert sidecar.is_file()

    out = subprocess.run(
        [
            shutil.which("exiftool"),
            "-j",
            "-XMP-dc:Title",
            "-XMP-dc:Description",
            "-XMP-dc:Subject",
            "-XMP-dc:Creator",
            "-XMP-xmp:Rating",
            str(sidecar),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout)[0]
    assert data["Title"] == "Quarterly Report"
    assert data["Description"] == "Q3 figures"
    assert sorted(data["Subject"]) == ["finance", "q3"]
    assert data["Creator"] == "Kevin"
    assert str(data["Rating"]) == "4"


@needs_exiftool
def test_export_preserves_existing_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4 test\n")
    lib = _open_library(tmp_path / "lib")
    _entry_with(lib, source=source, tags=["finance"])

    assert export_xmp_sidecars(lib, XmpExportOptions(write=True)).sidecars_written == 1
    second = export_xmp_sidecars(lib, XmpExportOptions(write=True))
    assert second.sidecars_written == 0
    assert second.sidecars_skipped_existing == 1
