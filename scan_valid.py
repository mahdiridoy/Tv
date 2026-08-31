"""
scan_valid.py
-------------
Simple link validator: checks if each channel URL is reachable (HTTP 200-299).
Keeps valid links, removes dead ones. Saves to output file.

Usage:
    python scan_valid.py merged.m3u merged.m3u
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import cloudscraper

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
scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update(HEADERS)

TIMEOUT = 2        # seconds — shorter timeout = faster dead-link detection
MAX_WORKERS = 500  # more parallel workers to go through ~20k URLs quicker


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
    """Hard check: single GET request, read first bytes. ONE chance only.

    - 200-299 AND data received → alive, latency = time to first bytes
    - Anything else → DEAD, no retry
    """
    extinf, url = extinf_url
    try:
        start = time.time()
        r = scraper.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
        # Read first chunk to confirm stream actually delivers data
        chunk = r.raw.read(1024)
        latency = int((time.time() - start) * 1000)
        r.close()
        if 200 <= r.status_code < 300 and len(chunk) > 0:
            return extinf, url, True, r.status_code, latency
        return extinf, url, False, r.status_code, latency
    except Exception as e:
        return extinf, url, False, 0, 0


def scan_links(entries, workers=MAX_WORKERS):
    total = len(entries)
    if total == 0:
        return [], {"alive": 0, "dead": 0, "total": 0}

    log.info(f"Scanning {total} links (simple HTTP check)...")

    # results[i] = (extinf, url) if alive, else None
    results: list[tuple | None] = [None] * total
    dead = 0
    latencies = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        # Map each future to its ORIGINAL index so we can restore order later
        future_to_idx = {
            ex.submit(check_url, entry): idx
            for idx, entry in enumerate(entries)
        }
        done = 0
        for fut in as_completed(future_to_idx):
            done += 1
            idx = future_to_idx[fut]
            extinf, url, alive, status, latency = fut.result()
            if alive:
                results[idx] = (extinf, url)
                if latency > 0:
                    latencies.append(latency)
            else:
                dead += 1
            if done % 100 == 0 or done == total:
                valid_so_far = sum(1 for r in results if r is not None)
                log.info(f"  {done}/{total} checked — {valid_so_far} valid, {dead} dead")

    # Preserve original order: only keep entries that passed
    valid = [r for r in results if r is not None]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
    log.info(f"Done: {len(valid)} valid / {dead} dead / avg {avg_latency}ms (order preserved)")
    return valid, {"alive": len(valid), "dead": dead, "total": total, "avg_latency_ms": avg_latency}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Simple M3U link scanner")
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

    # Save stats JSON for Telegram notification
    stats_file = args.stats_file
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f)
    log.info(f"Stats saved -> {stats_file}")

    print(f"\n{'='*50}")
    print(f"  SCAN RESULTS")
    print(f"{'='*50}")
    print(f"  Total      : {stats['total']}")
    print(f"  Valid      : {stats['alive']}")
    print(f"  Dead       : {stats['dead']}")
    print(f"  Avg latency: {stats['avg_latency_ms']} ms")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
