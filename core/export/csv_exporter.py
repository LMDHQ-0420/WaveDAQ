import os
import csv
import numpy as np
from datetime import datetime
from typing import Optional


def build_filepath(
    record_name: str,
    default_filename: Optional[str],
    default_dir: Optional[str],
    append_date: bool,
    append_time: bool,
    filter_suffix: Optional[str] = None,
) -> str:
    """Build the suggested save filepath from naming settings."""
    now = datetime.now()
    date_str = now.strftime('%Y%m%d')
    time_str = now.strftime('%H%M%S')

    template = default_filename or f"{record_name}.csv"
    processed = template.replace('{name}', record_name)
    processed = processed.replace('{date}', date_str).replace('{time}', time_str)

    has_date_ph = '{date}' in template
    has_time_ph = '{time}' in template

    base, ext = os.path.splitext(processed)
    if not ext:
        ext = '.csv'

    suffix = ''
    if append_date and not has_date_ph:
        suffix += '_' + date_str
    if append_time and not has_time_ph:
        suffix += '_' + time_str
    if filter_suffix:
        base = base + filter_suffix

    final_name = base + suffix + ext
    return os.path.join(default_dir, final_name) if default_dir else final_name


def export_to_csv(
    data: list,
    channels: list[int],
    filepath: str,
    filtered: bool = False,
    filter_low: float = 0.0,
    filter_high: float = 0.0,
) -> None:
    """Write selected channels to a CSV file (rows = samples, cols = channels).

    If filtered=True, applies threshold_filter before writing.
    """
    from core.signal.filters import threshold_filter

    rows = []
    for ch in channels:
        arr = np.asarray(data[ch], dtype=np.float32)
        if filtered:
            arr = threshold_filter(arr, filter_low, filter_high)
        rows.append(arr)

    transposed = np.array(rows).T
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(transposed)
