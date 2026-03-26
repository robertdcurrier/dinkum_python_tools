#!/usr/bin/env python3
"""Merge flight and science .dba files by timestamp.

Replaces the legacy Dinkum C binary dba_merge tool with a
pure Python implementation. Merges flight (.sbd-derived)
and science (.tbd-derived) ASCII .dba files into a single
combined .dba file, interleaved by timestamp.

Usage:
    dba_merge.py flight.dba science.dba > merged.dba
    dba_merge.py --flight-path DIR --science-path DIR \
        --output-path DIR [--verbose]
"""
import argparse
import glob
import os
import sys

try:
    from colorama import Fore, Style
    from colorama import init as colorama_init
    from tqdm import tqdm
    HAS_EXTRAS = True
except ImportError:
    HAS_EXTRAS = False


def parse_dba(filepath):
    """Parse a .dba ASCII file into header, sensors, data.

    Reads the header lines, sensor label lines, and data
    rows. Data rows are kept as lists of string tokens to
    avoid any float reformatting.

    Returns dict with header_lines, sensor_names,
    sensor_units, sensor_sizes, and data_rows.
    """
    with open(filepath, 'r') as f:
        header_lines = _read_header(f)
        names, units, sizes = _read_sensor_lines(f)
        data_rows = _read_data_rows(f)
    return {
        'header_lines': header_lines,
        'sensor_names': names,
        'sensor_units': units,
        'sensor_sizes': sizes,
        'data_rows': data_rows,
    }


def _read_header(f):
    """Read num_ascii_tags header lines from a .dba file."""
    lines = []
    for _ in range(3):
        lines.append(f.readline().rstrip('\n'))
    num_tags = int(lines[2].split(':')[1].strip())
    for _ in range(num_tags - 3):
        lines.append(f.readline().rstrip('\n'))
    return lines


def _read_sensor_lines(f):
    """Read the 3 sensor label lines (names, units, sizes).

    Returns (names_list, units_list, sizes_list).
    """
    names = f.readline().strip().split()
    units = f.readline().strip().split()
    sizes = f.readline().strip().split()
    return names, units, sizes


def _read_data_rows(f):
    """Read all data rows as lists of string tokens."""
    rows = []
    for line in f:
        stripped = line.strip()
        if stripped:
            rows.append(stripped.split())
    return rows


def find_time_col(sensor_names, col_name):
    """Find index of a named sensor in the sensor list.

    Returns the index or None if not found.
    """
    try:
        return sensor_names.index(col_name)
    except ValueError:
        return None


def build_merged_header(flight_dba, science_dba):
    """Build merged header from flight header + sensors.

    Uses flight file's header metadata. Updates
    sensors_per_cycle to flight + science count.
    Concatenates sensor name/unit/size lines.

    Returns list of header line strings (no newlines).
    """
    total = (
        len(flight_dba['sensor_names'])
        + len(science_dba['sensor_names'])
    )
    header = []
    for line in flight_dba['header_lines']:
        if line.startswith('sensors_per_cycle:'):
            header.append(
                f'sensors_per_cycle: {total}'
            )
        else:
            header.append(line)
    return header


def merge_rows(flight_dba, science_dba):
    """Merge flight and science data rows by timestamp.

    Rows with matching timestamps are combined into one.
    Unmatched flight rows get NaN science columns.
    Unmatched science rows get NaN flight columns with
    m_present_time set to sci_m_present_time.
    All rows sorted by effective timestamp.

    Returns list of merged row token lists.
    """
    f_names = flight_dba['sensor_names']
    s_names = science_dba['sensor_names']
    f_time = find_time_col(f_names, 'm_present_time')
    s_time = find_time_col(s_names, 'sci_m_present_time')
    sci_lookup = _build_sci_lookup(
        science_dba['data_rows'], s_time
    )
    tagged = _merge_flight_with_sci(
        flight_dba['data_rows'], f_time,
        sci_lookup, len(s_names),
    )
    tagged += _remaining_sci_rows(
        sci_lookup, s_time, f_time, len(f_names)
    )
    tagged.sort(key=lambda t: t[0])
    return [row for _, row in tagged]


def _build_sci_lookup(sci_rows, s_time_col):
    """Build timestamp -> list of science rows lookup."""
    lookup = {}
    for row in sci_rows:
        ts = _get_timestamp(row, s_time_col)
        lookup.setdefault(ts, []).append(row)
    return lookup


def _merge_flight_with_sci(
    flt_rows, f_time_col, sci_lookup, sci_count
):
    """Merge flight rows, combining with matching sci."""
    tagged = []
    nan_pad = ['NaN'] * sci_count
    for row in flt_rows:
        ts = _get_timestamp(row, f_time_col)
        if ts in sci_lookup and sci_lookup[ts]:
            sci_row = sci_lookup[ts].pop(0)
            if not sci_lookup[ts]:
                del sci_lookup[ts]
            tagged.append((ts, row + sci_row))
        else:
            tagged.append((ts, row + list(nan_pad)))
    return tagged


def _remaining_sci_rows(
    sci_lookup, s_time_col, f_time_col, flt_count
):
    """Build tagged rows for unmatched science data.

    Sets m_present_time position to sci_m_present_time.
    """
    tagged = []
    for ts, rows in sci_lookup.items():
        for row in rows:
            nan_pad = ['NaN'] * flt_count
            if (f_time_col is not None
                    and s_time_col is not None):
                nan_pad[f_time_col] = row[s_time_col]
            tagged.append((ts, nan_pad + row))
    return tagged


