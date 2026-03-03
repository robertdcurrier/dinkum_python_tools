#!/usr/bin/env python3
"""Convert Slocum glider binary .sbd/.tbd files to ASCII .dba.

Replaces the legacy Dinkum C binary dbd2asc tool with a pure
Python implementation. Reads binary segment files and writes
human-readable ASCII output to stdout.

Usage:
    dbd2asc.py [-h] [-s] [-o] [-k] [-c cache-path] files...
"""
import argparse
import glob
import math
import os
import struct
import sys

try:
    from colorama import Fore, Style
    from colorama import init as colorama_init
    from tqdm import tqdm
    HAS_EXTRAS = True
except ImportError:
    HAS_EXTRAS = False


def parse_header(f):
    """Read ASCII header key-value pairs from a binary file.

    The header consists of num_ascii_tags lines, each in the
    format: key:    value (colon + spaces + value + newline).

    Returns a dict of header key-value pairs and the count
    of lines actually read (always matches num_ascii_tags).
    """
    header = {}
    for i in range(3):
        line = f.readline().decode('ascii').strip()
        key, val = line.split(':', 1)
        header[key.strip()] = val.strip()
    num_tags = int(header['num_ascii_tags'])
    for _ in range(num_tags - 3):
        line = f.readline().decode('ascii').strip()
        key, val = line.split(':', 1)
        header[key.strip()] = val.strip()
    return header


