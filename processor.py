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
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    BD_KEYWORDS, INDIA_KEYWORDS, CARTOON_KEYWORDS,
    NEWS_KEYWORDS, SPORTS_KEYWORDS, MOVIES_KEYWORDS, MUSIC_KEYWORDS, FIFA_KEYWORDS,
    CATEGORY_ORDER, CATEGORY_LABELS, XTREAM_PANELS,
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
    ("FIFA",    FIFA_KEYWORDS),
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


# ── Xtream VOD / Series fetching ──────────────────────────────────────────────

def fetch_vod_and_series(panel: dict) -> list[tuple[str, str]]:
    """Fetch Movies + Series from an Xtream panel and return (extinf, url) pairs."""
    host, user, pw = panel["host"], panel["username"], panel["password"]
    pairs: list[tuple[str, str]] = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; IPTVBot/1.0)"}

    # Movies
    try:
        r = requests.get(
            f"{host}/player_api.php",
            params={"username": user, "password": pw, "action": "get_vod_streams"},
            timeout=SOURCE_TIMEOUT, headers=headers,
        )
        r.raise_for_status()
        movies = r.json()
        for item in movies:
            name = item.get("name", "Unknown")
            ext  = item.get("container_extension", "mp4")
            sid  = item.get("stream_id")
            logo = item.get("stream_icon", "")
            url  = f"{host}/movie/{user}/{pw}/{sid}.{ext}"
            extinf = f'#EXTINF:-1 tvg-logo="{logo}" group-title="VOD Movies",{name}'
            pairs.append((extinf, url))
        log.info(f"  OK    VOD movies from {host}  ({len(movies)} items)")
    except Exception as exc:
        log.warning(f"  SKIP  VOD movies {host}  ({exc})")

    # Series -> episodes (parallelized — one call per series, same worker pool as live sources)
    try:
        r = requests.get(
            f"{host}/player_api.php",
            params={"username": user, "password": pw, "action": "get_series"},
            timeout=SOURCE_TIMEOUT, headers=headers,
        )
        r.raise_for_status()
        series_list = r.json()

        def fetch_one_series(series: dict) -> list[tuple[str, str]]:
            series_id = series.get("series_id")
            out: list[tuple[str, str]] = []
            try:
                r2 = requests.get(
                    f"{host}/player_api.php",
                    params={"username": user, "password": pw,
                            "action": "get_series_info", "series_id": series_id},
                    timeout=SOURCE_TIMEOUT, headers=headers,
                )
                r2.raise_for_status()
                episodes = r2.json().get("episodes", {})
                for season_eps in episodes.values():
                    for ep in season_eps:
                        ep_id = ep.get("id")
                        ext   = ep.get("container_extension", "mp4")
                        title = f"{series.get('name', '')} - {ep.get('title', '')}"
                        logo  = series.get("cover", "")
                        url   = f"{host}/series/{user}/{pw}/{ep_id}.{ext}"
                        extinf = f'#EXTINF:-1 tvg-logo="{logo}" group-title="VOD Series",{title}'
                        out.append((extinf, url))
            except Exception as exc:
                log.warning(f"  SKIP  series {series_id}  ({exc})")
            return out

        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(fetch_one_series, s): s for s in series_list}
            for fut in as_completed(futures):
                pairs.extend(fut.result())
                done += 1
                if done % 200 == 0 or done == len(series_list):
                    log.info(f"  Series info: {done}/{len(series_list)} processed")

        log.info(f"  OK    VOD series from {host}  ({len(series_list)} series)")
    except Exception as exc:
        log.warning(f"  SKIP  VOD series {host}  ({exc})")

    return pairs


# ── VOD leakage filter ────────────────────────────────────────────────────────
# Some Xtream panels bundle movies/series into their "live" get.php M3U export.
# This detects and strips those so only real live channels stay in the live categories.

_VOD_URL_PATTERN   = re.compile(r"/(movie|series)/", re.IGNORECASE)
_VOD_EXT_PATTERN   = re.compile(r"\.(mp4|mkv|avi|mov|flv)(\?|$)", re.IGNORECASE)
_EPISODE_PATTERN   = re.compile(r"\bS\d{1,2}E\d{1,3}\b", re.IGNORECASE)          # S01E02
_SEASON_PATTERN    = re.compile(r"\bSeason\s*\d{1,2}\b", re.IGNORECASE)          # Season 1
_YEAR_TAG_PATTERN  = re.compile(r"\(\d{4}\)")                                     # (2023) — common in movie titles

