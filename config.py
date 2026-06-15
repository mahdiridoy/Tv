BD_KEYWORDS = [
    "BTV", "ATN", "Channel i", "Jamuna", "Somoy", "Ekattor",
    "NTV", "Bangla", "Boishakhi", "Desh", "Gazi", "DBC", "Mytv",
    "SA TV", "RTV", "Maasranga", "Shomoy", "Independent TV",
    "News24", "Channel 24", "Mohona", "Bijoy",
]

INDIA_KEYWORDS = [
    "Star Plus", "Star Jalsha", "Zee", "Sony", "Colors",
    "Sun TV", "Sony SAB", "DD National", "Sony Ten", "Aaj Tak",
    "Republic", "India TV", "Zee News", "NDTV", "TV9", "ABP",
    "Star Vijay", "Asianet", "Maa TV", "Gemini",
]

CARTOON_KEYWORDS = [
    "Cartoon Network", "Nick", "Nickelodeon", "Disney",
    "Pogo", "Hungama", "BabyTV", "Toon", "CBeebies", "Baby", "Kids",
]

NEWS_KEYWORDS = [
    "News", "Samachar", "Khobor", "BBC", "CNN", "Al Jazeera",
    "CNBC", "Bloomberg", "Sky News", "France 24", "DW", "Euronews",
]

SPORTS_KEYWORDS = [
    "Sport", "ESPN", "Star Sports", "Sony Six", "Ten Sports",
    "Willow", "DSport", "Cricket", "Football", "FIFA", "Sky Sports",
    "BT Sport", "Sony LIV Sports",
]

MOVIES_KEYWORDS = [
    "Movies", "Cinema", "Film", "Zee Cinema", "Star Gold",
    "Sony Max", "B4U", "Action", "Thriller", "Romedy", "&Pictures",
]

MUSIC_KEYWORDS = [
    "Music", "MTV", "VH1", "Channel V", "Zing", "9X Jalwa",
    "Hits", "Beats", "Radio",
]

# Category display names & priority order
CATEGORY_ORDER = ["bd", "india", "cartoon", "news", "sports", "movies", "music", "other"]

CATEGORY_LABELS = {
    "bd":      "Bangladesh",
    "india":   "India",
    "cartoon": "Kids & Cartoon",
    "news":    "News",
    "sports":  "Sports",
    "movies":  "Movies",
    "music":   "Music",
    "other":   "Other",
}

# ── Performance tuning ────────────────────────────────────────────────────────
MAX_WORKERS    = 20    # parallel threads for downloading sources
SOURCE_TIMEOUT = 20    # seconds to wait when fetching a source playlist
CHECK_TIMEOUT  = 5     # seconds per URL reachability check

# True  → skip per-URL check (fast, finishes in minutes)
# False → HTTP HEAD check each URL (filters dead links, ~10–20 min with 20 workers)
SKIP_URL_CHECK = True