def _get_timestamp(row, time_col):
    """Extract timestamp as float from a row."""
    if time_col is None or time_col >= len(row):
        return 0.0
    try:
        return float(row[time_col])
    except (ValueError, IndexError):
        return 0.0


def write_merged(out, header_lines, sensor_dba, rows):
    """Write merged .dba output to a stream.

    Writes header lines, sensor label lines, then data
    rows. Sensor and data lines have trailing space.
    """
    for line in header_lines:
        out.write(line + '\n')
    _write_sensor_lines(out, sensor_dba)
    for row in rows:
        out.write(' '.join(row) + ' \n')


def _write_sensor_lines(out, sensor_dba):
    """Write the 3 sensor label lines to output."""
    names = ' '.join(sensor_dba['sensor_names'])
    units = ' '.join(sensor_dba['sensor_units'])
    sizes = ' '.join(sensor_dba['sensor_sizes'])
    out.write(names + ' \n')
    out.write(units + ' \n')
    out.write(sizes + ' \n')


def merge_pair(flight_path, science_path, out):
    """Merge one flight+science pair to output stream."""
    flight_dba = parse_dba(flight_path)
    science_dba = parse_dba(science_path)
    header = build_merged_header(flight_dba, science_dba)
    rows = merge_rows(flight_dba, science_dba)
    combined = {
        'sensor_names': (
            flight_dba['sensor_names']
            + science_dba['sensor_names']
        ),
        'sensor_units': (
            flight_dba['sensor_units']
            + science_dba['sensor_units']
        ),
        'sensor_sizes': (
            flight_dba['sensor_sizes']
            + science_dba['sensor_sizes']
        ),
    }
    write_merged(out, header, combined, rows)


def _create_parser():
    """Create the CLI argument parser."""
    p = argparse.ArgumentParser(
        description='Merge flight and science .dba'
        ' files by timestamp.'
    )
    p.add_argument(
        'files', nargs='*',
        help='Flight and science .dba files to merge'
    )
    p.add_argument(
        '--flight-path', metavar='DIR',
        help='Directory of flight .dba files'
    )
    p.add_argument(
        '--science-path', metavar='DIR',
        help='Directory of science .dba files'
    )
    p.add_argument(
        '--output-path', metavar='DIR',
        help='Output directory for merged .dba files'
    )
    p.add_argument(
        '-v', '--verbose', action='store_true',
        help='Show progress bar and colored output'
    )
    return p


def main():
    """CLI entry point for dba_merge."""
    args = _create_parser().parse_args()
    if args.flight_path:
        _run_batch(args)
    else:
        _run_single(args)


def _run_single(args):
    """Merge one flight+science pair to stdout."""
    if len(args.files) != 2:
        print(
            'Usage: dba_merge.py flight.dba science.dba',
            file=sys.stderr,
        )
        sys.exit(1)
    merge_pair(args.files[0], args.files[1], sys.stdout)


def _run_batch(args):
    """Batch merge all paired files in directories."""
    if not args.science_path or not args.output_path:
        print(
            '--science-path and --output-path required'
            ' with --flight-path',
            file=sys.stderr,
        )
        sys.exit(1)
    if args.verbose and not HAS_EXTRAS:
        print(
            'Install colorama and tqdm for --verbose',
            file=sys.stderr,
        )
        sys.exit(1)
    pairs = _find_pairs(
        args.flight_path, args.science_path
    )
    if not pairs:
        print(
            'No matching file pairs found.',
            file=sys.stderr,
        )
        sys.exit(1)
    os.makedirs(args.output_path, exist_ok=True)
    ok, fail = _convert_batch(
        pairs, args.output_path, args.verbose
    )
    _print_summary(ok, fail, args.verbose)


def _find_pairs(flight_dir, science_dir):
    """Find matching flight+science file pairs.

    Pairs files by matching basename. Returns list of
    (flight_path, science_path, basename) tuples sorted
    by basename.
    """
    pattern = os.path.join(flight_dir, '*.dba')
    flight_files = sorted(glob.glob(pattern))
    pairs = []
    for fpath in flight_files:
        base = os.path.basename(fpath)
        spath = os.path.join(science_dir, base)
        if os.path.isfile(spath):
            pairs.append((fpath, spath, base))
    return pairs


def _convert_batch(pairs, out_dir, verbose):
    """Merge file pairs in batch, return (ok, fail)."""
    if verbose:
        colorama_init()
        iterator = tqdm(
            pairs, desc='Merging', unit='pair'
        )
    else:
        iterator = pairs
    ok = fail = 0
    for fpath, spath, base in iterator:
        out_path = os.path.join(out_dir, base)
        try:
            _merge_one(fpath, spath, out_path)
            ok += 1
        except (OSError, ValueError, KeyError) as e:
            fail += 1
            name = os.path.splitext(base)[0]
            _report_failure(name, e, verbose)
    return ok, fail


def _merge_one(flight_path, science_path, out_path):
    """Merge one pair to an output file."""
    with open(out_path, 'w') as out:
        merge_pair(flight_path, science_path, out)


def _report_failure(base, error, verbose):
    """Report a failed file merge."""
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
    """Print batch merge summary."""
    if verbose:
        g = f'{Fore.GREEN}{ok} merged'
        g += f'{Style.RESET_ALL}'
        r = f'{Fore.RED}{fail} failed'
        r += f'{Style.RESET_ALL}'
        print(f'\n{g}, {r}')
    else:
        print(f'{ok} merged, {fail} failed')


if __name__ == '__main__':
    main()
