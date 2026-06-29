<!-- SPDX-FileCopyrightText: (c) TagStudio Contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# DocumentStudio Sidecars

DocumentStudio keeps the application library useful, but durable document
metadata should also live in app-neutral sidecar files. This makes the SQLite
library **replaceable local state** rather than the only home for your metadata.

Two sidecar formats sit beside each source document:

- **JSON** (`<source>.json`) — the rich, repo-authority format. Everything.
- **XMP** (`<source>.xmp`) — the portable interoperability export that digiKam,
  Adobe apps, and ExifTool can read. A standard subset.

Everything is exposed through the `documentstudio-sidecars` command, and every
run is **dry-run by default** and prints a **machine-readable summary** so it can
be driven and verified by automation, not just by hand.

## Naming

Sidecars use the full source filename plus the format suffix. No
`.documentstudio` segment is used, so discovery stays plain and app-neutral.

| Source | JSON sidecar | XMP sidecar |
|--------|--------------|-------------|
| `report.pdf` | `report.pdf.json` | `report.pdf.xmp` |
| `lesson-plan.docx` | `lesson-plan.docx.json` | `lesson-plan.docx.xmp` |

A `.json`/`.xmp` file is treated as a managed sidecar only when a sibling source
file exists, so a standalone `data.json` document is still catalogued normally.

## Command

```bash
# Dry-run JSON export (default) with a machine-readable summary
documentstudio-sidecars /path/to/library --json

# Write JSON sidecars
documentstudio-sidecars /path/to/library --write

# Write portable XMP sidecars (via ExifTool)
documentstudio-sidecars /path/to/library --xmp --write

# Import sidecars back into the library (the round-trip)
documentstudio-sidecars /path/to/library --import --write
```

Flags: `--write` applies changes (writes files on export, mutates the library on
import); `--overwrite` replaces existing sidecars; `--limit N` bounds the scan;
`--json` prints a JSON summary instead of plain text.

The JSON summary is the point of integration for tooling — e.g.
`{"direction": "export", "format": "xmp", "sidecars_would_write": 3, "errors": 0}`.

## Round-trip

The library can be rebuilt from JSON sidecars alone: **export → discard the
SQLite library → re-scan the files → import**. Tags are keyed by durable
identity (name plus parent names), not the local database id, so a sidecar
written by one library re-applies cleanly to a freshly rebuilt one. Import is
idempotent — re-applying a sidecar adds nothing.

## XMP field mapping

XMP carries the portable subset. The mapping is the single source of truth in
`tagstudio.core.sidecars.xmp_mapping`:

| DocumentStudio | XMP property | Cardinality |
|----------------|--------------|-------------|
| tags (visible) | `dc:subject` | list |
| Title | `dc:title` | single |
| Description | `dc:description` | single |
| Author, Artist | `dc:creator` | list |
| Source | `dc:source` | single |
| Publisher | `dc:publisher` | single |
| URL | `dc:identifier` | single |
| Rating | `xmp:Rating` (validated −1…5) | single |
| Date, Date Created | `xmp:CreateDate` | single |
| Date Modified | `xmp:ModifyDate` | single |

Anything without a mapping stays JSON-only by design.

## Current guarantees

- dry-run is the default; writes require `--write`
- existing sidecars are preserved unless `--overwrite` is explicit
- source document bytes are never modified
- embedded document metadata is not modified (XMP is written to a sidecar only)
- the library indexer skips managed sidecars, sibling-conditionally
- GUI tag-mutation hooks are not patched yet

## Verification

- new XMP tests (mapping + ExifTool write→read-back round-trip): `10`
- combined sidecar + library regression: `67` passing
- lint findings: `0`
- XMP export uses ExifTool; it is skipped gracefully where ExifTool is absent

Protocol deviations: `0`.
