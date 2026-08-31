"""
order_m3u.py
------------
Arranges merged.m3u (output of the no-scan pipeline) in the exact order of
the CHANNEL_ORDER keyword list in config.py, assigns each channel a
PERMANENT tvg-chno number (slot N -> channel N), and removes group-title
attributes (categories/groups are gone). Channels matching no keyword are
appended after the whole list with continuing numbers -- never dropped.

This is the ordering step for the no-scan pipeline (run2.bat / GitHub
Actions). Run it AFTER attach_logos.py, on the final merged.m3u:
    python order_m3u.py
"""

import logging
import os
import re

from config import CHANNEL_ORDER
from utils import clean_name, parse_extinf_attrs
from processor import order_rank

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SOURCE_FILE = "merged.m3u"
OUTPUT_FILE = "merged.m3u"

_ATTR_DROP = {"group-title"}


def parse_entries(lines):
    """
    Split merged.m3u lines into (extinf, metadata_lines, url) blocks, the same
    way merge_m3u.py builds them: an #EXTINF line starts a block, following
    '#'-comment lines are metadata, the first non-'#' line is the stream URL.
    """
    entries = []
    current = None  # (extinf, [meta])
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            if current:
                entries.append((current[0], current[1], None))
            current = [line, []]
        elif line.startswith("#"):
            if current:
                current[1].append(line)
        else:
            if current:
                current.append(line)
                entries.append((current[0], current[1], current[2]))
                current = None
            else:
                entries.append(("#EXTINF:-1,Unknown", [], line))
    if current:
        entries.append((current[0], current[1], None))
    return entries


def rebuild_extinf(extinf: str, chno: int) -> str:
    """Rewrite an #EXTINF line: keep all attributes except group-title,
    force tvg-chno, preserve the display name after the comma."""
    attrs = parse_extinf_attrs(extinf)
    name = attrs.pop("name", "Unknown")
    attrs.pop("group-title", None)
    attrs["tvg-chno"] = str(chno)
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    if attr_str:
        return f"#EXTINF:-1 {attr_str},{name}"
    return f"#EXTINF:-1,{name}"


def main() -> None:
    if not os.path.exists(SOURCE_FILE):
        log.error(f"{SOURCE_FILE} not found - run merge_m3u.py first")
        return

    with open(SOURCE_FILE, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    entries = parse_entries(lines)

    # Order by CHANNEL_ORDER; assign PERMANENT tvg-chno from the slot.
    listed: dict[int, list] = {}
    unlisted: list = []
    dropped = 0
    for extinf, meta, url in entries:
        if not url:
            dropped += 1  # #EXTINF with no URL line - never a real channel
            continue
        name = parse_extinf_attrs(extinf).get("name", "Unknown")
        short = clean_name(name)
        rank = order_rank(short)
        block = (extinf, meta, url)
        if rank is not None:
            listed.setdefault(rank, []).append(block)
        else:
            unlisted.append(block)

    final = []
    for rank in range(len(CHANNEL_ORDER)):
        for extinf, meta, url in listed.get(rank, []):
            final.append((rank + 1, extinf, meta, url))
    for i, (extinf, meta, url) in enumerate(unlisted, start=1):
        final.append((len(CHANNEL_ORDER) + i, extinf, meta, url))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for chno, extinf, meta, url in final:
            f.write(rebuild_extinf(extinf, chno) + "\n")
            for m in meta:
                f.write(m + "\n")
            f.write(url + "\n")

    listed_count = sum(len(v) for v in listed.values())
    log.info(f"Ordered : {len(final)} channels ({listed_count} listed, {len(unlisted)} appended, {dropped} skipped)")
    log.info(f"Saved   -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()