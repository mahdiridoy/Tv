#!/usr/bin/env python3
"""
merge_m3u.py
Fetches multiple M3U/M3U8 playlist sources and merges them into a single
M3U file. No dead/alive checking, no adult filtering, no logo attaching —
those are separate steps (adult_filter.py, attach_logos.py) that run on
merged.m3u afterward. This step just combines + dedupes.

Usage:
    python merge_m3u.py

Configure sources in sources2.txt (one URL per line) or edit SOURCES below.
"""

import os
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

SOURCES = [
    # "https://example.com/playlist1.m3u",
    # "https://example.com/playlist2.m3u8",
]

SOURCES_FILE = "sources2.txt"
OUTPUT_FILE = "merged.m3u"
TIMEOUT = 20  # seconds per source
USER_AGENT = "Mozilla/5.0 (compatible; M3UMerger/1.0)"


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def load_sources():
    sources = list(SOURCES)
    if os.path.isfile(SOURCES_FILE):
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    sources.append(line)
    seen = set()
    unique = []
    for s in sources:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def dedupe_sources_file():
    """Remove duplicate URLs from sources2.txt itself, preserving comments and blanks."""
    if not os.path.isfile(SOURCES_FILE):
        return
    seen = set()
    deduped_lines = []
    removed = 0
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            # Keep comments and blank lines as-is
            if not stripped or stripped.startswith("#"):
                deduped_lines.append(line)
                continue
            if stripped not in seen:
                seen.add(stripped)
                deduped_lines.append(line)
            else:
                removed += 1
                print(f"[INFO] Removing duplicate source: {stripped}")
    if removed:
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            f.writelines(deduped_lines)
        print(f"[INFO] Removed {removed} duplicate(s) from {SOURCES_FILE}")


def fetch_text(url):
    """Fetch a URL or read a local file path, return text content.
    Returns (text, error_string). error_string is None on success.
    HTTP 403/500/etc errors are caught and reported so the source can
    be auto-removed from sources2.txt."""
    try:
        if url.startswith("http://") or url.startswith("https://"):
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
        else:
            with open(url, "rb") as f:
                raw = f.read()
        return raw.decode("utf-8", errors="ignore"), None
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code}"
    except Exception as e:
        return "", str(e)


def parse_entries(text):
    """
    Parse an M3U text into a list of entry blocks.
    Each entry block is a list of lines: any #EXTINF / #EXTVLCOPT / etc.
    metadata lines followed by the stream URL line.
    """
    entries = []
    current = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            if current:
                entries.append(current)
            current = [line]
        elif line.startswith("#"):
            if current:
                current.append(line)
        else:
            if current:
                current.append(line)
                entries.append(current)
                current = []
            else:
                entries.append([f"#EXTINF:-1,Unknown", line])
    if current:
        entries.append(current)
    return entries


def dedupe_entries(entries):
    """
    Remove duplicate channel entries. Two entries are considered duplicates
    if they have the same stream URL (last line of the entry, ignoring
    query-string tokens). Keeps the first occurrence and drops the rest.
    """
    seen_urls = set()
    unique = []
    dupes = 0

    for entry in entries:
        stream_url = entry[-1].strip() if entry else ""
        norm_url = stream_url.split("?", 1)[0].rstrip("/").lower()

        if norm_url and norm_url in seen_urls:
            dupes += 1
            continue

        if norm_url:
            seen_urls.add(norm_url)
        unique.append(entry)

    if dupes:
        print(f"[INFO] Removed {dupes} duplicate channel(s) by URL")
    return unique


def main():
    # ── STEP 1: Deduplicate sources2.txt FIRST ────────────────────────────────
    print("=" * 50)
    print("  STEP 1: Deduplicating sources2.txt")
    print("=" * 50)
    dedupe_sources_file()

    sources = load_sources()
    if not sources:
        print("[ERROR] No sources configured. Add URLs to sources2.txt or SOURCES list.")
        sys.exit(1)

    print(f"[INFO] {len(sources)} unique sources ready to fetch")

    # ── STEP 2: Fetch all sources ─────────────────────────────────────────────
    print()
    print("=" * 50)
    print("  STEP 2: Fetching sources")
    print("=" * 50)
    all_entries = []
    failed_sources = []  # track sources that errored out
    for src in sources:
        print(f"[INFO] Fetching: {src}")
        text, error = fetch_text(src)
        if error:
            print(f"[WARN] REMOVING source (error: {error}): {src}", file=sys.stderr)
            failed_sources.append(src)
            continue
        if not text:
            print(f"[WARN] REMOVING source (empty response): {src}", file=sys.stderr)
            failed_sources.append(src)
            continue
        entries = parse_entries(text)
        print(f"[INFO]   -> {len(entries)} entries found")
        all_entries.extend(entries)

    # Remove failed sources from sources2.txt so they won't be retried
    if failed_sources:
        print()
        print("=" * 50)
        print("  STEP 3: Removing failed sources from sources2.txt")
        print("=" * 50)
        failed_set = set(failed_sources)
        kept_lines = []
        if os.path.isfile(SOURCES_FILE):
            with open(SOURCES_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    # Keep comments, blanks, and sources that did NOT fail
                    if not stripped or stripped.startswith("#"):
                        kept_lines.append(line)
                    elif stripped not in failed_set:
                        kept_lines.append(line)
                    else:
                        print(f"[INFO] Removed failed source: {stripped}")
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)
        print(f"[INFO] Removed {len(failed_sources)} dead source(s) from {SOURCES_FILE}")

    # ── STEP 4: Deduplicate channels ──────────────────────────────────────────
    print()
    print("=" * 50)
    print("  STEP 4: Deduplicating channels")
    print("=" * 50)
    print(f"[INFO] Total entries before deduplication: {len(all_entries)}")
    all_entries = dedupe_entries(all_entries)
    print(f"[INFO] Total entries after deduplication: {len(all_entries)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for entry in all_entries:
            for line in entry:
                f.write(line + "\n")

    print(f"[DONE] Wrote {len(all_entries)} total entries to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
