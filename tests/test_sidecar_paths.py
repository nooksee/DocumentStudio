# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from tagstudio.core.sidecars.paths import (
    is_managed_sidecar,
    sidecar_path_for,
    source_path_for,
)


def test_sidecar_path_preserves_source_name() -> None:
    assert sidecar_path_for(Path("/docs/report.pdf")) == Path("/docs/report.pdf.json")
    assert sidecar_path_for(Path("/docs/report.pdf"), ".xmp") == Path("/docs/report.pdf.xmp")


def test_sidecar_path_rejects_unknown_suffix() -> None:
    with pytest.raises(ValueError):
        sidecar_path_for(Path("/docs/report.pdf"), ".txt")


def test_source_path_is_inverse_of_sidecar_path() -> None:
    source = Path("/docs/report.pdf")
    assert source_path_for(sidecar_path_for(source)) == source
    assert source_path_for(sidecar_path_for(source, ".xmp")) == source


def test_managed_sidecar_requires_existing_source(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4 test\n")

    # Both sidecar flavors shadow an existing source, so both are managed.
    assert is_managed_sidecar(tmp_path / "report.pdf.json")
    assert is_managed_sidecar(tmp_path / "report.pdf.xmp")


def test_orphan_sidecar_without_source_is_not_managed(tmp_path: Path) -> None:
    # A .json/.xmp whose source file is absent is treated as ordinary payload.
    orphan = tmp_path / "orphan.pdf.json"
    orphan.write_text("{}", encoding="utf-8")

    assert is_managed_sidecar(orphan) is False


def test_standalone_json_is_not_a_sidecar(tmp_path: Path) -> None:
    # A real .json document with no matching source file must stay indexable.
    standalone = tmp_path / "data.json"
    standalone.write_text("{}", encoding="utf-8")

    assert is_managed_sidecar(standalone) is False


def test_non_sidecar_suffix_is_never_managed(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.4 test\n")

    assert is_managed_sidecar(source) is False
