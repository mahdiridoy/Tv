# ── Channel ordering ─────────────────────────────────────────────────────────
# The "category list": the final playlist is arranged EXACTLY in the order of
# this list, top to bottom. Each entry is a keyword, matched as a whole word
# or phrase (case-insensitive) against the channel name — so "ATN" catches
# every ATN* channel (ATN Bangla, ATN News, ATN Music, ATN Bangla UK, ...),
# "Channel i" catches Channel I / Channel I UK / etc.
#
# A channel is placed under the FIRST keyword in this list that matches it.
# If a channel matches more than one keyword (e.g. "ATN Bangla" matches both
# "ATN" and "Bangla"), it goes under the EARLIER one.
#
# Channels that match NONE of these keywords are NOT dropped — they are simply
# appended after all listed channels (fastest-first), so no channel is missed.
#
# PERMANENT CHANNEL NUMBERS: every channel that matches the Nth keyword in
# this list (1-based) is permanently assigned channel number N. This number
# never changes between runs — it's tied to this list, not to which channels
# happened to survive. If you insert a new keyword, all channels after it get
# renumbered; if you only edit the ORDER of two keywords, their numbers swap.
# Channels matching no keyword keep getting numbers after the whole list.
CHANNEL_ORDER = [
    "BTV",
    "ATN",
    "Channel i",
    "Jamuna",
    "Somoy",
    "Ekattor",
    "NTV",
    "Boishakhi",
    "Desh",
    "Gazi",
    "DBC",
    "MyTV",
    "SA TV",
    "RTV",
    "Maasranga",
    "Shomoy",
    "Independent TV",
    "News24",
    "Channel 24",
    "Mohona",
    "Bijoy",
    "Bangladesh Television",
    "Bangladesh Parliament Television",
    "BanglaVision",
    "Asian TV",
    "Duronto TV",
    "Ananda TV",
    "Deepto TV",
    "Nagorik TV",
    "Bangla TV",
    "Global TV",
    "Channel S",
    "Green TV",
    "Ruposhi Bangla",
    "Movie Bangla",
    "Music Bangla",
    "Bangla Plus",
    "Channel 9",

    # ── India ─────────────────────────────────────────────────────────────
    "Star",
    "Zee",
    "Sony",
    "Colors",
    "Republic",
    "Sun",
    "DD",
    "Aaj Tak",
    "India TV",
    "NDTV",
    "TV9",
    "ABP",
    "Asianet",
    "Maa",
    "&TV",
    "Dangal",
    "Big Magic",
    "Sansad",
    "News18",
    "Times Now",
    "News Nation",
    "CNBC",
    "ET Now",
    "Sports18",
    "Eurosport",
    "B4U",
    "UTV",
    "Movies Now",
    "MNX",
    "Romedy Now",
    "9XM",
    "9X",
    "Zing",
    "MTV",
    "VH1",
    "Music India",
    "Cartoon Network",
    "Pogo",
    "Discovery",
    "Nick",
    "Disney",
    "Hungama",
    "History",
    "Animal Planet",
    "National Geographic",
    "Nat Geo",
    "Travel XP",
    "Food Food",
    "Aastha",
    "Sanskar",
    "Sadhna",
    "Vedic",
    "KTV",
    "Kalaignar",
    "Jaya",
    "Raj",
    "Vijay",
    "Adithya",
    "Gemini",
    "ETV",
    "Surya",
    "Flowers",
    "Manorama",
    "Mathrubhumi",
    "Udaya",
    "Public TV",
    "Suvarna",
    "Power",
    "Majha",
    "PTC",
    "Chardikla",
    "Tarang",
    "Kanak",
    "OTV",
    "Kalinga",
    "Prameya",
    "TV5",
    "V6",
    "N TV",
    "10TV",
    "Sakshi",
    "ABN",
    "Studio N",
    "Zee Bangla",
    "Colors Bangla",
    "Sun Bangla",
    "ABP Ananda",
    "News18 Bangla",
    "Republic Bangla",
    "TV9 Bangla",
    "Zee 24 Ghanta",
    "24 Ghanta",
    "Kolkata TV",
    "Sandesh",
    "Sandesh News",

    # ── Generic "Bangla" (kept LAST) ──────────────────────────────────────
    # The bare word "Bangla" is intentionally placed AFTER every Indian
    # brand keyword. Indian Bangla channels (Zee Bangla, Colors Bangla, Sun
    # Bangla, TV9 Bangla, News18 Bangla, Republic Bangla, ...) therefore
    # match their Indian brand first and stay out of the Bangladesh section.
    # Only channels that contain "Bangla" and no earlier keyword (e.g. a
    # generic "Bangla News") fall through to here.
    "Bangla",

    # ── Sports (shared) ────────────────────────────────────────────────────
    "T Sports",
    "ESPN",
]

# ── Performance tuning ────────────────────────────────────────────────────────
MAX_WORKERS    = 200    # parallel threads for downloading & checking URLs (lowered further —
                        # each check can now make up to 3 requests and read real media bytes)
SOURCE_TIMEOUT = 120    # seconds to wait when fetching a source playlist (raised for large Xtream panels)
CHECK_TIMEOUT  = 3      # max seconds for the ENTIRE check per channel (all manifest hops +
                        # the sustained-read window together). Lowered from 5s — most dead
                        # links respond within 1-2s; 3s is plenty for alive ones.

# True  → skip per-URL check (fast, finishes in minutes, keeps dead links)
# False → real GET + content-validated + sustained-throughput check (recommended)
SKIP_URL_CHECK = False

# How many retries on timeout before marking a URL dead (4xx/5xx are never retried)
# Set to 0 = hard check, one shot, no retries (fastest)
CHECK_RETRIES = 0

# How long (seconds) to keep reading actual media bytes to measure real
# throughput, once a segment/direct stream is found. Short enough to keep
# total run time reasonable across hundreds of channels, long enough to
# catch a stream that starts fine then stalls.
READ_WINDOW = 2.0

# Minimum sustained throughput (KB/s) required during READ_WINDOW for a
# channel to count as healthy. Below this, the stream is trickling data —
# which is what buffering looks like on the wire — and gets removed just
# like a dead channel. ~50 KB/s (~400 kbps) is a conservative floor below
# which most players will visibly stutter; raise it if clients still report
# buffering, lower it if too many legitimately slow-but-watchable channels
# are being dropped.
MIN_THROUGHPUT_KBPS = 50

# Channels that respond within this many seconds are kept. Anything alive but
# slower than this — likely to buffer in a player — is now REMOVED entirely,
# same as a dead channel. Only fast, working channels survive into output.m3u,
# sorted fastest → slowest by latency.
BUFFER_THRESHOLD = 2.0

# ── Reliability ───────────────────────────────────────────────────────────────
# Retries for a SOURCE playlist download (not a channel check) — a source
# timing out once shouldn't lose every channel it provides for the whole run.
SOURCE_RETRIES = 1
SOURCE_RETRY_BACKOFF = 2  # seconds, doubles each retry (3s, 6s, ...)

# Safety net: if this run's final channel count collapses relative to the
# PREVIOUS output.m3u (e.g. every source failed, or the check was somehow
# too strict this run), don't overwrite a working playlist with a broken
# one — keep the last good file and report the failure instead.
MIN_OUTPUT_RATIO = 0.5      # new run must keep at least 50% of the previous channel count
MIN_OUTPUT_CHANNELS = 20    # ...and never fewer than this many, regardless of ratio