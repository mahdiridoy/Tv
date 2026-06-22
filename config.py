FIFA_KEYWORDS = ["T Sports","TSports","BBC","BBC ONE","BBC TWO","ITV","ITV1","FOX","FS1","FOX Sports","Telemundo","Universo","TUDN","Univision","TSN","CTV","RDS","SBS","TVNZ","beIN","beIN Sports","beIN MAX","beIN Sports MAX","M6","ARD","ZDF","MagentaTV","RTVE","La 1","Teledeporte","RAI","Rai 1","Rai Sport","VRT","RTBF","Sporza","Tipik","NOS","ORF","ServusTV","SRF","RTS","RSI","RTP","Globo","SporTV","CazéTV","CazeTV","SBT","N Sports","Televisa","TV Azteca","Telefe","TV Publica","TyC Sports","Caracol","RCN","Win Sports","Chilevision","America Television","SuperSport","New World TV","TRT","Match TV","CCTV5","CCTV Sports","Migu","NHK","Fuji TV","Nippon TV","DAZN","JTBC","Sony Sports","Sony Ten","PTV Sports","Arena Sport","Sport TV","Eleven Sports","Canal+","Eurosport","Premier Sports","D SPORTS","Cignal","Shomoy","BTV","Toffee","Bioscope","Sky Sports","Sky Sport","ESPN","ESPN Deportes","Gol Mundial","FUSSBALL","Sportklub","TVP Sport","Polsat Sport","Sportdigital","Viaplay","V Sport","TV2 Sport","NRK","SVT","TV4","Yle","MTV3"
               "FanCode", "FANCODE", "Sky F1", "Sky F1 DE", "Sky Sport FHD", "Sky Sport HD", "Tipik", "FIFA World Cup",
    "World Cup",
    "FIFA 2026",
    "WC 2026",
    "Football World Cup",
    "Soccer World Cup", "Unite 8 Sports 1 HD",
    "Unite 8 Sports 2 HD",
    "Somoy",
    "PTV 4K",
    "S Football",
    "TVP Sports",
]

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
MAX_WORKERS    = 200    # parallel threads for downloading & checking URLs
SOURCE_TIMEOUT = 20    # seconds to wait when fetching a source playlist
CHECK_TIMEOUT  = 8     # seconds per URL reachability check

# True  → skip per-URL check (fast, finishes in minutes, keeps dead links)
# False → HTTP HEAD/GET check each URL (filters dead links, recommended)
SKIP_URL_CHECK = False

# How many retries on connection error before marking a URL dead
CHECK_RETRIES = 1
