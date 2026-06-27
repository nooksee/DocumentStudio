# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Round-trip proof: a library can be rebuilt from JSON sidecars alone.

This is the keystone test for the DocumentStudio sidecar doctrine. If it
passes, the SQLite library is genuinely replaceable local state rather than the
durable metadata authority.
"""

from pathlib import Path

from tagstudio.core.library.alchemy.fields import TextField
from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.library.alchemy.models import Entry, Tag
from tagstudio.core.library.ignore import Ignore
from tagstudio.core.library.refresh import RefreshTracker
from tagstudio.core.sidecars.import_sidecar import ImportOptions, import_json_sidecars
from tagstudio.core.sidecars.json_sidecar import ExportOptions, export_json_sidecars
from tagstudio.core.utils.types import unwrap


def _open_library(path: Path) -> Library:
    lib = Library()
    status = lib.open_library(path, in_memory=True)
    assert status.success
    return lib


def _applied_state(lib: Library, entry_id: int) -> tuple[list[str], list[tuple]]:
    """Return an entry's applied tag names and text fields for comparison."""
    entry = unwrap(lib.get_entry_full(entry_id))
    tag_names = sorted(tag.name for tag in entry.tags)
    text_fields = sorted((f.name, f.value, f.is_multiline) for f in entry.text_fields)
    return tag_names, text_fields


def test_library_round_trips_through_json_sidecars(tmp_path: Path) -> None:
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4 test\n")
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")

    # --- Build the source library with a hierarchical tag and fields. ---
    source = _open_library(tmp_path / "source")
    folder = unwrap(source.folder)

    subbar = Tag(id=1500, name="subbar", color_namespace="tagstudio-standard", color_slug="yellow")
    assert source.add_tag(subbar)
    bar = Tag(
        id=2000,
        name="bar",
        color_namespace="tagstudio-standard",
        color_slug="blue",
        parent_tags={subbar},
    )
    assert source.add_tag(bar)
    foo = Tag(id=2500, name="foo", color_namespace="tagstudio-standard", color_slug="red")
    assert source.add_tag(foo)

    entry_report = Entry(
        id=1,
        folder=folder,
        path=report,
        fields=[
            TextField(name="Title", value="Quarterly Report", is_multiline=False),
            TextField(name="Description", value="Q3 figures", is_multiline=True),
        ],
    )
    entry_notes = Entry(id=2, folder=folder, path=notes, fields=[])
    assert source.add_entries([entry_report, entry_notes])
    assert source.add_tags_to_entries(1, [foo.id])
    assert source.add_tags_to_entries(2, [bar.id])

    # --- Export sidecars next to the real source files. ---
    export_summary = export_json_sidecars(source, ExportOptions(write=True))
    assert export_summary.sidecars_written == 2
    assert (tmp_path / "report.pdf.json").is_file()
    assert (tmp_path / "notes.txt.json").is_file()

    # --- Rebuild a bare library that only knows the file paths. ---
    rebuilt = _open_library(tmp_path / "rebuilt")
    rebuilt_folder = unwrap(rebuilt.folder)
    assert rebuilt.add_entries(
        [
            Entry(id=1, folder=rebuilt_folder, path=report, fields=[]),
            Entry(id=2, folder=rebuilt_folder, path=notes, fields=[]),
        ]
    )

    import_summary = import_json_sidecars(rebuilt, ImportOptions(apply=True))
    assert import_summary.sidecars_found == 2
    assert import_summary.errors == 0

    # --- The rebuilt library matches the source for both entries. ---
    assert _applied_state(rebuilt, 1) == _applied_state(source, 1)
    assert _applied_state(rebuilt, 2) == _applied_state(source, 2)

    # --- The tag hierarchy survived: bar still descends from subbar. ---
    rebuilt_bar = unwrap(rebuilt.get_tag_by_name("bar"))
    assert sorted(parent.name for parent in rebuilt_bar.parent_tags) == ["subbar"]


