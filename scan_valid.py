"""
scan_valid.py
-------------
Strict link validator: 200-299 + real data + fast response = alive.
NO retries, NO auto-fix. Slow streams (>3s) are dead (buffering).

Usage:
    python scan_valid.py merged.m3u output.m3u --stats-file stats.json
"""

import argparse
import json
import logging
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter

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

# Plain requests session — NO retries
session = requests.Session()
session.headers.update(HEADERS)
adapter = HTTPAdapter(max_retries=0, pool_connections=500, pool_maxsize=500)
session.mount("http://", adapter)
session.mount("https://", adapter)

TIMEOUT = 3             # seconds — hard limit for connect + read
MAX_LATENCY_MS = 3000   # streams slower than this = buffering = dead
MAX_WORKERS = 500


def _enforce_socket_timeout(response, timeout):
    """Force socket read timeout so raw.read() cannot block 18 sec."""
    try:
        # urllib3 v2: response.raw._connection.sock
        sock = response.raw._connection.sock
        if sock:
            sock.settimeout(timeout)
            return
    except Exception:
        pass
    try:
        # urllib3 v1 / fallback
        sock = response.raw._fp.fp.raw._sock
        if sock:
            sock.settimeout(timeout)
    except Exception:
        pass


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
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("#")):
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
    """Strict single-shot check with enforced read timeout.

    - 200-299 + data + latency <= 3000ms → alive
    - 403/404/500/502/timeout/empty/slow → DEAD
    """
    extinf, url = extinf_url
    try:
        start = time.perf_counter()
        r = session.get(url, timeout=(TIMEOUT, TIMEOUT), allow_redirects=True, stream=True)
        _enforce_socket_timeout(r, TIMEOUT)

        # This read now respects TIMEOUT via socket timeout
        chunk = r.raw.read(1024)
        latency = int((time.perf_counter() - start) * 1000)
        try:
            r.close()
        except Exception:
            pass

        status = r.status_code

        # Too slow = buffering = dead (fixes 18086ms average)
        if latency > MAX_LATENCY_MS:
            return extinf, url, False, status, latency

        if 200 <= status < 300 and len(chunk) > 0:
            return extinf, url, True, status, latency
        return extinf, url, False, status, latency

    except (requests.exceptions.Timeout, TimeoutError):
        return extinf, url, False, 0, 0
    except requests.exceptions.ConnectionError:
        return extinf, url, False, 0, 0
    except Exception as e:
        # socket.timeout etc lands here
        if "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
            return extinf, url, False, 0, 0
        return extinf, url, False, 0, 0


def scan_links(entries, workers=MAX_WORKERS):
    total = len(entries)
    if total == 0:
        return [], {"alive": 0, "dead": 0, "total": 0}

    log.info(f"Scanning {total} links (STRICT 200-299, socket timeout {TIMEOUT}s, max {MAX_LATENCY_MS}ms)...")

    results: list[tuple | None] = [None] * total
    dead = 0
    alive = 0
    latencies = []
    error_counts = {}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_idx = {ex.submit(check_url, entry): idx for idx, entry in enumerate(entries)}
        done = 0
        for fut in as_completed(future_to_idx):
            done += 1
            idx = future_to_idx[fut]
            extinf, url, is_alive, status, latency = fut.result()
            if is_alive:
                results[idx] = (extinf, url)
                alive += 1
                latencies.append(latency)
            else:
                dead += 1
                # Track reason: include slow as separate bucket
                if status == 0:
                    key = "Timeout/Error"
                elif latency > MAX_LATENCY_MS:
                    key = f"Slow >{MAX_LATENCY_MS}ms"
                else:
                    key = f"HTTP {status}"
                error_counts[key] = error_counts.get(key, 0) + 1

            if done % 500 == 0 or done == total:
                log.info(f"  {done}/{total} checked — {alive} valid, {dead} dead")

    valid = [r for r in results if r is not None]

    # Accurate latency: median + trimmed mean (capped, no 18s outliers)
    if latencies:
        avg_latency = int(sum(latencies) / len(latencies))
        median_latency = int(statistics.median(latencies))
        # Also report p95 to show tail
        sorted_lat = sorted(latencies)
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if len(sorted_lat) > 20 else sorted_lat[-1]
    else:
        avg_latency = median_latency = p95 = 0

    if error_counts:
        log.info("Dead link breakdown:")
        for err_type, count in sorted(error_counts.items(), key=lambda x: -x[1]):
            log.info(f"  {err_type}: {count}")

    log.info(f"Done: {len(valid)} valid / {dead} dead / avg {avg_latency}ms median {median_latency}ms p95 {p95}ms (order preserved)")
    return valid, {
        "alive": len(valid),
        "dead": dead,
        "total": total,
        "avg_latency_ms": avg_latency,
        "median_latency_ms": median_latency,
        "p95_latency_ms": p95,
        "error_breakdown": error_counts,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="STRICT M3U scanner with enforced timeout")
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

    with open(args.stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    log.info(f"Stats saved -> {args.stats_file}")

    print(f"\n{'='*50}")
    print(f"  SCAN RESULTS")
    print(f"{'='*50}")
    print(f"  Total      : {stats['total']}")
    print(f"  Valid      : {stats['alive']}")
    print(f"  Dead       : {stats['dead']}")
    print(f"  Avg latency: {stats['avg_latency_ms']} ms")
    print(f"  Median     : {stats.get('median_latency_ms','?')} ms")
    print(f"  p95        : {stats.get('p95_latency_ms','?')} ms")
    if stats.get('error_breakdown'):
        print(f"\n  Dead breakdown:")
        for err, cnt in sorted(stats['error_breakdown'].items(), key=lambda x: -x[1]):
            print(f"    {err}: {cnt}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
