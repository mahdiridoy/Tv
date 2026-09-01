"""
scan_valid.py
-------------
TRIPLE-CHECK validator: 200-299 + real data + fast (<3000ms) must pass 3 TIMES.
If any of the 3 fails (403/404/500/timeout/slow/empty/error body) -> DEAD.

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
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

session = requests.Session()
session.headers.update(HEADERS)
adapter = HTTPAdapter(max_retries=0, pool_connections=500, pool_maxsize=500)
session.mount("http://", adapter)
session.mount("https://", adapter)

TIMEOUT = 3
MAX_LATENCY_MS = 3000
MAX_WORKERS = 500
TRIPLE_CHECKS = 3  # must pass 3 times

ERROR_BODY_KEYWORDS = [
    b"403 forbidden", b"404 not found", b"access denied",
    b"server error", b"bad gateway", b"service unavailable",
    b"cloudflare", b"attention required",
]


def _enforce_socket_timeout(response, timeout):
    try:
        sock = response.raw._connection.sock
        if sock:
            sock.settimeout(timeout)
            return
    except Exception:
        pass
    try:
        sock = response.raw._fp.fp.raw._sock
        if sock:
            sock.settimeout(timeout)
    except Exception:
        pass


def _single_probe(url):
    """One probe: returns (alive, status, latency, reason)."""
    try:
        start = time.perf_counter()
        r = session.get(url, timeout=(TIMEOUT, TIMEOUT), allow_redirects=True, stream=True, verify=False)
        _enforce_socket_timeout(r, TIMEOUT)
        chunk = r.raw.read(1024)
        latency = int((time.perf_counter() - start) * 1000)
        try:
            r.close()
        except Exception:
            pass
        status = r.status_code

        if latency > MAX_LATENCY_MS:
            return False, status, latency, f"slow:{latency}ms"
        if not (200 <= status < 300):
            return False, status, latency, f"status:{status}"
        if len(chunk) == 0:
            return False, status, latency, "empty"
        # Check body for error page even when status is 200
        lower = chunk[:800].lower()
        for kw in ERROR_BODY_KEYWORDS:
            if kw in lower:
                return False, status, latency, f"error_body:{kw.decode()}"
        return True, status, latency, "ok"

    except (requests.exceptions.Timeout, TimeoutError):
        return False, 0, 0, "timeout"
    except requests.exceptions.ConnectionError as e:
        # SSL expired etc - try without verify already False, so still dead
        return False, 0, 0, "conn_error"
    except Exception as e:
        msg = str(e).lower()
        if "timed out" in msg or "timeout" in type(e).__name__.lower():
            return False, 0, 0, "timeout"
        return False, 0, 0, f"error:{type(e).__name__}"


def check_url(extinf_url):
    """Triple-check: must pass 3 consecutive probes."""
    extinf, url = extinf_url
    latencies = []
    last_status = 0
    last_reason = ""
    for attempt in range(TRIPLE_CHECKS):
        alive, status, latency, reason = _single_probe(url)
        last_status = status
        last_reason = reason
        if not alive:
            return extinf, url, False, status, latency
        latencies.append(latency)
        if attempt < TRIPLE_CHECKS - 1:
            time.sleep(0.2)  # small gap between checks

    # All 3 passed - use median latency
    median_lat = int(statistics.median(latencies)) if latencies else 0
    return extinf, url, True, last_status, median_lat


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


def scan_links(entries, workers=MAX_WORKERS):
    total = len(entries)
    if total == 0:
        return [], {"alive": 0, "dead": 0, "total": 0}

    log.info(f"Scanning {total} links TRIPLE-CHECK (3x {TIMEOUT}s, max {MAX_LATENCY_MS}ms, verify=False)...")

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
                if status == 0:
                    key = "Timeout/Error"
                elif latency > MAX_LATENCY_MS:
                    key = f"Slow >{MAX_LATENCY_MS}ms"
                else:
                    key = f"HTTP {status}" if status else "Error"
                error_counts[key] = error_counts.get(key, 0) + 1

            if done % 500 == 0 or done == total:
                log.info(f"  {done}/{total} checked — {alive} valid, {dead} dead")

    valid = [r for r in results if r is not None]

    if latencies:
        avg_latency = int(sum(latencies) / len(latencies))
        median_latency = int(statistics.median(latencies))
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


def main():
    parser = argparse.ArgumentParser(description="TRIPLE-CHECK M3U scanner")
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
    print(f"  SCAN RESULTS (TRIPLE-CHECK)")
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
