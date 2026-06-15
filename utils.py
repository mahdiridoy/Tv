import re
import time
import requests
from config import CHECK_TIMEOUT, CHECK_RETRIES


# ── URL Validation ────────────────────────────────────────────────────────────

def http_check(url: str) -> bool:
    """
    Fast HTTP reachability check — HEAD first, GET fallback.
    Retries once on connection/timeout errors before marking dead.

    Dead URL detection:
      • HTTP 4xx / 5xx status → dead
      • Connection refused / DNS failure → dead
      • Timeout (CHECK_TIMEOUT seconds) → dead
      • Redirect to a working URL → alive
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; IPTVBot/1.0)"}

    for attempt in range(1 + CHECK_RETRIES):
        try:
            # HEAD is fast — no body downloaded
            r = requests.head(
                url, timeout=CHECK_TIMEOUT,
                allow_redirects=True, headers=headers,
            )
            if r.status_code < 400:
                return True
            if r.status_code in (405, 501):
                # Server doesn't support HEAD — try a streaming GET (reads 0 bytes)
                r2 = requests.get(
                    url, timeout=CHECK_TIMEOUT,
                    stream=True, headers=headers,
                )
                r2.close()
                return r2.status_code < 400
            # 4xx/5xx that isn't a HEAD-rejection → dead, no point retrying
            return False
        except requests.exceptions.Timeout:
            if attempt < CHECK_RETRIES:
                time.sleep(0.5)
                continue
            return False
        except Exception:
            return False

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
    
