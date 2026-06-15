import re
import requests
from config import CHECK_TIMEOUT


# ── URL Validation ────────────────────────────────────────────────────────────

def http_check(url: str) -> bool:
    """
    Fast HTTP reachability check — HEAD first, GET fallback.
    Replaces the old ffprobe/ffmpeg approach which caused 6-hour timeouts.
    A HEAD request takes <1s vs ffprobe which downloads stream data.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; IPTVBot/1.0)"}
    try:
        r = requests.head(url, timeout=CHECK_TIMEOUT, allow_redirects=True, headers=headers)
        if r.status_code < 400:
            return True
        # Some HLS endpoints refuse HEAD; fall back to a minimal GET
        r = requests.get(url, timeout=CHECK_TIMEOUT, stream=True, headers=headers)
        r.close()
        return r.status_code < 400
    except Exception:
        return False


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
    m = _NAME_RE.search(line)
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
    
