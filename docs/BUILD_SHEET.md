# DataCardForge — Build Sheet

Owner: Chris Decker (grummpy). Public repo: grummpy/DataCardForge. Runs fully local and offline. Synthetic sample data only.

## Goal
Point at a dataset folder (CSV, Parquet, or image-class folders `root/<class>/*.jpg`) and auto-write a data card in Markdown, HTML and JSON, then edit it in a local UI.

## Card sections
- Overview: name, version, description, created date.
- Size: rows/files, columns, bytes on disk, image count & resolution stats.
- Schema: column, dtype, example values, unique count.
- Class balance: per-label counts/% (auto-detect `label`/`class`/`target` column or folder names), imbalance ratio, warning thresholds.
- Missingness: per-column null %, rows with any missing.
- Duplicates: exact row dupes; image dupes via SHA-256 and perceptual hash (near-dupes).
- Sources: editable list (auto-filled from README/LICENSE/source.txt if present).
- License: editable field (SPDX picker), auto-detected from LICENSE file.
- Known gaps: auto suggestions (rare classes, high-missing columns, small image sizes) + editable.
- Intended use / out-of-scope use: editable.
- PII hint scan: flag columns that look like emails/phones/names (warning only).

## Outputs
`<dataset>/DATACARD.md`, `DATACARD.html` (self-contained, embedded SVG charts), `datacard.json` (schema-versioned). Edits saved to JSON and re-rendered; auto fields refresh on re-scan without clobbering user edits.

## UI (local, 127.0.0.1:8767)
Choose folder, Scan, view/edit card sections, live preview, Export. No network calls; no CDN assets.

## Layout
`datacardforge/{scan_tabular,scan_images,stats,dupes,render,store,server}.py`, `web/`, `samples/` (generated synthetic CSV, Parquet, and colored-shape image classes), `tests/`, launchers, `art/`.

## Tests (pytest, offline)
Synthetic fixtures: CSV with nulls + dupes, Parquet, image folders with an exact and near duplicate. Assert sizes, schema, balance, missingness %, dupe counts, three outputs written, user edits survive re-scan, no network (socket blocked in tests).

## Launchers
`launch-mac.command`, `launch-windows.bat`, `launch-linux.sh`: venv, install, run, open browser.

## Done when
Tests green, UI tried end to end on samples, README with art, merged to main.
