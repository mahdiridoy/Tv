"""
deep_checker.py
---------------
Deep IPTV stream checker replicating key features of iptv-checker-headless.exe

Features:
- HTTP validation with retry and exponential backoff
- Minimum byte threshold (500KB direct, 128KB HLS)
- HLS manifest following with recursive variant playlist support
- DRM detection (Widevine, FairPlay, PlayReady)
- Geoblocked detection (403/451/426/423 + body patterns)
- Placeholder URL detection (black.ts, blank.ts, etc.)
- Extended timeout (two-pass: short first, longer on failure)
- Triple-check: must pass 3 consecutive checks

Usage:
    python deep_checker.py merged.m3u output.m3u --stats-file stats.json
"""

import argparse
import json
import logging
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Optional
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS (from Rust source code)
# ═══════════════════════════════════════════════════════════════════════════════

# Minimum byte thresholds
MIN_BYTES_DIRECT = 500 * 1024       # 500KB for direct streams
MIN_BYTES_HLS = 128 * 1024          # 128KB for HLS segments

# HLS configuration
MAX_HLS_DEPTH = 4                   # Max recursive depth for variant playlists

# Geoblocked detection
GEOBLOCK_STATUSES = {403, 451, 426, 423}

# Placeholder URL detection
PLACEHOLDER_PATHS = [
    '/video/black.ts',
    '/black.ts',
    '/blank.ts',
    '/placeholder.ts',
    '/null.ts',
]

# Timeouts (seconds)
TIMEOUT_SHORT = 3                   # Short timeout for first pass
TIMEOUT_LONG = 8                    # Longer timeout for failed first pass
MAX_LATENCY_MS = 3000               # Max acceptable latency in ms

# Workers and retries
MAX_WORKERS = 500                   # Parallel threads
TRIPLE_CHECKS = 3                   # Must pass 3 consecutive checks
MAX_RETRIES = 2                     # Max retries with exponential backoff
INITIAL_BACKOFF = 0.5               # Initial backoff in seconds

# Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# Error body keywords for detection
ERROR_BODY_KEYWORDS = [
    b"403 forbidden",
    b"404 not found",
    b"access denied",
    b"server error",
    b"bad gateway",
    b"service unavailable",
    b"cloudflare",
    b"attention required",
]

# DRM detection patterns
DRM_PATTERNS = [
    (re.compile(r'EXT-X-KEY:.*METHOD=(?:SAMPLE-AES|AES-128)', re.IGNORECASE), "Widevine/Standard DRM"),
    (re.compile(r'EXT-X-SESSION-KEY:.*METHOD=(?:SAMPLE-AES|AES-128)', re.IGNORECASE), "Widevine/Session DRM"),
    (re.compile(r'EXT-X-KEY:.*METHOD=FairPlay', re.IGNORECASE), "FairPlay DRM"),
    (re.compile(r'EXT-X-SESSION-KEY:.*METHOD=FairPlay', re.IGNORECASE), "FairPlay Session DRM"),
    (re.compile(r'EXT-X-KEY:.*METHOD=PlayReady', re.IGNORECASE), "PlayReady DRM"),
    (re.compile(r'EXT-X-SESSION-KEY:.*METHOD=PlayReady', re.IGNORECASE), "PlayReady Session DRM"),
]

# Geoblocked body patterns
GEOBLOCK_BODY_PATTERNS = [
    re.compile(b'geoblocked', re.IGNORECASE),
    re.compile(b'not available in your region', re.IGNORECASE),
    re.compile(b'restricted in your country', re.IGNORECASE),
    re.compile(b'access denied.*region', re.IGNORECASE),
    re.compile(b'content not available.*area', re.IGNORECASE),
]


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP SESSION SETUP
# ═══════════════════════════════════════════════════════════════════════════════

session = requests.Session()
session.headers.update(HEADERS)
adapter = HTTPAdapter(max_retries=0, pool_connections=500, pool_maxsize=500)
session.mount("http://", adapter)
session.mount("https://", adapter)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _enforce_socket_timeout(response, timeout):
    """Set socket timeout after connection is established."""
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


