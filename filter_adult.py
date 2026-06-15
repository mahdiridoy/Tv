"""
Adult Content Filter
--------------------
Reads output.m3u, removes any channel whose #EXTINF line or stream URL
contains an adult keyword, then writes the cleaned playlist to ridoyiptv.m3u.
"""

import os
import re
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SOURCE_FILE = "output.m3u"
OUTPUT_FILE = "ridoyiptv.m3u"

ADULT_KEYWORDS = [
    "adult", "xxx", "porn", "sex", "erotic", "erotik", "erotique",
    "dorcel", "penthouse", "playboy", "hustler", "brazzers",
    "bangbros", "mofos", "wankz", "vixen", "blacked",
    "realitykings", "reality kings", "naughtyamerica", "naughty america",
    "xvideos", "xhamster", "pornhub", "onlyfans", "boyxx", "sextreme",
    "hentai", "nude", "naked", "milf", "fetish",
    "hardcore", "softcore", "explicit", "uncensored",
    "redlight", "red light", "taboo", "18+",
    "for adults", "adults only", "hot movies",
]

# Pre-compile one regex — much faster than looping over keywords one by one
_ADULT_RE = re.compile(
    "|".join(re.escape(k) for k in ADULT_KEYWORDS),
    re.IGNORECASE,
)


def is_adult(text: str) -> bool:
    return bool(_ADULT_RE.search(text))


def main() -> None:
    if not os.path.exists(SOURCE_FILE):
        log.error(f"{SOURCE_FILE} not found — run processor.py first")
        return

    with open(SOURCE_FILE, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    cleaned: list[str] = []
    removed = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("#EXTINF"):
            url_line = lines[i + 1] if i + 1 < len(lines) else ""

            if is_adult(line) or is_adult(url_line):
                removed += 1
                i += 2
                continue

            cleaned.append(line)
            if url_line:
                cleaned.append(url_line)
            i += 2
        else:
            cleaned.append(line)
            i += 1

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(cleaned)

    kept = sum(1 for l in cleaned if l.startswith("#EXTINF"))
    log.info(f"Removed : {removed} adult channels")
    log.info(f"Kept    : {kept} clean channels")
    log.info(f"Saved   → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
    
