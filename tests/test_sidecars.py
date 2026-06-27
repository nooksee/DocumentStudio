# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

from tagstudio.core.library.alchemy.library import Library
from tagstudio.core.sidecars.json_sidecar import (
    ExportOptions,
    entry_to_sidecar_payload,
    export_json_sidecars,
    sidecar_path_for,
    write_json_sidecar,
)
from tagstudio.core.utils.types import unwrap


def test_sidecar_path_preserves_source_suffix() -> None:
    assert sidecar_path_for(Path("/tmp/report.pdf")) == Path("/tmp/report.pdf.json")


def test_entry_payload_includes_tags_and_fields(library: Library) -> None:
    entry = unwrap(library.get_entry_full(1))
    payload = entry_to_sidecar_payload(entry)

    assert payload["schema"] == "documentstudio.sidecar.v2"
    assert payload["source"]["entry_id"] == 1
    assert payload["source"]["path"] == "foo.txt"
    assert "foo" in payload["keywords"]
    assert payload["fields"]["text"][0]["name"] == "Title"
    # Tag identity is durable: names, not numeric database ids.
    assert all("id" not in tag for tag in payload["tags"])
    assert all("parents" in tag for tag in payload["tags"])


def test_export_json_sidecars_dry_run_does_not_write(library: Library) -> None:
    summary = export_json_sidecars(library, ExportOptions(limit=1))

    assert summary.entries_seen == 1
    assert summary.sidecars_would_write == 1
    assert summary.sidecars_written == 0


def test_write_json_sidecar_preserves_existing_without_overwrite(tmp_path: Path) -> None:
    sidecar = tmp_path / "report.pdf.json"

    assert write_json_sidecar(sidecar, {"schema": "first"}, overwrite=False)
    assert not write_json_sidecar(sidecar, {"schema": "second"}, overwrite=False)

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["schema"] == "first"


def test_write_json_sidecar_replaces_existing_with_overwrite(tmp_path: Path) -> None:
    sidecar = tmp_path / "report.pdf.json"

    assert write_json_sidecar(sidecar, {"schema": "first"}, overwrite=False)
    assert write_json_sidecar(sidecar, {"schema": "second"}, overwrite=True)

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["schema"] == "second"
