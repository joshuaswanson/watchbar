# Watchbar

A macOS menubar app for managing your YouTube Watch Later playlist.

![macOS](https://img.shields.io/badge/macOS-only-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)

## Features

- Browse your Watch Later playlist from the menubar with video count badge
- Search and filter videos by title
- Sort by alphabetical, duration, or default order with ascending/descending toggle
- Download and play videos locally (no ads, no autoplay), with English captions embedded into the mp4
- Open videos in browser
- Remove videos from Watch Later
- Auto-refresh every 5 minutes
- Thumbnails and duration display
- Tab view for Watch Later and downloaded videos

## Requirements

- macOS
- Python 3.13+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) on `PATH` (e.g. `brew install yt-dlp`)
- Safari, signed into your YouTube/Google account

## Setup

1. **Sign into YouTube in Safari.** Watchbar reads YouTube auth cookies directly from Safari's cookie store via `yt-dlp --cookies-from-browser safari` — there's no separate login flow inside the app. If you're not signed in there, the playlist will be empty.

2. **Grant Full Disk Access to Terminal** (System Settings → Privacy & Security → Full Disk Access). macOS protects Safari's cookie database, so without this, `yt-dlp` cannot read your cookies and the app will show no videos. Add whichever terminal you launch `run.sh` from (Terminal.app, iTerm, etc.).

3. **Clone and run:**

   ```bash
   git clone https://github.com/joshuaswanson/watchbar.git
   cd watchbar
   chmod +x run.sh
   ./run.sh
   ```

   The first run creates a virtual environment and installs dependencies automatically. To launch from Finder later, double-click `Watchbar.command`.

Cookies are re-extracted from Safari roughly every 30 minutes, so as long as you stay signed into YouTube in Safari, the app keeps working without manual re-auth. If you sign out of Safari, Watchbar loses access too.

## Usage

Once running, a small video icon appears in your menubar with a video count. Click it to open the popover with your Watch Later playlist.

- **Click** a video to download and play locally
- **Hover** a row to reveal action buttons: open in browser (Safari icon) and remove from Watch Later / delete download (trash icon)
- Switch between **Watch Later** and **Downloaded** tabs to see your playlist or local files
- Use the search field to filter by title
- Use the sort dropdown (Default, Alphabetical, Duration) and the arrow button to change order and direction
- Press the refresh button to re-fetch the playlist immediately

## How it works

Watchbar uses yt-dlp to extract authentication cookies from Safari and fetches your Watch Later playlist via YouTube's InnerTube API. The native macOS UI is built with PyObjC. Videos can be downloaded locally via yt-dlp for offline playback, with English auto-captions embedded into each mp4.

## Support

If you find this useful, [buy me a coffee](https://buymeacoffee.com/swanson).

<img src="assets/bmc_qr.png" alt="Buy Me a Coffee QR" width="200">
