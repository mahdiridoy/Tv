# IPTV M3U Bot — Pulse Stream TV Auto Engine

Automated IPTV playlist generator that fetches, merges, filters, validates, and publishes a live M3U playlist every 5 hours via GitHub Actions.

The final output (`ridoyiptv.m3u`) is pushed to the repo and a Telegram notification is sent on every successful run.

---

## How It Works — 5-Step Pipeline

The GitHub Actions workflow (`auto.yml`) runs these scripts in order on every scheduled trigger:

| Step | Script | What it does |
|------|--------|-------------|
| 1 | `merge_m3u.py` | Fetches all sources from `sources2.txt`, merges them into a single `merged.m3u`, and deduplicates by URL |
| 2 | `adult_filter.py` | Scans every `#EXTINF` line and URL for adult keywords — removes matching channels from `merged.m3u` |
| 3 | `attach_logos.py` | Matches channel names against the logo database (`logos.py`) and attaches `tvg-logo` attributes |
| 4 | `order_m3u.py` | Sorts channels into the exact order defined in `config.py` `CHANNEL_ORDER` and assigns permanent `tvg-chno` numbers |
| 5 | `scan_valid.py` | Triple-checks every stream URL (HTTP status + real data + latency < 3s, verified 3 times) — removes dead/slow channels |

After all 5 steps, `merged.m3u` is copied to `ridoyiptv.m3u` with a generation timestamp prepended, then committed and pushed.

---

## Configuration

### `sources2.txt`
One M3U/M3U8 URL per line. Lines starting with `#` are comments. Failed sources are automatically removed on each run.

### `config.py`
- **`CHANNEL_ORDER`** — Keyword list that controls the final channel ordering and permanent channel numbers
- **Performance tuning** — `MAX_WORKERS`, timeouts, retry settings, throughput thresholds

### `logos.py`
Logo database mapping channel name keywords to image URLs. Used by `attach_logos.py` to add `tvg-logo` attributes.

---

## GitHub Actions

The workflow runs **every 5 hours** (`0 */5 * * *`) and can also be triggered manually via `workflow_dispatch`.

### Required Secrets

Set these in your repository **Settings → Secrets and variables → Actions**:

| Secret | Purpose |
|--------|---------|
| `GH_PAT` | GitHub Personal Access Token — used to push commits (triggers `notify.yml` which sends Telegram alerts) |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token for notifications |
| `TELEGRAM_CHAT_ID` | Telegram chat/group ID to receive update messages |

### Optional Secrets

| Secret | Purpose |
|--------|---------|
| `TELEGRAM_CHANNEL` | Telegram channel username (defaults to `@liveapkpulse`) |

### Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `auto.yml` | Cron (every 5h) / Manual | Runs the full 5-step pipeline and pushes the result |
| `notify.yml` | Push to `main` (when `ridoyiptv.m3u` or `mahdi_iptv.m3u8` changes) | Deduplicates `mahdi_iptv.m3u8` and sends Telegram notification |

---

## Project Structure

```
.
├── .github/
│   └── workflows/
│       ├── auto.yml              # Main pipeline (cron every 5h)
│       └── notify.yml            # Telegram notification on push
├── Logo/
│   └── Pulse_Stream_logo.jpeg    # Channel logo asset
├── config.py                     # Channel order + performance tuning
├── logos.py                      # Logo URL database
├── merge_m3u.py                  # Step 1: Fetch & merge sources
├── adult_filter.py               # Step 2: Remove adult channels
├── attach_logos.py               # Step 3: Attach channel logos
├── order_m3u.py                  # Step 4: Sort by CHANNEL_ORDER
├── scan_valid.py                 # Step 5: Validate stream URLs
├── utils.py                      # Shared utilities (name cleaning, parsing)
├── requirements.txt              # Python dependencies
├── sources2.txt                  # M3U source URLs (one per line)
├── ad.html                       # Ad page
├── run2.bat                      # Local batch runner
├── .gitignore
└── README.md
```

---

## Local Development

### Prerequisites
- Python 3.10+
- Git

### Setup

```bash
git clone https://github.com/<your-username>/iptv-bot-m3u.git
cd iptv-bot-m3u
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### Run the full pipeline locally

```bash
python merge_m3u.py
python adult_filter.py
python attach_logos.py
python order_m3u.py
python scan_valid.py merged.m3u merged.m3u --stats-file ridoy_scan_stats.json
cp merged.m3u ridoyiptv.m3u
```

### Run individual steps

```bash
python merge_m3u.py                    # Merge sources only
python adult_filter.py                 # Filter adult channels
python attach_logos.py                 # Attach logos
python order_m3u.py                    # Reorder channels
python scan_valid.py input.m3u out.m3u # Validate a playlist
```

---

## Output Files

| File | Description | Git-tracked |
|------|-------------|-------------|
| `ridoyiptv.m3u` | Final published playlist (Pulse Stream Server 2) | No (auto-generated) |
| `ridoy_scan_stats.json` | Scan statistics (alive/dead/latency) | No (auto-generated) |
| `merged.m3u` | Intermediate merged playlist | No (auto-generated) |
| `mahdi_iptv.m3u8` | Secondary playlist (Server 1) | Yes (managed by `notify.yml`) |
| `mahdi_scan_stats.json` | Secondary scan stats | Yes (managed by `notify.yml`) |

---

## License

Personal project — not for redistribution.
