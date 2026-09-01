import re
import time
import requests
from requests.adapters import HTTPAdapter

HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36","Accept":"*/*","Accept-Language":"en-US,en;q=0.9","Connection":"keep-alive"}
# Plain requests session — NO retries, NO cloudscraper
session = requests.Session()
session.headers.update(HEADERS)
adapter = HTTPAdapter(max_retries=0)
session.mount("http://", adapter)
session.mount("https://", adapter)

from urllib.parse import urljoin
from config import CHECK_TIMEOUT, CHECK_RETRIES, MIN_THROUGHPUT_KBPS, READ_WINDOW

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IPTVBot/1.0)"}
_MAX_MANIFEST_DEPTH = 2  # master playlist → variant playlist → media segment


# ── URL Validation ────────────────────────────────────────────────────────────

def _first_media_uri(manifest_text: str, base_url: str) -> str | None:
    """
    Given HLS manifest text, return the absolute URL of the next thing to
    fetch: for a master playlist, the first variant's playlist URI; for a
    variant/media playlist, the first actual segment URI.
    """
    lines = [ln.strip() for ln in manifest_text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for nxt in lines[i + 1:]:
                if not nxt.startswith("#"):
                    return urljoin(base_url, nxt)
        elif not line.startswith("#"):
            return urljoin(base_url, line)  # first segment URI in a media playlist
    return None


_MANIFEST_SNIFF_CAP = 20000  # bytes — enough to hold even a large manifest's text


def _raw_read(r, n: int) -> bytes:
    """Read up to n raw bytes from an open streaming response, decoding
    any transfer/content encoding so what we see matches what a normal
    body read would give."""
    return r.raw.read(n, decode_content=True)


def _classify_and_check(r, overall_start: float):
    """
    Classifies and (if it's real media) health-checks an already-open
    streaming response — by sniffing the actual first bytes, never by
    trusting Content-Type or the URL's file extension.

    This matters because many IPTV panels (Xtream-Codes-style links
    especially) serve real .m3u8 playlist TEXT from URLs with no .m3u8
    suffix and inconsistent/missing Content-Type headers — e.g.
    http://server:port/user/pass/12345. The old header/extension check
    misclassified those as "direct media", measured how fast the tiny
    playlist text itself downloaded (always instantly), and reported the
    channel healthy WITHOUT EVER REACHING THE REAL VIDEO SEGMENTS. That's
    the gap that let dead channels through undetected. Sniffing the body
    for a literal "#EXTM3U" header closes it regardless of headers/URL.

    Returns one of:
      ("manifest", next_url)            — it's a playlist, descend further
      ("manifest_fail", reason)         — claims/looks like a playlist but is empty/malformed
      ("result", (alive, latency, reason)) — final health verdict on real media
    """
    r.raw.decode_content = True
    first_chunk = _raw_read(r, 4096)
    first_byte_time = time.perf_counter()

    if not first_chunk:
        return "result", (False, None, "dead:empty-response")

    if first_chunk.lstrip()[:7] == b"#EXTM3U":
        # Confirmed real manifest by sniffing content — regardless of
        # what the headers or URL claimed.
        body = bytearray(first_chunk)
        while len(body) < _MANIFEST_SNIFF_CAP:
            more = _raw_read(r, 4096)
            if not more:
                break
            body += more
        text = body.decode("utf-8", errors="ignore")
        nxt = _first_media_uri(text, r.url)
        if not nxt:
            return "manifest_fail", "dead:empty-manifest"
        return "manifest", nxt

    # Not a manifest — this is real media. Keep reading to measure sustained
    # throughput; a channel only counts healthy if it delivers data
    # continuously above MIN_THROUGHPUT_KBPS, not just a first byte.
    total_bytes = len(first_chunk)
    read_start = time.perf_counter()
    while True:
        if (time.perf_counter() - read_start >= READ_WINDOW
                or time.perf_counter() - overall_start >= CHECK_TIMEOUT):
            break
        chunk = _raw_read(r, 8192)
        if not chunk:
            break
        total_bytes += len(chunk)

    read_elapsed = max(time.perf_counter() - read_start, 0.05)
    throughput_kbps = (total_bytes / 1024) / read_elapsed

    if throughput_kbps < MIN_THROUGHPUT_KBPS:
        return "result", (False, None, f"buffering:{throughput_kbps:.0f}kbps")

    latency = first_byte_time - overall_start
    return "result", (True, latency, "ok")


def check_stream(url: str) -> tuple[bool, float | None, str]:
    """
    Hard check — ONE shot, no retries. Any error = dead immediately.

    Pipeline: HTTP status → content sniff → manifest follow → sustained read.
    403/404/500/timeout/connection error → dead, no second chance.
    """
    overall_start = time.perf_counter()
    try:
        current_url = url
        for depth in range(_MAX_MANIFEST_DEPTH + 1):
            with session.get(
                current_url, timeout=(CHECK_TIMEOUT, CHECK_TIMEOUT),
                stream=True, allow_redirects=True,
            ) as r:
                if r.status_code >= 400:
                    return False, None, f"dead:status-{r.status_code}"

                kind, payload = _classify_and_check(r, overall_start)
                if kind == "manifest":
                    current_url = payload
                    continue
                elif kind == "manifest_fail":
                    return False, None, payload
                else:
                    alive, latency, reason = payload
                    return alive, latency, reason

        return False, None, "dead:depth-exceeded"

    except requests.exceptions.Timeout:
        return False, None, "dead:timeout"
    except Exception as exc:
        return False, None, f"dead:error-{type(exc).__name__}"


# Backward-compatible wrapper (kept in case anything else still imports http_check)
def http_check(url: str) -> bool:
    alive, _, _ = check_stream(url)
    return alive


# ── M3U Parsing Helpers ───────────────────────────────────────────────────────

_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_NAME_RE = re.compile(r',(.+)$')


def parse_extinf_attrs(line: str) -> dict:
    """
    Parse a full #EXTINF line into a dict.

    Example line:
        #EXTINF:-1 tvg-id="btv.bd" tvg-name="BTV" tvg-logo="https://..." group-title="BD",BTV

    Returns:
        {
          "tvg-id":      "btv.bd",
          "tvg-name":    "BTV",
          "tvg-logo":    "https://...",
          "group-title": "BD",
          "name":        "BTV",       ← display name after the comma
        }
    """
    attrs = dict(_ATTR_RE.findall(line))
    # The display name is everything after the comma that FOLLOWS the last
    # quoted attribute. A naive first-comma split breaks when an attribute
    # value (e.g. a tvg-logo URL) itself contains commas, so we skip past
    # the end of the last `key="value"` pair before looking for the comma.
    last_attr_end = max(
        (m.end() for m in _ATTR_RE.finditer(line)),
        default=0,
    )
    m = _NAME_RE.search(line, last_attr_end)
    # Prefer the display name after the comma; fall back to tvg-name attribute
    attrs["name"] = (m.group(1).strip() if m else "") or attrs.get("tvg-name", "Unknown")
    return attrs


def clean_name(name: str) -> str:
    """
    Normalise a channel display name:
      • Remove ' | HD' / ' | FHD' style suffixes
      • Remove standalone quality tags (FHD, 4K, UHD, SD)
      • Collapse multiple spaces
    """
    name = re.sub(r'\s*\|.*$', '', name)                          # strip " | anything"
    name = re.sub(r'\b(FHD|4K|UHD|SD)\b', '', name, flags=re.I)  # quality words
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


# ── Channel Ordering ─────────────────────────────────────────────────────────

from config import CHANNEL_ORDER


def _kw_pattern(kw: str) -> re.Pattern:
    """Word-boundary-safe regex for keyword matching."""
    left  = r"\b" if kw[0].isalnum()  else ""
    right = r"\b" if kw[-1].isalnum() else ""
    return re.compile(left + re.escape(kw) + right, re.IGNORECASE)


_ORDER_PATTERNS = [_kw_pattern(kw) for kw in CHANNEL_ORDER]


def order_rank(name: str) -> int | None:
    """Return the index of the first CHANNEL_ORDER keyword matching the name,
    or None if no keyword matches."""
    for i, pattern in enumerate(_ORDER_PATTERNS):
        if pattern.search(name):
            return i
    return None
    
