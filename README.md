# DataCardForge

<img src="art/icon.png" alt="DataCardForge icon" width="72">

![DataCardForge cover](art/cover.png)

DataCardForge writes a data card for a folder on your machine. Point it at CSV, Parquet, or image-class folders (`folder/<class>/*.jpg`) and it scans size, schema, class balance, missing values, duplicates, license, and possible PII columns. You can edit the narrative sections locally. A later scan refreshes the measured fields and keeps what you typed.

The app binds to **127.0.0.1:8767**. Card files are written next to the dataset: `DATACARD.md`, `DATACARD.html` (self-contained, with SVG charts), and `datacard.json`. Nothing is uploaded. The page does not load fonts, scripts, or images from the network.

Sample datasets in `samples/` are synthetic. Names, emails, and phone numbers are fictional.

## Launch

The first launch creates a virtual environment and installs dependencies. That install step needs network access. After that, scanning, editing, and the test suite run offline.

**macOS** — double-click `launch-mac.command` (or run it in Terminal).

**Windows** — double-click `launch-windows.bat`.

**Linux**

```bash
./launch-linux.sh
```

Each launcher checks that `art/icon.png` and `art/cover.png` are present, installs into `.venv`, starts the editor, and opens `http://127.0.0.1:8767`.

From an existing environment:

```bash
python -m pip install -r requirements.txt
python -m datacardforge
```

## Use the editor

1. Pick a sample or browse to a dataset folder, then choose **Scan**.
2. Read the measured sections and edit overview, license, sources, known gaps, intended use, and out-of-scope use. The preview updates as you type.
3. **Save** writes the three card files. **Export** downloads one of them.
4. **Re-scan** after the files change. Fields you edited stay. Counts, schema, balance, missingness, duplicates, and the auto gap list are computed again.
5. **Discard edits** rebuilds the card from the folder only.

Editable text is stored with `"source": "user"` in `datacard.json`. Re-scan replaces `"source": "auto"` fields. Hand-editing the JSON the same way is picked up on the next scan.

Image classes are immediate subfolders that contain images (`jpg`, `jpeg`, `png`, `gif`, `webp`, `bmp`). Tabular files are `.csv` and `.parquet` in the dataset root. Exact image copies use SHA-256. Near-duplicates use a 64-bit difference hash plus an 8×8 color distance, so a recolored shape is not treated as a copy of another shape.

PII hints are warnings only. Columns that look like emails, phone numbers, or personal names are flagged. Values are not removed.

Suggested gaps use these thresholds: a class under 10% when there are at least two classes, an imbalance ratio (largest / smallest) above 3, a column more than 20% missing, or an image shorter than 32 px on its shortest side.

## Tests

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

The test suite blocks outbound sockets (loopback is allowed for the local server test). Fixtures are synthetic CSV rows with nulls and duplicate records, a Parquet file, and drawn images with one exact copy and one near copy.

## Layout

```
datacardforge/     scanner, card merge, HTML/Markdown render, local server
web/               browser UI (no build step, no CDN)
samples/           synthetic CSV, Parquet, and colored-shape images
tests/             offline pytest suite
art/icon.png       icon used by the launchers and the UI
art/cover.png      cover used on the welcome screen
launch-mac.command
launch-windows.bat
launch-linux.sh
```

Regenerate the sample files with `python samples/generate.py`.
