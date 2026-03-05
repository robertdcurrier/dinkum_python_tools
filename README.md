# Dinkum Python Tools

Pure Python replacements for the legacy Dinkum C binary
tools used to process Slocum underwater glider data.

Part of the Gandalf backend — replaces 12-year-old 32-bit
Linux ELF binaries with portable, zero-dependency Python
that produces bit-exact identical output.

## dbd2asc.py

Converts Slocum glider binary `.sbd` (flight) and `.tbd`
(science) segment files to ASCII `.dba` format. Drop-in
replacement for the legacy C `dbd2asc` binary.

Validated against 600 reference files (300 flight +
300 science) with zero differences.

### Quick Start

```bash
# Single file to stdout
python3 tools/dbd2asc.py \
    -c /path/to/cache_files \
    flight_segment.sbd > output.dba

# Batch convert flight data
python3 tools/dbd2asc.py \
    --input-path /path/to/sbd \
    --output-path /path/to/flight \
    --cache-dir /path/to/cache_files

# Batch convert science data
python3 tools/dbd2asc.py \
    --input-path /path/to/tbd \
    --output-path /path/to/science \
    --cache-dir /path/to/cache_files

# Both flight and science in one command
python3 tools/dbd2asc.py \
    --input-path /path/to/binary_files \
    --output-path /path/to/dba \
    --cache-dir /path/to/cache_files \
    --both --verbose
```

### CLI Reference

```
usage: dbd2asc.py [-h] [-s] [-o] [-k] [-c PATH]
                  [--input-path DIR] [--output-path DIR]
                  [--both] [-v] [files ...]
```

| Flag | Description |
|------|-------------|
| `files` | Binary .sbd/.tbd files (single mode) |
| `-c`, `--cache-dir` | Directory containing .cac files |
| `-s` | Read filenames from stdin |
| `-o` | Include initial data cycle in output |
| `-k` | Suppress optional header keys |
| `--input-path` | Input directory for batch mode |
| `--output-path` | Output directory for batch mode |
| `--both` | Process sbd->flight and tbd->science |
| `-v`, `--verbose` | Progress bars and colored output |

### Batch Mode

**Single type** — specify the exact input and output
directories. Path validation ensures sbd pairs with
flight and tbd pairs with science:

```bash
python3 tools/dbd2asc.py \
    --input-path data/binary_files/sbd \
    --output-path output/flight \
    --cache-dir data/cache_files
```

**Both types** — specify parent directories and use
`--both`. Automatically maps `sbd/` to `flight/` and
`tbd/` to `science/`:

```bash
python3 tools/dbd2asc.py \
    --input-path data/binary_files \
    --output-path output/dba \
    --cache-dir data/cache_files \
    --both
```

### How It Works

Slocum gliders encode sensor data in binary segment files
with a 2-bit-per-sensor state encoding:

| State | Meaning |
|-------|---------|
| 0 | Sensor absent this cycle (NaN) |
| 1 | Same value as last cycle (carry forward) |
| 2 | New value follows in stream |
| 3 | New value follows in stream |

The converter maintains a running value buffer so that
state-1 sensors carry forward their last known value
across state-0 gaps, exactly matching the legacy C
behavior.

## dba_merge.py

Merges flight and science `.dba` files into a single
combined `.dba` file, interleaved by timestamp. Drop-in
replacement for the legacy C `dba_merge` binary.

Validated against 300 reference merged files with zero
differences.

### Quick Start

```bash
# Single pair to stdout
python3 tools/dba_merge.py \
    flight.dba science.dba > merged.dba

# Batch merge all pairs
python3 tools/dba_merge.py \
    --flight-path /path/to/flight \
    --science-path /path/to/science \
    --output-path /path/to/merged \
    --verbose
```

### CLI Reference

```
usage: dba_merge.py [-h] [--flight-path DIR]
                    [--science-path DIR]
                    [--output-path DIR] [-v]
                    [files ...]
```

| Flag | Description |
|------|-------------|
| `files` | Flight and science .dba files (single mode) |
| `--flight-path` | Flight .dba directory (batch mode) |
| `--science-path` | Science .dba directory (batch mode) |
| `--output-path` | Output directory (batch mode) |
| `-v`, `--verbose` | Progress bars and colored output |

### How It Works

Rows from both files are interleaved by timestamp:

- **Matching timestamps** — flight and science values
  are joined into a single row
- **Flight-only timestamps** — flight values with NaN
  in all science columns
- **Science-only timestamps** — NaN in flight columns
  (with `m_present_time` set to `sci_m_present_time`)
  followed by science values

The merged header uses the flight file's metadata with
`sensors_per_cycle` updated to the combined sensor count.

## Dependencies

Python 3.6+ required.

```bash
pip install -r requirements.txt
```

## Directory Layout

```
tools/
  dbd2asc.py           # Python binary-to-ASCII converter
  dba_merge.py         # Python flight+science merger
  batch_dbd2asc.sh     # Shell batch wrapper
  dinkum/              # Legacy C binaries (reference)
data/                  # Test data (not in repo)
  binary_files/
    sbd/               # Flight binary segments
    tbd/               # Science binary segments
  ascii_files/dba/
    flight/            # Reference flight ASCII
    science/           # Reference science ASCII
  cache_files/         # Sensor metadata caches (.cac)
```

## Roadmap

- [x] `dbd2asc` — binary to ASCII conversion
- [x] `dba_merge` — merge flight + science .dba files
- [ ] `rename_dbd_files` — rename raw binary files
- ~~`dba_sensor_filter`~~ — not needed; handled via
  JSONB queries in PostgreSQL
- ~~`dba_time_filter`~~ — not needed; handled via SQL
  WHERE clauses in PostgreSQL

## License

MIT License. See [LICENSE](LICENSE) for details.
