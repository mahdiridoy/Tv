"""
attach_logos.py
----------------
Reads merged.m3u (already merged + adult-filtered), attaches a tvg-logo
to each channel using logos.py.

MATCHING RULE — whole-word containment, not full-name equality:
A LOGO_DB key matches a channel if the key's words appear as a whole,
in-order word sequence somewhere in the channel name. So:

    key "Deepto"  matches  "Deepto", "Deepto TV", "BD:DEEPTO TV",
                           "BD: Deepto", "|BANGLA| DEEPTO TV HD", ...

But it will NOT match on a single shared word inside a longer key:

    key "ATN Bangla"  does NOT match  "Bangla TV"
    (that channel only shares the word "Bangla" — "atn" is missing,
     so the full key phrase never appears in it)

If a channel could match more than one key (e.g. both "ATN" and
"ATN News" are in LOGO_DB), the LONGEST/most specific key wins — so
"ATN News (1080p)" gets the "ATN News" logo, not the plain "ATN" one.

Channels with no match keep whatever tvg-logo they already had.
Overwrites merged.m3u with the result.
"""

import re
import logging

from logos import LOGO_DB, DEFAULT_LOGO

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase and split into word tokens, dropping punctuation/symbols
    like ':', '|', '[', ']', '-', '(', ')' entirely (they're just decoration
    in these channel names, not part of the actual word match)."""
    return _WORD_RE.findall(text.lower())


# Pre-tokenize every LOGO_DB key once, keeping original key + longest-first
# order so a longer/more specific key is checked/preferred over a shorter one.
_LOGO_ENTRIES = sorted(
    (
        (_tokenize(key), url, key)
        for key, url in LOGO_DB.items()
        if _tokenize(key)
    ),
    key=lambda entry: len(entry[0]),
    reverse=True,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SOURCE_FILE = "merged.m3u"
OUTPUT_FILE = "merged.m3u"

# Set True to fall back to DEFAULT_LOGO when a channel has no hard match
# AND no embedded tvg-logo already. Off by default.
USE_DEFAULT_LOGO_FALLBACK = False

_EXTINF_RE = re.compile(
    r'^#EXTINF:(?P<duration>-?\d+(?:\.\d+)?)(?P<attrs>(?:\s+[\w-]+="[^"]*")*)\s*,(?P<name>.*)$'
)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def parse_extinf(line):
    """Return (duration, attrs_dict, name) from an #EXTINF line, or None if unparsable."""
    m = _EXTINF_RE.match(line.strip())
    if not m:
        return None
    duration = m.group("duration")
    attrs = dict(_ATTR_RE.findall(m.group("attrs") or ""))
    name = m.group("name").strip()
    return duration, attrs, name


def build_extinf(duration, attrs, name):
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    if attr_str:
        return f"#EXTINF:{duration} {attr_str},{name}\n"
    return f"#EXTINF:{duration},{name}\n"


def _contains_sequence(name_tokens: list[str], key_tokens: list[str]) -> bool:
    """True if key_tokens appears as a contiguous, in-order run inside
    name_tokens — e.g. ["deepto"] inside ["bd", "deepto", "tv"], or
    ["atn", "news"] inside ["atn", "news", "1080p"]."""
    n, k = len(name_tokens), len(key_tokens)
    if k == 0 or k > n:
        return False
    return any(name_tokens[i:i + k] == key_tokens for i in range(n - k + 1))


def hard_match_logo(name: str):
    """Return the logo for the longest LOGO_DB key whose words appear as a
    whole, in-order sequence inside `name`. Longest match wins so a more
    specific key (e.g. "ATN News") beats a shorter one ("ATN") when both
    would otherwise match. Returns None if nothing matches."""
    name_tokens = _tokenize(name)
    for key_tokens, url, _key in _LOGO_ENTRIES:  # already longest-first
        if _contains_sequence(name_tokens, key_tokens):
            return url
    return None


def main() -> None:
    import os
    if not os.path.exists(SOURCE_FILE):
        log.error(f"{SOURCE_FILE} not found — run merge_m3u.py first")
        return

    with open(SOURCE_FILE, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    out_lines: list[str] = []
    attached = 0

    for line in lines:
        if line.startswith("#EXTINF"):
            parsed = parse_extinf(line)
            if parsed:
                duration, attrs, name = parsed
                before = attrs.get("tvg-logo")
                matched = hard_match_logo(name)
                if matched:
                    attrs["tvg-logo"] = matched
                elif USE_DEFAULT_LOGO_FALLBACK and not attrs.get("tvg-logo"):
                    attrs["tvg-logo"] = DEFAULT_LOGO
                if attrs.get("tvg-logo") != before:
                    attached += 1
                out_lines.append(build_extinf(duration, attrs, name))
                continue
        out_lines.append(line)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(out_lines)

    log.info(f"Attached : {attached} hard-matched logo(s)")
    log.info(f"Saved    -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
