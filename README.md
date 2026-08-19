# TV Media Organizer

A Python script that scans a folder of downloaded TV files, parses messy release
filenames, and moves each episode into a clean, Plex-friendly library structure:

```
Show Name/
└── Season 07/
    ├── Show Name - S07E01 - Episode Title.mkv
    ├── Show Name - S07E02 - Episode Title.mkv
    └── ...
```

It handles both loose files (`S07E16.mkv`) and full season/series packs inside
nested folders, strips out release-group cruft (`1080p`, `WEB-DL`, `x265`, site
prefixes, bracketed junk, etc.), and cleans up empty source folders once every
file has been moved successfully.

---

## Features

- **Flexible filename parsing** — recognizes both `SxxExx` (e.g. `S07E16`) and
  `NxNN` (e.g. `1x02`) episode formats. The `NxNN` pattern is guarded so it
  won't misfire on resolutions like `1920x1080`.
- **Show name resolution** — if the show name isn't in the filename, it's
  derived from the nearest meaningful parent folder, skipping structural folders
  like `Season 7`, `Series`, `Extras`, and `Specials`.
- **Title cleanup** — removes quality/codec/release tags, streaming-service tags
  (`AMZN`, `NF`, `DSNP`, …), site prefixes (`somesite.to - `), and leftover
  bracketed blocks, then applies smart title-casing that preserves apostrophes.
- **Safe source cleanup** — a source folder or file is only deleted after
  **every** video file in it has been moved. If any file fails to parse or move,
  the whole item is left in place so nothing is lost.
- **Parallel processing** — uses a thread pool (configurable) so multiple show
  folders can be processed at once.
- **Logging** — every move, skip, duplicate, and failure is written to a log
  file.

---

## Requirements

- Python 3.7+
- [`python-dotenv`](https://pypi.org/project/python-dotenv/)

Install the dependency:

```bash
pip install python-dotenv
```

(Everything else — `os`, `re`, `shutil`, `logging`, `concurrent.futures` — is
part of the Python standard library.)

---

## Configuration

The script reads its settings from a `.env` file in the same directory. Create
one before running:

```env
# Required
SOURCE_DIR=/path/to/your/downloads
DEST_DIR=/path/to/your/tv/library

# Optional
LOG_DIR=/path/to/logs           # defaults to the script's own directory
MAX_WORKERS=1                   # threads; keep low for HDDs, raise to 8+ for SSD/NVMe
STRIP_YEAR_FROM_SHOW=True       # see note below
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `SOURCE_DIR` | Yes | — | Folder to scan for TV files. |
| `DEST_DIR` | Yes | — | Root of your organized library where episodes are moved. |
| `LOG_DIR` | No | script directory | Where `tv_show_organizer.log` is written. |
| `MAX_WORKERS` | No | `1` | Number of worker threads. Keep at 1–2 for spinning HDDs; 8+ is fine for SSD/NVMe. |
| `STRIP_YEAR_FROM_SHOW` | No | `True` | When `True`, a trailing `(YYYY)` is removed from the show name so `Impractical Jokers (2011)` and loose `Impractical Jokers` files land in one folder. Set to `False` for Plex-style `Show Name (Year)` folders. |

Accepted "true" values for the boolean setting: `true`, `1`, `yes`
(case-insensitive).

---

## Usage

Once your `.env` is set up:

```bash
python TVMediaOragnizerScript.py
```

The script prints live progress to the terminal, for example:

```
Starting TV show organization...
Found 42 target item(s). Deploying 4 async threads.

Progress: 42/42 (100%) | Active: Some.Show.Name...

TV show processing complete! Folders Cleaned: 38 | Skipped/Unchanged: 2 | Left in source (couldn't parse): 2
```

### Supported video extensions

`.mkv` `.mp4` `.avi` `.mov` `.wmv` `.flv` `.webm` `.m4v`

Any file with an unrecognized extension is ignored.

---

## Output structure

For each parsed episode, the script builds:

```
DEST_DIR/
└── <Show Name>/
    └── Season <NN>/
        └── <Show Name> - S<NN>E<NN> - <Title>.<ext>
```

If no episode title can be recovered, the title portion is dropped:

```
<Show Name> - S<NN>E<NN>.<ext>
```

---

## How source cleanup works

This is the most important safety behavior to understand:

- Files that **can't be parsed** are logged as warnings and **left exactly where
  they are** — they are never deleted.
- A source directory is removed **only if every video file inside it was moved
  successfully**. If even one file fails, the entire folder is left in source and
  reported under "Left in source (couldn't parse)".
- If a destination file already exists, the incoming file is treated as a
  **duplicate**: it's skipped and the source copy is removed to keep the source
  clean.

Result outcomes reported per item:

| Status | Meaning |
|---|---|
| `processed` | At least one file was moved and the source was cleaned up. |
| `skipped` | Nothing to do (no video files, or only duplicates). |
| `unparsed` | Some files couldn't be parsed/moved; the item was left in source. |

---

## Logging

A log file named `tv_show_organizer.log` is written to `LOG_DIR` (or the script's
directory by default). It records every moved episode, skipped duplicate,
unparseable file, and cleanup action, with timestamps. Check this file if a show
didn't end up where you expected.

---

## Notes & caveats

- **Test on a copy first.** The script *moves* and *deletes* files. Point
  `SOURCE_DIR` at a small test folder before running it on your real library.
- **HDD vs SSD:** high `MAX_WORKERS` values can actually *slow down* spinning
  drives due to seek thrashing. Only raise it for SSD/NVMe storage.
- Files with no recognizable `SxxExx` / `NxNN` pattern are intentionally left
  untouched rather than guessed at.
- The script calls `os._exit(0)` on completion to exit immediately without
  waiting on lingering threads.

---