def _is_placeholder_url(url: str) -> bool:
    """Check if URL is a known placeholder."""
    url_lower = url.lower()
    return any(path in url_lower for path in PLACEHOLDER_PATHS)


def _detect_drm(content: str) -> Optional[str]:
    """Detect DRM in HLS manifest content."""
    for pattern, drm_type in DRM_PATTERNS:
        if pattern.search(content):
            return drm_type
    return None


def _is_geoblocked(status_code: int, body: bytes) -> Tuple[bool, str]:
    """Check if response indicates geoblocking."""
    # Check status code
    if status_code in GEOBLOCK_STATUSES:
        return True, f"geoblock_status:{status_code}"
    
    # Check body patterns
    body_lower = body[:2000].lower()
    for pattern in GEOBLOCK_BODY_PATTERNS:
        if pattern.search(body_lower):
            return True, f"geoblock_body:{pattern.pattern.decode()}"
    
    return False, ""


def _check_body_errors(chunk: bytes) -> Optional[str]:
    """Check for error keywords in response body."""
    lower = chunk[:800].lower()
    for kw in ERROR_BODY_KEYWORDS:
        if kw in lower:
            return f"error_body:{kw.decode()}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# HLS MANIFEST PARSING
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_hls_manifest(content: str, base_url: str) -> Dict:
    """
    Parse HLS manifest and extract variant playlists and segments.
    Returns dict with 'variants', 'segments', 'drm', and 'total_bytes'.
    """
    result = {
        'variants': [],
        'segments': [],
        'drm': None,
        'total_bytes': 0,
        'has_media': False,
    }
    
    lines = content.strip().split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Check for DRM
        if line.startswith('#EXT-X-KEY') or line.startswith('#EXT-X-SESSION-KEY'):
            drm = _detect_drm(line)
            if drm:
                result['drm'] = drm
        
        # Check for variant playlists (master playlist)
        if line.startswith('#EXT-X-STREAM-INF:'):
            # Next line should be the variant URL
            i += 1
            if i < len(lines):
                variant_url = lines[i].strip()
                if variant_url and not variant_url.startswith('#'):
                    full_url = urljoin(base_url, variant_url)
                    result['variants'].append(full_url)
        
        # Check for media segments (media playlist)
        if line and not line.startswith('#'):
            # This is a segment URL
            full_url = urljoin(base_url, line)
            result['segments'].append(full_url)
            result['has_media'] = True
        
        i += 1
    
    return result


