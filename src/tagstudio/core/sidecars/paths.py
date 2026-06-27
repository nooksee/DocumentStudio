# SPDX-FileCopyrightText: (c) TagStudio Contributors
# SPDX-License-Identifier: GPL-3.0-only

"""Path helpers for DocumentStudio sidecars.

These helpers intentionally avoid any database or Qt imports so the file
scanner can cheaply ask "is this one of my own sidecars?" without pulling in
the whole library stack.

DocumentStudio writes durable same-folder sidecars beside the source file::

    report.pdf       -> source document
    report.pdf.json  -> rich JSON sidecar (repo authority)
    report.pdf.xmp   -> portable XMP sidecar (interoperability export)
"""

from __future__ import annotations

from pathlib import Path

SIDECAR_SUFFIXES: tuple[str, ...] = (".json", ".xmp")


def sidecar_path_for(source_path: Path, suffix: str = ".json") -> Path:
    """Return the same-folder sidecar path for a source file.

    The full source name is preserved so ``report.pdf`` becomes
    ``report.pdf.json``, which keeps the sidecar distinct from a sibling
    ``report.txt`` and lets the source suffix survive a round-trip.
    """
    if suffix not in SIDECAR_SUFFIXES:
        raise ValueError(f"Unsupported sidecar suffix: {suffix!r}")
    return Path(f"{source_path}{suffix}")


def source_path_for(sidecar_path: Path) -> Path:
    """Return the source document path a sidecar describes.

    ``report.pdf.json`` -> ``report.pdf``. This is the inverse of
    :func:`sidecar_path_for` and only strips the final sidecar suffix.
    """
    return sidecar_path.with_suffix("")


def is_managed_sidecar(path: Path) -> bool:
    """Return True when ``path`` is a DocumentStudio sidecar shadowing a source.

    A ``.json`` or ``.xmp`` file is treated as a managed sidecar only when a
    sibling source file exists (e.g. ``report.pdf.json`` next to
    ``report.pdf``). A standalone ``data.json`` with no matching source is left
    alone as ordinary library payload, so real JSON/XMP documents are still
    indexed. This mirrors digiKam, which skips ``image.jpg.xmp`` sidecars while
    still cataloguing genuine files.
    """
    if path.suffix.lower() not in SIDECAR_SUFFIXES:
        return False
    source = source_path_for(path)
    if source == path:
        return False
    return source.is_file()