def test_reimport_is_idempotent(tmp_path: Path) -> None:
    doc = tmp_path / "memo.pdf"
    doc.write_bytes(b"%PDF-1.4 test\n")

    source = _open_library(tmp_path / "source")
    folder = unwrap(source.folder)
    tag = Tag(id=3000, name="legal", color_namespace="tagstudio-standard", color_slug="red")
    assert source.add_tag(tag)
    assert source.add_entries(
        [Entry(id=1, folder=folder, path=doc, fields=[TextField(name="Title", value="Memo")])]
    )
    assert source.add_tags_to_entries(1, [tag.id])
    assert export_json_sidecars(source, ExportOptions(write=True)).sidecars_written == 1

    rebuilt = _open_library(tmp_path / "rebuilt")
    rebuilt_folder = unwrap(rebuilt.folder)
    assert rebuilt.add_entries([Entry(id=1, folder=rebuilt_folder, path=doc, fields=[])])

    first = import_json_sidecars(rebuilt, ImportOptions(apply=True))
    assert first.tags_created == 1
    assert first.tag_links_added == 1
    assert first.fields_added == 1

    # A second apply must not duplicate anything.
    second = import_json_sidecars(rebuilt, ImportOptions(apply=True))
    assert second.tags_created == 0
    assert second.tag_links_added == 0
    assert second.fields_added == 0


def test_import_dry_run_does_not_mutate(tmp_path: Path) -> None:
    doc = tmp_path / "memo.pdf"
    doc.write_bytes(b"%PDF-1.4 test\n")

    source = _open_library(tmp_path / "source")
    folder = unwrap(source.folder)
    tag = Tag(id=3000, name="legal", color_namespace="tagstudio-standard", color_slug="red")
    assert source.add_tag(tag)
    assert source.add_entries([Entry(id=1, folder=folder, path=doc, fields=[])])
    assert source.add_tags_to_entries(1, [tag.id])
    assert export_json_sidecars(source, ExportOptions(write=True)).sidecars_written == 1

    rebuilt = _open_library(tmp_path / "rebuilt")
    rebuilt_folder = unwrap(rebuilt.folder)
    assert rebuilt.add_entries([Entry(id=1, folder=rebuilt_folder, path=doc, fields=[])])
    tags_before = len(rebuilt.tags)

    summary = import_json_sidecars(rebuilt, ImportOptions(apply=False))
    assert summary.sidecars_found == 1
    assert summary.tags_created == 0
    assert summary.tag_links_added == 0
    assert len(rebuilt.tags) == tags_before
    assert _applied_state(rebuilt, 1) == ([], [])


def test_refresh_skips_managed_sidecars(tmp_path: Path) -> None:
    lib = Library()
    assert lib.open_library(tmp_path).success

    # Upstream ships a default .ts_ignore that blanket-ignores *.json/*.xmp.
    # A document library may hold real json/xmp documents, so allow them and
    # let the sibling-conditional sidecar predicate do the filtering instead.
    Ignore.write_ignore_file(tmp_path, ["# allow json/xmp documents\n"])

    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 test\n")
    (tmp_path / "report.pdf.json").write_text("{}", encoding="utf-8")  # sidecar -> skipped
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")  # standalone -> payload

    tracker = RefreshTracker(library=lib)
    # force_internal_tools keeps the test independent of a system ripgrep.
    list(tracker.refresh_dir(tmp_path, force_internal_tools=True))

    found = {path.name for path in tracker.files_not_in_library}
    assert "report.pdf" in found
    assert "data.json" in found
    assert "report.pdf.json" not in found


def test_default_template_catalogs_real_json_documents(tmp_path: Path) -> None:
    """The shipped default .ts_ignore must not blanket-ignore json/xmp documents.

    This locks in the DocumentStudio deviation from upstream: a standalone
    data.json is payload, while report.pdf.json is skipped as a sidecar.
    """
    lib = Library()
    assert lib.open_library(tmp_path).success  # seeds the default .ts_ignore template

    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 test\n")
    (tmp_path / "report.pdf.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    (tmp_path / "photo.HEIC.aae").write_text("aae", encoding="utf-8")  # still ignored

    tracker = RefreshTracker(library=lib)
    list(tracker.refresh_dir(tmp_path, force_internal_tools=True))

    found = {path.name for path in tracker.files_not_in_library}
    assert "data.json" in found
    assert "report.pdf.json" not in found
    assert "photo.HEIC.aae" not in found