def _follow_hls_recursive(url: str, depth: int = 0) -> Tuple[bool, str, int, Optional[str]]:
    """
    Recursively follow HLS manifests.
    Returns: (is_valid, final_url, total_bytes, drm_type)
    """
    if depth > MAX_HLS_DEPTH:
        return False, url, 0, None
    
    try:
        # Fetch the manifest
        r = session.get(url, timeout=(TIMEOUT_SHORT, TIMEOUT_SHORT), 
                       allow_redirects=True, stream=True, verify=False)
        _enforce_socket_timeout(r, TIMEOUT_SHORT)
        
        # Read content
        content = b''
        for chunk in r.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > 1024 * 1024:  # Limit to 1MB
                break
        
        r.close()
        
        status = r.status_code
        if not (200 <= status < 300):
            return False, url, 0, None
        
        # Check if it's HLS content
        try:
            text = content.decode('utf-8', errors='ignore')
        except:
            return False, url, 0, None
        
        if '#EXTM3U' not in text:
            # Not an HLS manifest, treat as direct stream
            return True, url, len(content), None
        
        # Parse HLS manifest
        manifest = _parse_hls_manifest(text, url)
        
        # Check for DRM
        if manifest['drm']:
            return False, url, 0, manifest['drm']
        
        # If it has variants, follow them recursively
        if manifest['variants']:
            for variant_url in manifest['variants']:
                is_valid, final_url, bytes_count, drm = _follow_hls_recursive(
                    variant_url, depth + 1
                )
                if is_valid:
                    return True, final_url, bytes_count, drm
            return False, url, 0, None
        
        # If it has segments, check minimum byte threshold
        if manifest['segments']:
            # Calculate total estimated bytes
            # For simplicity, we'll check the first few segments
            total_bytes = 0
            segments_to_check = manifest['segments'][:5]  # Check first 5 segments
            
            for seg_url in segments_to_check:
                try:
                    seg_r = session.get(seg_url, timeout=(TIMEOUT_SHORT, TIMEOUT_SHORT),
                                       stream=True, verify=False)
                    seg_content = b''
                    for chunk in seg_r.iter_content(chunk_size=8192):
                        seg_content += chunk
                        if len(seg_content) > 256 * 1024:  # 256KB per segment
                            break
                    seg_r.close()
                    total_bytes += len(seg_content)
                    
                    # If we have enough data, we can stop
                    if total_bytes >= MIN_BYTES_HLS:
                        return True, url, total_bytes, None
                except:
                    continue
            
            if total_bytes >= MIN_BYTES_HLS:
                return True, url, total_bytes, None
            else:
                return False, url, total_bytes, None
        
        # No variants or segments, treat as direct stream
        return True, url, len(content), None
    
    except (requests.exceptions.Timeout, TimeoutError):
        return False, url, 0, None
    except requests.exceptions.ConnectionError:
        return False, url, 0, None
    except Exception as e:
        return False, url, 0, None


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CHECK FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def _single_probe(url: str, timeout: int = TIMEOUT_SHORT, 
                  max_retries: int = MAX_RETRIES) -> Tuple[bool, int, int, str, Optional[str]]:
    """
    Single probe with retry and exponential backoff.
    Returns: (alive, status, latency_ms, reason, drm_type)
    """
    last_reason = "unknown"
    last_status = 0
    
    for attempt in range(max_retries + 1):
        try:
            start = time.perf_counter()
            
            # Check if it's a placeholder URL
            if _is_placeholder_url(url):
                return False, 0, 0, "placeholder_url", None
            
            r = session.get(url, timeout=(timeout, timeout), 
                          allow_redirects=True, stream=True, verify=False)
            _enforce_socket_timeout(r, timeout)
            
            # Read initial chunk
            chunk = r.raw.read(1024)
            latency = int((time.perf_counter() - start) * 1000)
            
            status = r.status_code
            last_status = status
            
            # Check for geoblocking
            is_geoblocked, geoblock_reason = _is_geoblocked(status, chunk)
            if is_geoblocked:
                try:
                    r.close()
                except:
                    pass
                return False, status, latency, geoblock_reason, None
            
            # Check status code
            if not (200 <= status < 300):
                try:
                    r.close()
                except:
                    pass
                last_reason = f"status:{status}"
                if attempt < max_retries:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    time.sleep(backoff)
                    continue
                return False, status, latency, last_reason, None
            
            # Check for error body even with 200 status
            error_reason = _check_body_errors(chunk)
            if error_reason:
                try:
                    r.close()
                except:
                    pass
                if attempt < max_retries:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    time.sleep(backoff)
                    continue
                return False, status, latency, error_reason, None
            
            # Check if it's HLS content
            try:
                text = chunk.decode('utf-8', errors='ignore')
                if '#EXTM3U' in text:
                    # It's HLS, follow it recursively
                    is_valid, final_url, bytes_count, drm_type = _follow_hls_recursive(url)
                    if not is_valid:
                        if drm_type:
                            return False, status, latency, f"drm:{drm_type}", drm_type
                        return False, status, latency, "hls_invalid", None
                    if bytes_count < MIN_BYTES_HLS:
                        return False, status, latency, f"insufficient_bytes:{bytes_count}", None
                    return True, status, latency, "ok", None
            except:
                pass
            
            # Direct stream - read more data to check minimum bytes
            total_bytes = len(chunk)
            if total_bytes < 1024:  # Less than 1KB initially
                # Read more data
                try:
                    for c in r.iter_content(chunk_size=8192):
                        total_bytes += len(c)
                        if total_bytes >= MIN_BYTES_DIRECT:
                            break
                except:
                    pass
            
            try:
                r.close()
            except:
                pass
            
            if total_bytes < MIN_BYTES_DIRECT:
                if attempt < max_retries:
                    backoff = INITIAL_BACKOFF * (2 ** attempt)
                    time.sleep(backoff)
                    continue
                return False, status, latency, f"insufficient_bytes:{total_bytes}", None
            
            return True, status, latency, "ok", None
        
        except (requests.exceptions.Timeout, TimeoutError):
            last_reason = "timeout"
            if attempt < max_retries:
                backoff = INITIAL_BACKOFF * (2 ** attempt)
                time.sleep(backoff)
                continue
            return False, 0, 0, last_reason, None
        except requests.exceptions.ConnectionError:
            last_reason = "conn_error"
            if attempt < max_retries:
                backoff = INITIAL_BACKOFF * (2 ** attempt)
                time.sleep(backoff)
                continue
            return False, 0, 0, last_reason, None
        except Exception as e:
            msg = str(e).lower()
            if "timed out" in msg or "timeout" in type(e).__name__.lower():
                last_reason = "timeout"
            else:
                last_reason = f"error:{type(e).__name__}"
            
            if attempt < max_retries:
                backoff = INITIAL_BACKOFF * (2 ** attempt)
                time.sleep(backoff)
                continue
            return False, 0, 0, last_reason, None
    
    return False, last_status, 0, last_reason, None


