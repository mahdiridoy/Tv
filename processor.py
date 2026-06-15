"""
IPTV Playlist Processor
-----------------------
• Downloads all sources in parallel  (fast)
• Parses M3U entries with full attribute support
• Deduplicates by stream URL
• Categorises into 8 groups using all keyword lists from config.py
• Writes output.m3u with group-title attribute (compatible with all players)
• Optionally validates each URL via fast HTTP check (set SKIP_URL_CHECK in config.py)

Root cause of old 6-hour timeout: ffprobe was called sequentially on every URL.
Fix: replaced with optional parallel HTTP HEAD check (milliseconds per URL).
"""

import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    BD_KEYWORDS, INDIA_KEYWORDS, CARTOON_KEYWORDS,
    NEWS_KEYWORDS, SPORTS_KEYWORDS, MOVIES_KEYWORDS, MUSIC_KEYWORDS,
    CATEGORY_ORDER, CATEGORY_LABELS,
    MAX_WORKERS, SOURCE_TIMEOUT, SKIP_URL_CHECK, CHECK_RETRIES,
)
from logos import LOGO_DB, DEFAULT_LOGO
from utils import clean_name, parse_extinf_attrs, http_check

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Logo lookup ───────────────────────────────────────────────────────────────

def get_logo(name: str, embedded: str = "") -> str:
    """Use embedded tvg-logo if present, otherwise look up in LOGO_DB."""
    if embedded and embedded.startswith("http"):
        return embedded
    low = name.lower()
    for key, url in LOGO_DB.items():
        if key in low:
            return url
    return DEFAULT_LOGO


# ── Categorisation ────────────────────────────────────────────────────────────

_DETECT_ORDER = [
    ("bd",      BD_KEYWORDS),
    ("cartoon", CARTOON_KEYWORDS),
    ("news",    NEWS_KEYWORDS),
    ("sports",  SPORTS_KEYWORDS),
    ("movies",  MOVIES_KEYWORDS),
    ("music",   MUSIC_KEYWORDS),
    ("india",   INDIA_KEYWORDS),
]


def detect(name: str) -> str:
    """Return the category key for a channel name."""
    low = name.lower()
    for cat, keywords in _DETECT_ORDER:
        if any(k.lower() in low for k in keywords):
            return cat
    return "other"


# ── Source downloading ────────────────────────────────────────────────────────

def fetch_source(url: str) -> tuple[str, str | None]:
    """Download one playlist URL. Returns (url, text) or (url, None) on failure."""
    try:
        r = requests.get(
            url, timeout=SOURCE_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; IPTVBot/1.0)"},
        )
        r.raise_for_status()
        return url, r.text
    except Exception as exc:
        log.warning(f"  SKIP  {url}  ({exc})")
        return url, None


# ── M3U parsing ───────────────────────────────────────────────────────────────

def parse_m3u(text: str) -> list[tuple[str, str]]:
    """
    Parse M3U text into a list of (extinf_line, stream_url) pairs.

    Handles:
    • Blank lines between EXTINF and URL
    • Comment lines between EXTINF and URL
    • EXTINF lines with any number of attributes
    """
    lines = text.splitlines()
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            # Scan forward past blank / comment lines to find the stream URL
            j = i + 1
            while j < len(lines) and (
                not lines[j].strip() or lines[j].strip().startswith("#")
            ):
                j += 1
            if j < len(lines):
                url = lines[j].strip()
                if url.startswith("http"):
                    out.append((line, url))
            i = j + 1
        else:
            i += 1
    return out


# ── Optional URL validation ───────────────────────────────────────────────────

def validate_urls(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Filter dead URLs using parallel HTTP HEAD/GET checks.
    Skipped when SKIP_URL_CHECK = True.
    """
    if SKIP_URL_CHECK:
        log.info(f"URL validation skipped — keeping all {len(pairs)} entries (dead links NOT removed)")
        return pairs

    log.info(
        f"Validating {len(pairs)} URLs  "
        f"[workers={MAX_WORKERS}, timeout={__import__('config').CHECK_TIMEOUT}s, retries={CHECK_RETRIES}]…"
    )
    valid:  list[tuple[str, str]] = []
    dead_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_map = {ex.submit(http_check, url): (extinf, url) for extinf, url in pairs}
        done = 0
        for fut in as_completed(future_map):
            done += 1
            extinf, url = future_map[fut]
            if fut.result():
                valid.append((extinf, url))
            else:
                dead_count += 1
                log.debug(f"  DEAD  {url}")
            if done % 100 == 0 or done == len(pairs):
                log.info(
                    f"  {done}/{len(pairs)} checked — "
                    f"{len(valid)} live, {dead_count} dead"
                )

    log.info(
        f"Validation done: {len(valid)} live / {dead_count} dead "
        f"({dead_count * 100 // len(pairs)}% removed)"
    )
    return valid


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # 1. Load sources — deduplicate in-place (preserving order)
    with open("sources.txt") as f:
        sources = list(dict.fromkeys(x.strip() for x in f if x.strip()))
    log.info(f"Loaded {len(sources)} unique sources")

    # 2. Download all sources in parallel
    raw_pairs: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_source, s): s for s in sources}
        for fut in as_completed(futures):
            src_url, text = fut.result()
            if text:
                parsed = parse_m3u(text)
                raw_pairs.extend(parsed)
                log.info(f"  OK    {src_url}  ({len(parsed)} channels)")

    log.info(f"Total parsed: {len(raw_pairs)} channels")

    # 3. Deduplicate by stream URL
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for extinf, url in raw_pairs:
        if url not in seen:
            seen.add(url)
            deduped.append((extinf, url))
    log.info(f"After dedup: {len(deduped)} unique channels")

    # 4. Optional URL validation
    valid_pairs = validate_urls(deduped)

    # 5. Categorise into 8 groups
    cats: dict[str, list] = {c: [] for c in CATEGORY_ORDER}
    for extinf, url in valid_pairs:
        attrs = parse_extinf_attrs(extinf)
        name  = attrs.get("name", "Unknown")
        logo  = get_logo(name, attrs.get("tvg-logo", ""))
        cat   = detect(name)
        short = clean_name(name)
        cats[cat].append((short, url, logo, CATEGORY_LABELS[cat]))

    # 6. Write output.m3u (BD → India → Cartoon → News → Sports → Movies → Music → Other)
    final = [ch for c in CATEGORY_ORDER for ch in cats[c]]
    with open("output.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url, logo, group in final:
            f.write(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{name}\n')
            f.write(f"{url}\n")

    # 7. Write stats
    dead = len(deduped) - len(valid_pairs)
    with open("stats.txt", "w") as f:
        f.write(f"Total parsed : {len(raw_pairs)}\n")
        f.write(f"After dedup  : {len(deduped)}\n")
        f.write(f"Dead removed : {dead}\n")
        f.write(f"Final output : {len(final)}\n")
        f.write("-" * 32 + "\n")
        for c in CATEGORY_ORDER:
            f.write(f"  {CATEGORY_LABELS[c]:<15}: {len(cats[c])}\n")

    log.info(f"Done — {len(final)} channels written to output.m3u")


if __name__ == "__main__":
    main()

