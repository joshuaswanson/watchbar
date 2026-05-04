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
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed globally)
- Safari (used for YouTube authentication cookies)

## Setup

```bash
git clone https://github.com/joshuaswanson/watchbar.git
cd watchbar
chmod +x run.sh
./run.sh
```

The first run creates a virtual environment and installs dependencies automatically.

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