def is_vod_entry(extinf: str, url: str) -> bool:
    """Return True if this entry looks like a movie/series item, not a live channel."""
    if _VOD_URL_PATTERN.search(url):
        return True
    if _VOD_EXT_PATTERN.search(url):
        return True
    attrs = parse_extinf_attrs(extinf)
    name = attrs.get("name", "")
    if _EPISODE_PATTERN.search(name) or _SEASON_PATTERN.search(name):
        return True
    if _YEAR_TAG_PATTERN.search(name):
        return True
    return False


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

    # 2. Download all live-TV M3U sources in parallel
    raw_pairs: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_source, s): s for s in sources}
        for fut in as_completed(futures):
            src_url, text = fut.result()
            if text:
                parsed = parse_m3u(text)
                raw_pairs.extend(parsed)
                log.info(f"  OK    {src_url}  ({len(parsed)} channels)")

    log.info(f"Total parsed (live sources): {len(raw_pairs)} channels")

    # 2a. Strip VOD/series entries that leaked into "live" source exports
    # (some Xtream panels bundle movies/series into their get.php M3U output)
    live_only_pairs = []
    leaked_vod_count = 0
    for extinf, url in raw_pairs:
        if is_vod_entry(extinf, url):
            leaked_vod_count += 1
        else:
            live_only_pairs.append((extinf, url))
    raw_pairs = live_only_pairs
    log.info(f"Stripped {leaked_vod_count} VOD/series entries leaked into live sources")
    log.info(f"Live channels after VOD filter: {len(raw_pairs)}")

    # 2b. Fetch VOD/series separately — these bypass HTTP validation entirely
    vod_pairs: list[tuple[str, str]] = []
    for panel in XTREAM_PANELS:
        panel_pairs = fetch_vod_and_series(panel)
        vod_pairs.extend(panel_pairs)
        log.info(f"  OK    VOD/Series {panel['host']}  ({len(panel_pairs)} items)")

    # 3. Deduplicate LIVE entries by stream URL
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for extinf, url in raw_pairs:
        if url not in seen:
            seen.add(url)
            deduped.append((extinf, url))
    log.info(f"After dedup (live): {len(deduped)} unique channels")

    # Dedup VOD/series too (cheap, no network calls)
    seen_vod: set[str] = set()
    vod_deduped: list[tuple[str, str]] = []
    for extinf, url in vod_pairs:
        if url not in seen_vod:
            seen_vod.add(url)
            vod_deduped.append((extinf, url))
    log.info(f"After dedup (VOD/series): {len(vod_deduped)} items")

    # 4. Validate ONLY live TV URLs — VOD/series skip this (avoids panel rate-limiting)
    valid_pairs = validate_urls(deduped)

    # 5. Categorise live entries into groups
    cats: dict[str, list] = {c: [] for c in CATEGORY_ORDER}
    for extinf, url in valid_pairs:
        attrs = parse_extinf_attrs(extinf)
        name  = attrs.get("name", "Unknown")
        logo  = get_logo(name, attrs.get("tvg-logo", ""))
        cat   = detect(name)
        short = clean_name(name)
        cats[cat].append((short, url, logo, CATEGORY_LABELS[cat]))

    # 5b. Categorise VOD/series entries — taken straight from group-title, no keyword detection
    for extinf, url in vod_deduped:
        attrs = parse_extinf_attrs(extinf)
        name  = attrs.get("name", "Unknown")
        logo  = attrs.get("tvg-logo", "")
        group = attrs.get("group-title", "VOD Movies")
        cat   = "vod_movies" if group == "VOD Movies" else "vod_series"
        cats[cat].append((name, url, logo, CATEGORY_LABELS[cat]))

    # 6. Write output.m3u (BD → India → Cartoon → News → Sports → Movies → Music → Other → FIFA → VOD Movies → VOD Series)
    final = [ch for c in CATEGORY_ORDER for ch in cats[c]]
    with open("output.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url, logo, group in final:
            f.write(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{name}\n')
            f.write(f"{url}\n")

    # 7. Write stats
    dead = len(deduped) - len(valid_pairs)
    with open("stats.txt", "w") as f:
        f.write(f"Total parsed (live) : {len(raw_pairs) + leaked_vod_count}\n")
        f.write(f"VOD/series leaked   : {leaked_vod_count} (stripped from live)\n")
        f.write(f"After dedup (live)  : {len(deduped)}\n")
        f.write(f"Dead removed        : {dead}\n")
        f.write(f"VOD/Series items    : {len(vod_deduped)} (unvalidated)\n")
        f.write(f"Final output        : {len(final)}\n")
        f.write("-" * 32 + "\n")
        for c in CATEGORY_ORDER:
            f.write(f"  {CATEGORY_LABELS[c]:<15}: {len(cats[c])}\n")

    log.info(f"Done — {len(final)} channels/items written to output.m3u")


if __name__ == "__main__":
    main()

