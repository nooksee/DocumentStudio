<!-- SPDX-FileCopyrightText: (c) TagStudio Contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# DocumentStudio Sidecars

DocumentStudio keeps the application library useful, but durable document metadata should also be exportable into app-neutral sidecar files.

The first sidecar surface is the `documentstudio-sidecars` command. It exports JSON sidecars from the current DocumentStudio library state.

## Naming

JSON sidecars use the source filename plus `.json`.

Examples:

- `report.pdf`
- `report.pdf.json`
- `lesson-plan.docx`
- `lesson-plan.docx.json`

No `.documentstudio` filename segment is used.

## Command

```bash
documentstudio-sidecars /path/to/library --limit 10 --json
```

The command defaults to dry-run mode.

Use `--write` only when sidecar writes are intended:

```bash
documentstudio-sidecars /path/to/library --write
```

Existing sidecars are preserved by default. Use `--overwrite` only when replacement is intentional:

```bash
documentstudio-sidecars /path/to/library --write --overwrite
```

## Current Guarantees

- dry-run is the default
- write mode requires `--write`
- existing sidecars are preserved unless `--overwrite` is explicit
- source document bytes are not modified
- embedded metadata is not modified
- GUI tag mutation hooks are not patched yet

## Exported Data

The JSON sidecar includes:

- schema name
- generator tool and version
- source entry ID, path, filename, suffix, and dates
- visible keyword list
- tag details
- text fields
- datetime fields

JSON sidecars are the rich repo-authority format. XMP sidecars remain the planned interoperability format for portable fields such as keywords, title, description, rating, creator, and reliable dates.

## Verification

Initial service verification on 2026-06-25:

- fixture dry-run entries seen: `3`
- fixture sidecars written: `0`
- sidecar tests passed: `5`
- lint findings: `0`

Protocol deviations: `0`.
