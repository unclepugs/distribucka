#!/usr/bin/env python3
"""
Fetches VT/NT tariff switching schedule for a given HDO code.
"""

import json
import re
import sys

import requests

from config import DATA_DIR, HDO_CODE

SOURCE_URL = "https://www.zsdis.sk/Uvod/Online-sluzby/Casy-prepinania-nizkej-a-vysokej-tarify"


def fetch_schedule():
    resp = requests.get(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()

    match = re.search(r"household_rates\s*=\s*(\[.*?\]);", resp.text, re.DOTALL)
    if not match:
        sys.exit("Could not find household_rates in page.")

    raw = match.group(1)
    raw = re.sub(r":\s*'([^']*)'", r': "\1"', raw)
    raw = re.sub(r'([{,\s])([a-z_]\w*)\s*:', r'\1"\2":', raw)
    return json.loads(raw)


def get_hdo(rates, code):
    for entry in rates:
        if str(entry.get("code")) == str(code):
            return entry
    return None


def time_to_min(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def min_to_time(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def compute_vt(nt_intervals):
    """Return VT intervals as complement of NT on a 24h timeline."""
    segments = []
    for iv in nt_intervals:
        s = time_to_min(iv["t_from"])
        e = time_to_min(iv["t_to"])
        if e <= s:          # wraps midnight
            segments.append((0, e))
            segments.append((s, 1440))
        else:
            segments.append((s, e))

    segments.sort()

    # merge overlapping
    merged = []
    for seg in segments:
        if merged and seg[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], seg[1]))
        else:
            merged.append(list(seg))

    vt = []
    prev = 0
    for s, e in merged:
        if s > prev:
            vt.append({"t_type": "vt", "t_from": min_to_time(prev), "t_to": min_to_time(s)})
        prev = e
    if prev < 1440:
        vt.append({"t_type": "vt", "t_from": min_to_time(prev), "t_to": min_to_time(1440)})

    return vt


def main():
    rates = fetch_schedule()
    entry = get_hdo(rates, HDO_CODE)

    if not entry:
        sys.exit(f"HDO code {HDO_CODE} not found.")

    nt_intervals = entry["intervals"]
    vt_intervals = compute_vt(nt_intervals)

    all_intervals = sorted(
        [{**iv, "t_type": "nt"} for iv in nt_intervals] + vt_intervals,
        key=lambda iv: time_to_min(iv["t_from"]),
    )

    print(f"HDO {HDO_CODE} — {len(nt_intervals)} NT + {len(vt_intervals)} VT intervalov\n")
    for iv in all_intervals:
        label = iv["t_type"].upper()
        days  = []
        if iv.get("weekday"): days.append("Po-Pi")
        if iv.get("weekend"): days.append("So-Ne")
        suffix = f"  ({', '.join(days)})" if days else ""
        print(f"  {label}  {iv['t_from']} – {iv['t_to']}{suffix}")

    out = {
        "hdo_code":     HDO_CODE,
        "nt_intervals": nt_intervals,
        "vt_intervals": vt_intervals,
        "all_intervals": all_intervals,
    }
    out_path = f"{DATA_DIR}/tariffs.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
