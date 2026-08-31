"""
scan_valid.py
-------------
Strict link validator: checks if each channel URL is reachable (HTTP 200-299).
NO retries, NO auto-fix. If server returns 403/404/500/502/503/520, it's DEAD.

Usage:
    python scan_valid.py merged.m3u output.m3u --stats-file stats.json
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# Plain requests session — NO retries, NO auto-fix
session = requests.Session()
session.headers.update(HEADERS)
adapter = HTTPAdapter(
    max_retries=0,           # ZERO retries — one shot only
    pool_connections=500,
    pool_maxsize=500,
)
session.mount("http://", adapter)
session.mount("https://", adapter)

TIMEOUT = 3        # seconds
MAX_WORKERS = 500  # parallel workers

# HTTP status codes that mean DEAD
DEAD_STATUSES = {403, 404, 405, 406, 410, 429, 500, 502, 503, 520, 521, 522, 523, 524, 525, 526, 530}


# ── M3U Parsing ──────────────────────────────────────────────────────────────

def parse_m3u(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            j = i + 1
            while j < len(lines) and (
                not lines[j].strip() or lines[j].strip().startswith("#")
            ):
                j += 1
            if j < len(lines):
                url = lines[j].strip()
                if url.startswith("http"):
                    entries.append((line, url))
            i = j + 1
        else:
            i += 1
    return entries


def write_m3u(filepath, entries):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for extinf, url in entries:
            f.write(f"{extinf}\n")
            f.write(f"{url}\n")


# ── Stream Check ─────────────────────────────────────────────────────────────

def check_url(extinf_url):
    """STRICT check: single GET, ZERO retries. ONE chance only.

    - 200-299 AND real data → alive
    - 403, 404, 500, 502, 503, 520, timeout, empty → DEAD
    - cloudscraper is NOT used — plain requests only
    """
    extinf, url = extinf_url
    try:
        start = time.time()
        r = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        # Read first 1024 bytes — must contain real data
        chunk = r.raw.read(1024)
        latency = int((time.time() - start) * 1000)
        r.close()

        status = r.status_code

        # STRICT: 200-299 ONLY with real data = alive. Everything else = DEAD.
        if 200 <= status < 300 and len(chunk) > 0:
            return extinf, url, True, status, latency
        return extinf, url, False, status, latency

    except requests.exceptions.Timeout:
        return extinf, url, False, 0, 0
    except requests.exceptions.ConnectionError:
        return extinf, url, False, 0, 0
    except Exception as e:
        return extinf, url, False, 0, 0


def scan_links(entries, workers=MAX_WORKERS):
    total = len(entries)
    if total == 0:
        return [], {"alive": 0, "dead": 0, "total": 0}

    log.info(f"Scanning {total} links (STRICT — no retries, no cloudscraper)...")

    results: list[tuple | None] = [None] * total
    dead = 0
    alive = 0
    latencies = []
    error_counts = {}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_idx = {
            ex.submit(check_url, entry): idx
            for idx, entry in enumerate(entries)
        }
        done = 0
        for fut in as_completed(future_to_idx):
            done += 1
            idx = future_to_idx[fut]
            extinf, url, is_alive, status, latency = fut.result()
            if is_alive:
                results[idx] = (extinf, url)
                alive += 1
                if latency > 0:
                    latencies.append(latency)
            else:
                dead += 1
                key = f"HTTP {status}" if status else "Timeout/Error"
                error_counts[key] = error_counts.get(key, 0) + 1

            if done % 500 == 0 or done == total:
                log.info(f"  {done}/{total} checked — {alive} valid, {dead} dead")

    valid = [r for r in results if r is not None]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0

    if error_counts:
        log.info("Dead link breakdown:")
        for err_type, count in sorted(error_counts.items(), key=lambda x: -x[1]):
            log.info(f"  {err_type}: {count}")

    log.info(f"Done: {len(valid)} valid / {dead} dead / avg {avg_latency}ms (order preserved)")
    return valid, {
        "alive": len(valid),
        "dead": dead,
        "total": total,
        "avg_latency_ms": avg_latency,
        "error_breakdown": error_counts,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="STRICT M3U link scanner (no retries)")
    parser.add_argument("input", nargs="?", default="merged.m3u")
    parser.add_argument("output", nargs="?", default="merged.m3u")
    parser.add_argument("--stats-file", default="scan_stats.json", help="JSON file to write scan stats")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        log.error(f"{args.input} not found")
        sys.exit(1)

    entries = parse_m3u(args.input)
    log.info(f"Loaded {len(entries)} channels from {args.input}")

    if not entries:
        log.error("No channels found")
        sys.exit(1)

    valid_entries, stats = scan_links(entries)

    write_m3u(args.output, valid_entries)
    log.info(f"Saved {len(valid_entries)} valid channels -> {args.output}")

    stats_file = args.stats_file
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    log.info(f"Stats saved -> {stats_file}")

    print(f"\n{'='*50}")
    print(f"  SCAN RESULTS")
    print(f"{'='*50}")
    print(f"  Total      : {stats['total']}")
    print(f"  Valid      : {stats['alive']}")
    print(f"  Dead       : {stats['dead']}")
    print(f"  Avg latency: {stats['avg_latency_ms']} ms")
    if stats.get('error_breakdown'):
        print(f"\n  Dead breakdown:")
        for err, cnt in sorted(stats['error_breakdown'].items(), key=lambda x: -x[1]):
            print(f"    {err}: {cnt}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