def load_cache(crc, cache_dir):
    """Load sensor definitions from a .cac cache file.

    Cache files are named {crc}.cac. Each line has format:
    s: T/F  index  unknown  byte_size  sensor_name  units

    Returns list of dicts for sensors marked 'T' (active),
    sorted by their cycle index.
    """
    path = os.path.join(cache_dir, f'{crc}.cac')
    sensors = []
    with open(path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 7 or parts[0] != 's:':
                continue
            active = parts[1] == 'T'
            if not active:
                continue
            sensors.append({
                'index': int(parts[2]),
                'byte_size': int(parts[4]),
                'name': parts[5],
                'units': parts[6],
            })
    sensors.sort(key=lambda s: s['index'])
    return sensors


def read_known_bytes(f):
    """Read the known-bytes cycle for byte-swap detection.

    Structure after tag byte 's':
      1-byte int, 2-byte int (0x1234),
      4-byte float (123.456), 8-byte double (123456789.12345)

    Returns True if little-endian (expected), raises on
    mismatch.
    """
    tag = f.read(1)
    if tag != b's':
        raise ValueError(
            f'Expected known-bytes tag "s", got {tag!r}'
        )
    f.read(1)  # 1-byte int
    i2 = struct.unpack('<h', f.read(2))[0]
    f4 = struct.unpack('<f', f.read(4))[0]
    f.read(8)  # 8-byte double
    if i2 != 0x1234:
        raise ValueError(
            f'Byte-swap check failed: got 0x{i2:04x}'
        )
    if abs(f4 - 123.456) > 0.01:
        raise ValueError(
            f'Float check failed: got {f4}'
        )
    return True


def decode_states(state_data, n_sensors):
    """Decode 2-bit-per-sensor state bytes.

    Bits are packed MSB-first: bits [7:6] = sensor 0,
    bits [5:4] = sensor 1, etc. States:
      0 = not updated, 1 = same value,
      2 = new value in stream, 3 = new value in stream.

    Returns list of state values (0-3) for each sensor.
    """
    states = []
    for byte in state_data:
        for shift in [6, 4, 2, 0]:
            states.append((byte >> shift) & 0x03)
    return states[:n_sensors]


def read_sensor_value(f, byte_size):
    """Read a single sensor value from the binary stream.

    Sizes: 1 = int8, 2 = int16, 4 = float32, 8 = float64.
    All values are little-endian.
    """
    raw = f.read(byte_size)
    if len(raw) < byte_size:
        return None
    if byte_size == 1:
        return struct.unpack('<b', raw)[0]
    elif byte_size == 2:
        return struct.unpack('<h', raw)[0]
    elif byte_size == 4:
        return struct.unpack('<f', raw)[0]
    elif byte_size == 8:
        return struct.unpack('<d', raw)[0]
    return None


def read_cycle(f, sensors, state_byte_count):
    """Read one data cycle from the binary stream.

    Returns (tag, states, values) where values is a dict
    mapping sensor index to the new value. Returns None
    at EOF or on 'X' tag.
    """
    tag_byte = f.read(1)
    if not tag_byte:
        return None
    tag = chr(tag_byte[0])
    if tag == 'X':
        return None
    state_data = f.read(state_byte_count)
    if len(state_data) < state_byte_count:
        return None
    states = decode_states(state_data, len(sensors))
    values = {}
    for i, (state, sensor) in enumerate(
        zip(states, sensors)
    ):
        if state >= 2:
            val = read_sensor_value(f, sensor['byte_size'])
            if val is not None:
                values[i] = val
    return (tag, states, values)


def format_value(val, byte_size):
    """Format a sensor value for ASCII output.

    4-byte floats use 6 significant digits (%g).
    8-byte doubles use 15 significant digits.
    NaN values output as 'NaN'.
    """
    if val is None:
        return 'NaN'
    if isinstance(val, float) and math.isnan(val):
        return 'NaN'
    if byte_size <= 4:
        return f'{val:.6g}'
    return f'{val:.15g}'


def build_output_header(
    header, sensors, segment_names
):
    """Build the DBA ASCII output header lines.

    Transforms binary header tags into ASCII output format.
    Returns list of header lines (without newlines).
    """
    name = header.get('full_filename', '')
    ext = header.get('filename_extension', '')
    the8x3 = header.get('the8x3_filename', '')
    n_segs = len(segment_names)
    num_tags = 14 + max(0, n_segs - 1)
    lines = [
        'dbd_label:'
        ' DBD_ASC(dinkum_binary_data_ascii)file',
        'encoding_ver: 2',
        f'num_ascii_tags: {num_tags}',
        'all_sensors: 0',
        f'filename: {name}',
        f'the8x3_filename: {the8x3}',
        f'filename_extension: {ext}',
        f'filename_label: {name}-{ext}({the8x3})',
    ]
    lines.extend(_build_remaining_header(
        header, sensors, n_segs, segment_names
    ))
    return lines


def _build_remaining_header(
    header, sensors, n_segs, segment_names
):
    """Build remaining header lines after filename_label."""
    lines = [
        'mission_name: '
        f'{header.get("mission_name", "")}',
        'fileopen_time: '
        f'{header.get("fileopen_time", "")}',
        f'sensors_per_cycle: {len(sensors)}',
        'num_label_lines: 3',
        f'num_segments: {n_segs}',
    ]
    for i, seg in enumerate(segment_names):
        lines.append(f'segment_filename_{i}: {seg}')
    return lines


def write_sensor_lines(out, sensors):
    """Write the 3 sensor label lines to output.

    Line 1: space-separated sensor names
    Line 2: space-separated units
    Line 3: space-separated byte sizes
    """
    names = ' '.join(s['name'] for s in sensors)
    units = ' '.join(s['units'] for s in sensors)
    sizes = ' '.join(str(s['byte_size']) for s in sensors)
    out.write(names + ' \n')
    out.write(units + ' \n')
    out.write(sizes + ' \n')


def write_data_row(out, current_vals, sensors):
    """Write one data row to output.

    Each row is space-separated formatted values.
    """
    parts = []
    for i, sensor in enumerate(sensors):
        parts.append(
            format_value(current_vals[i], sensor['byte_size'])
        )
    out.write(' '.join(parts) + ' \n')


def convert_files(
    filepaths, cache_dir, output_initial, out=None
):
    """Convert one or more binary files to ASCII.

    Writes a single combined header, then data from each
    file in order. The header uses the first file's info
    with all files listed as segments.
    """
    if out is None:
        out = sys.stdout
    segment_names = [
        _get_full_filename(fp) for fp in filepaths
    ]
    header_written = False
    for filepath in filepaths:
        with open(filepath, 'rb') as f:
            header = parse_header(f)
            sensors = _load_sensors(header, cache_dir, f)
            n = len(sensors)
            sb = int(header['state_bytes_per_cycle'])
            read_known_bytes(f)
            header_written = _process_cycles(
                f, header, sensors, n, sb,
                output_initial,
                header_written, segment_names, out,
            )


def _get_full_filename(filepath):
    """Extract full_filename from a binary file header."""
    with open(filepath, 'rb') as f:
        header = parse_header(f)
    return header.get('full_filename', '')


def _load_sensors(header, cache_dir, f):
    """Load sensor definitions from cache or inline."""
    crc = header.get('sensor_list_crc', '')
    factored = int(header.get('sensor_list_factored', '0'))
    if factored == 1:
        return load_cache(crc, cache_dir)
    return _read_inline_sensors(f, header)


def _read_inline_sensors(f, header):
    """Read sensor definitions from inline data in file."""
    total = int(header.get('total_num_sensors', '0'))
    sensors = []
    for _ in range(total):
        line = f.readline().decode('ascii').strip()
        parts = line.split()
        if len(parts) < 7 or parts[0] != 's:':
            continue
        if parts[1] == 'T':
            sensors.append({
                'index': int(parts[2]),
                'byte_size': int(parts[4]),
                'name': parts[5],
                'units': parts[6],
            })
    sensors.sort(key=lambda s: s['index'])
    return sensors


def _process_cycles(
    f, header, sensors, n_sensors,
    state_bytes, output_initial,
    header_written, segment_names, out,
):
    """Read and output all data cycles.

    Returns updated header_written flag.
    """
    last_known = [float('nan')] * n_sensors
    first_cycle = True
    while True:
        result = read_cycle(f, sensors, state_bytes)
        if result is None:
            break
        _, states, values = result
        row = _build_row(last_known, states, values)
        if first_cycle:
            first_cycle = False
            if not output_initial:
                continue
        if not header_written:
            header_written = _write_header(
                header, sensors, segment_names, out,
            )
        write_data_row(out, row, sensors)
    if not header_written and not first_cycle:
        header_written = _write_header(
            header, sensors, segment_names, out,
        )
    return header_written


def _build_row(last_known, states, values):
    """Build output row from state bits and value buffer.

    State 0: output NaN (sensor absent this cycle).
    State 1: output last known value (carry forward).
    State 2/3: output new value, update last_known.
    The last_known buffer persists across state-0 gaps.
    """
    row = []
    for i in range(len(last_known)):
        if states[i] >= 2 and i in values:
            last_known[i] = values[i]
            row.append(values[i])
        elif states[i] == 1:
            row.append(last_known[i])
        else:
            row.append(float('nan'))
    return row


def _write_header(
    header, sensors, segment_names, out
):
    """Write DBA header and sensor label lines."""
    lines = build_output_header(
        header, sensors, segment_names
    )
    for line in lines:
        out.write(line + '\n')
    write_sensor_lines(out, sensors)
    return True


def sort_files_by_time(filepaths):
    """Sort input files by fileopen_time from headers.

    Opens each file, reads just the header to extract
    fileopen_time, then sorts all files by that time.
    """
    timed = []
    for fp in filepaths:
        with open(fp, 'rb') as f:
            header = parse_header(f)
        timed.append((header.get('fileopen_time', ''), fp))
    timed.sort()
    return [fp for _, fp in timed]


def _create_parser():
    """Create the CLI argument parser."""
    p = argparse.ArgumentParser(
        description='Convert Slocum glider binary'
        ' files to ASCII.'
    )
    p.add_argument(
        'files', nargs='*',
        help='Binary .sbd/.tbd files to convert'
    )
    p.add_argument(
        '-s', action='store_true',
        help='Read filenames from stdin'
    )
    p.add_argument(
        '-o', action='store_true',
        help='Output initial data lines'
    )
    p.add_argument(
        '-k', action='store_true',
        help='Suppress optional header keys'
    )
    p.add_argument(
        '-c', '--cache-dir', metavar='PATH',
        default=None,
        help='Cache directory for .cac files'
    )
    _add_batch_args(p)
    return p


def _add_batch_args(p):
    """Add batch mode arguments to the parser."""
    p.add_argument(
        '--input-path', metavar='DIR',
        help='Input directory of binary files'
    )
    p.add_argument(
        '--output-path', metavar='DIR',
        help='Output directory for .dba files'
    )
    p.add_argument(
        '--both', action='store_true',
        help='Process sbd->flight and tbd->science'
    )
    p.add_argument(
        '-v', '--verbose', action='store_true',
        help='Show progress bar and colored output'
    )


def main():
    """CLI entry point for dbd2asc."""
    args = _create_parser().parse_args()
    if args.input_path:
        _run_batch(args)
    else:
        _run_single(args)


def _run_single(args):
    """Run single/merged file conversion to stdout."""
    filepaths = _collect_filepaths(args)
    cache_dir = _resolve_cache_dir(args.cache_dir)
    filepaths = sort_files_by_time(filepaths)
    convert_files(filepaths, cache_dir, args.o)


def _validate_paths(input_path, output_path):
    """Verify input/output path pairing is correct.

    sbd input must pair with flight output, and
    tbd input must pair with science output. Exits
    with an error if paths are mismatched.
    """
    inp = input_path.lower()
    out = output_path.lower()
    if 'sbd' in inp and 'flight' not in out:
        print(
            'ERROR: sbd input requires a flight '
            'output path, got: ' + output_path,
            file=sys.stderr,
        )
        sys.exit(1)
    if 'tbd' in inp and 'science' not in out:
        print(
            'ERROR: tbd input requires a science '
            'output path, got: ' + output_path,
            file=sys.stderr,
        )
        sys.exit(1)


def _require_extras():
    """Exit if colorama/tqdm are not installed."""
    if not HAS_EXTRAS:
        print(
            'Install colorama and tqdm for --verbose',
            file=sys.stderr,
        )
        sys.exit(1)


def _run_both(args):
    """Process both sbd->flight and tbd->science."""
    if args.verbose:
        _require_extras()
    cache_dir = _resolve_cache_dir(args.cache_dir)
    pairs = [('sbd', 'flight'), ('tbd', 'science')]
    total_ok = total_fail = 0
    for sub_in, sub_out in pairs:
        ok, fail = _run_both_pair(
            args, cache_dir, sub_in, sub_out
        )
        total_ok += ok
        total_fail += fail
    _print_summary(
        total_ok, total_fail, args.verbose
    )


def _run_both_pair(args, cache_dir, sub_in, sub_out):
    """Process one sbd/tbd pair for --both mode."""
    in_dir = os.path.join(args.input_path, sub_in)
    out_dir = os.path.join(args.output_path, sub_out)
    if not os.path.isdir(in_dir):
        return 0, 0
    files = sorted(
        glob.glob(os.path.join(in_dir, '*.*bd'))
    )
    if not files:
        return 0, 0
    os.makedirs(out_dir, exist_ok=True)
    if args.verbose:
        print(f'\n{sub_in} -> {sub_out}')
    return _convert_batch(
        files, out_dir, cache_dir,
        args.o, args.verbose,
    )


def _run_batch(args):
    """Batch convert all binary files in a directory."""
    if not args.output_path:
        print(
            '--output-path required with --input-path',
            file=sys.stderr,
        )
        sys.exit(1)
    if args.both:
        _run_both(args)
        return
    _validate_paths(args.input_path, args.output_path)
    if args.verbose:
        _require_extras()
    cache_dir = _resolve_cache_dir(args.cache_dir)
    pattern = os.path.join(args.input_path, '*.*bd')
    files = sorted(glob.glob(pattern))
    if not files:
        print(
            f'No binary files in {args.input_path}',
            file=sys.stderr,
        )
        sys.exit(1)
    os.makedirs(args.output_path, exist_ok=True)
    ok, fail = _convert_batch(
        files, args.output_path, cache_dir,
        args.o, args.verbose,
    )
    _print_summary(ok, fail, args.verbose)


def _convert_batch(files, output_path, cache_dir,
                   output_initial, verbose):
    """Convert files in batch, return (ok, fail)."""
    if verbose:
        colorama_init()
        iterator = tqdm(
            files, desc='Converting', unit='file'
        )
    else:
        iterator = files
    ok = fail = 0
    for f in iterator:
        base = os.path.splitext(
            os.path.basename(f)
        )[0]
        out = os.path.join(
            output_path, f'{base}.dba'
        )
        try:
            _convert_one(
                f, out, cache_dir, output_initial,
            )
            ok += 1
        except (OSError, ValueError, KeyError) as e:
            fail += 1
            _report_failure(base, e, verbose)
    return ok, fail


def _convert_one(filepath, out_path, cache_dir,
                 output_initial):
    """Convert a single binary file to .dba."""
    with open(out_path, 'w') as out:
        convert_files(
            [filepath], cache_dir,
            output_initial, out,
        )


def _report_failure(base, error, verbose):
    """Report a failed file conversion."""
    if verbose:
        tqdm.write(
            f'{Fore.RED}FAIL: {base}: '
            f'{error}{Style.RESET_ALL}'
        )
    else:
        print(
            f'FAIL: {base}: {error}',
            file=sys.stderr,
        )


def _print_summary(ok, fail, verbose):
    """Print batch conversion summary."""
    if verbose:
        g = f'{Fore.GREEN}{ok} converted'
        g += f'{Style.RESET_ALL}'
        r = f'{Fore.RED}{fail} failed'
        r += f'{Style.RESET_ALL}'
        print(f'\n{g}, {r}')
    else:
        print(f'{ok} converted, {fail} failed')


def _collect_filepaths(args):
    """Collect input file paths from args or stdin."""
    filepaths = list(args.files)
    if args.s:
        for line in sys.stdin:
            line = line.strip()
            if line:
                filepaths.append(line)
    if not filepaths:
        print(
            'No input files specified.',
            file=sys.stderr,
        )
        sys.exit(1)
    return filepaths


def _resolve_cache_dir(cache_arg):
    """Resolve the cache directory path."""
    if cache_arg:
        return cache_arg
    parent = os.environ.get('GLIDER_PARENT_DIR', '')
    if parent:
        return os.path.join(parent, 'cache')
    return './cache'


if __name__ == '__main__':
    main()