def check_url(extinf_url: Tuple[str, str]) -> Tuple[str, str, bool, int, int, Optional[str]]:
    """
    Triple-check: must pass 3 consecutive probes.
    Returns: (extinf, url, is_alive, status, latency_ms, drm_type)
    """
    extinf, url = extinf_url
    latencies = []
    last_status = 0
    last_drm = None
    
    for attempt in range(TRIPLE_CHECKS):
        # First attempt uses short timeout, second uses long timeout
        timeout = TIMEOUT_SHORT if attempt == 0 else TIMEOUT_LONG
        alive, status, latency, reason, drm_type = _single_probe(url, timeout=timeout)
        last_status = status
        last_drm = drm_type
        
        if not alive:
            return extinf, url, False, status, latency, last_drm
        
        latencies.append(latency)
        
        if attempt < TRIPLE_CHECKS - 1:
            time.sleep(0.2)  # Small gap between checks
    
    # All 3 passed - use median latency
    median_lat = int(statistics.median(latencies)) if latencies else 0
    return extinf, url, True, last_status, median_lat, last_drm


# ═══════════════════════════════════════════════════════════════════════════════
# M3U PARSING
# ═══════════════════════════════════════════════════════════════════════════════

def parse_m3u(filepath: str) -> List[Tuple[str, str]]:
    """Parse M3U file and return list of (extinf_line, url) tuples."""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            # Find the next non-empty, non-comment line (the URL)
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


