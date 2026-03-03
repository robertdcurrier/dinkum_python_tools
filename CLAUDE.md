# CLAUDE.md

This file provides guidance to Claude Code
(claude.ai/code) when working with code in this
repository.

## Project Overview

Dinkum Python Tools — pure Python replacements for the
legacy Dinkum C binary tools used in the Gandalf backend
for processing Slocum underwater glider data. Handles
the pipeline from binary glider telemetry to ASCII
conversion, with sensor filtering and merging planned.

## Completed Tools

- `tools/dbd2asc.py` — drop-in replacement for the
  legacy C `dbd2asc` binary. Converts Slocum glider
  binary `.sbd`/`.tbd` segment files to ASCII `.dba`
  format. Validated bit-exact against 600 reference
  files (300 flight + 300 science). Supports single
  file, batch, and combined `--both` modes.

- `tools/dba_merge.py` — drop-in replacement for the
  legacy C `dba_merge` binary. Merges flight and
  science `.dba` files by timestamp into combined
  output. Rows with matching timestamps are joined;
  unmatched rows are NaN-padded. Validated bit-exact
  against 300 reference merged files. Supports single
  pair (stdout) and batch modes.

## Running

```bash
# dbd2asc: single file to stdout (legacy-compatible)
python3 tools/dbd2asc.py -c <cache-dir> file.sbd

# dbd2asc: batch, one type at a time
python3 tools/dbd2asc.py \
    --input-path data/binary_files/sbd \
    --output-path output/flight \
    --cache-dir data/cache_files

# dbd2asc: batch, both flight and science
python3 tools/dbd2asc.py \
    --input-path data/binary_files \
    --output-path output/dba \
    --cache-dir data/cache_files \
    --both --verbose

# dba_merge: single pair to stdout
python3 tools/dba_merge.py flight.dba science.dba

# dba_merge: batch all pairs
python3 tools/dba_merge.py \
    --flight-path output/flight \
    --science-path output/science \
    --output-path output/merged \
    --verbose
```

## Dependencies

See `requirements.txt`. Install with:
```bash
pip install -r requirements.txt
```

- `colorama` — colored terminal output
- `tqdm` — progress bars

## Architecture

### Pipeline

Slocum gliders produce binary segment files (`.sbd`
for flight, `.tbd` for science). These get converted
to ASCII `.dba` files, then merged into combined
flight+science records. Cache files (`.cac`) store
sensor metadata used during conversion.

### Binary Format Details

Each binary file contains:
1. ASCII header (key: value pairs)
2. Sensor definitions (inline or via `.cac` cache)
3. Known-bytes validation cycle (endianness check)
4. Data cycles with 2-bit state encoding per sensor:
   - State 0: sensor absent (output NaN)
   - State 1: same value (carry forward last known)
   - State 2/3: new value follows in stream

### Path Conventions

Batch mode enforces path pairing:
- `sbd` input dir must pair with `flight` output dir
- `tbd` input dir must pair with `science` output dir
- `--both` mode auto-maps `sbd/`->`flight/` and
  `tbd/`->`science/`

### Directory Layout

- `tools/` — utility scripts and binaries
  - `dbd2asc.py` — Python binary-to-ASCII converter
  - `dba_merge.py` — Python flight+science merger
  - `batch_dbd2asc.sh` — shell batch wrapper
  - `dinkum/` — legacy 32-bit Linux ELF binaries
    (reference implementations):
    - `dbd2asc` / `dbd2asc_24` — binary to ASCII
    - `dba_merge` — merge flight + science `.dba`
    - `dba_sensor_filter` — filter sensors
    - `dba_time_filter` — filter by time range
    - `rename_dbd_files` — rename raw files
- `data/` — test data (not in repo, see .gitignore)
  - `binary_files/sbd/` — flight binary segments
  - `binary_files/tbd/` — science binary segments
  - `ascii_files/dba/flight/` — reference flight DBA
  - `ascii_files/dba/science/` — reference science DBA
  - `cache_files/` — `.cac` sensor metadata caches

## Remaining Tools to Implement

- `dba_sensor_filter` — filter sensors from `.dba`
- `dba_time_filter` — filter `.dba` by time range
- `rename_dbd_files` — rename raw binary files

## Conventions

- All Python scripts must include
  `#!/usr/bin/env python3` shebang
- PEP-8 compliant code
- No lines over 79 characters
- No functions over 35 lines (excluding docstrings)
- Imports at the very top of files
- Test against reference output from legacy C tools