def write_m3u(filepath: str, entries: List[Tuple[str, str]]):
    """Write M3U file with given entries."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for extinf, url in entries:
            f.write(f"{extinf}\n")
            f.write(f"{url}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNING
# ═══════════════════════════════════════════════════════════════════════════════

def scan_links(entries: List[Tuple[str, str]], workers: int = MAX_WORKERS) -> Tuple[List[Tuple[str, str]], Dict]:
    """Scan all entries with deep checks and return valid entries with stats."""
    total = len(entries)
    if total == 0:
        return [], {"alive": 0, "dead": 0, "total": 0}
    
    log.info(f"Deep scanning {total} channels (TRIPLE-CHECK, {TRIPLE_CHECKS}x, "
             f"min {MIN_BYTES_DIRECT//1024}KB direct, {MIN_BYTES_HLS//1024}KB HLS)...")
    
    results: List[Optional[Tuple[str, str]]] = [None] * total
    dead = 0
    alive = 0
    latencies = []
    error_counts = {}
    drm_channels = 0
    geoblocked = 0
    placeholders = 0
    
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_idx = {ex.submit(check_url, entry): idx for idx, entry in enumerate(entries)}
        done = 0
        
        for fut in as_completed(future_to_idx):
            done += 1
            idx = future_to_idx[fut]
            extinf, url, is_alive, status, latency, drm_type = fut.result()
            
            if is_alive:
                results[idx] = (extinf, url)
                alive += 1
                latencies.append(latency)
            else:
                dead += 1
                
                # Categorize error
                if status == 0:
                    key = "Timeout/Error"
                elif latency > MAX_LATENCY_MS:
                    key = f"Slow >{MAX_LATENCY_MS}ms"
                else:
                    key = f"HTTP {status}" if status else "Error"
                
                error_counts[key] = error_counts.get(key, 0) + 1
                
                # Track special cases
                if drm_type:
                    drm_channels += 1
                if "geoblock" in (drm_type or ""):
                    geoblocked += 1
                if "placeholder" in (drm_type or ""):
                    placeholders += 1
            
            # Log progress every 500 channels
            if done % 500 == 0 or done == total:
                log.info(f"  {done}/{total} checked — {alive} valid, {dead} dead")
    
    # Filter valid results
    valid = [r for r in results if r is not None]
    
    # Calculate latency statistics
    if latencies:
        avg_latency = int(sum(latencies) / len(latencies))
        median_latency = int(statistics.median(latencies))
        sorted_lat = sorted(latencies)
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if len(sorted_lat) > 20 else sorted_lat[-1]
    else:
        avg_latency = median_latency = p95 = 0
    
    # Log error breakdown
    if error_counts:
        log.info("Dead link breakdown:")
        for err_type, count in sorted(error_counts.items(), key=lambda x: -x[1]):
            log.info(f"  {err_type}: {count}")
    
    # Log special cases
    if drm_channels > 0:
        log.info(f"DRM-protected channels (removed): {drm_channels}")
    if geoblocked > 0:
        log.info(f"Geoblocked channels (removed): {geoblocked}")
    if placeholders > 0:
        log.info(f"Placeholder URLs (removed): {placeholders}")
    
    log.info(f"Done: {len(valid)} valid / {dead} dead / "
             f"avg {avg_latency}ms median {median_latency}ms p95 {p95}ms")
    
    return valid, {
        "alive": len(valid),
        "dead": dead,
        "total": total,
        "avg_latency_ms": avg_latency,
        "median_latency_ms": median_latency,
        "p95_latency_ms": p95,
        "error_breakdown": error_counts,
        "drm_channels": drm_channels,
        "geoblocked": geoblocked,
        "placeholders": placeholders,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Deep IPTV Stream Checker")
    parser.add_argument("input", nargs="?", default="merged.m3u",
                       help="Input M3U file")
    parser.add_argument("output", nargs="?", default="merged.m3u",
                       help="Output M3U file")
    parser.add_argument("--stats-file", default="scan_stats.json",
                       help="JSON file to write scan stats")
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
    
    print(f"\n{'='*60}")
    print(f"  DEEP IPTV STREAM CHECKER RESULTS")
    print(f"{'='*60}")
    print(f"  Total channels : {stats['total']}")
    print(f"  Valid channels : {stats['alive']}")
    print(f"  Dead channels  : {stats['dead']}")
    print(f"  Avg latency    : {stats['avg_latency_ms']} ms")
    print(f"  Median latency : {stats.get('median_latency_ms', '?')} ms")
    print(f"  P95 latency    : {stats.get('p95_latency_ms', '?')} ms")
    
    if stats.get('drm_channels', 0) > 0:
        print(f"  DRM protected  : {stats['drm_channels']}")
    if stats.get('geoblocked', 0) > 0:
        print(f"  Geoblocked     : {stats['geoblocked']}")
    if stats.get('placeholders', 0) > 0:
        print(f"  Placeholders   : {stats['placeholders']}")
    
    if stats.get('error_breakdown'):
        print(f"\n  Dead breakdown:")
        for err, cnt in sorted(stats['error_breakdown'].items(), key=lambda x: -x[1]):
            print(f"    {err}: {cnt}")
    
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()