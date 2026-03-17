# Watchbar

A macOS menubar app for managing your YouTube Watch Later playlist.

![macOS](https://img.shields.io/badge/macOS-only-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)

## Features

- Browse your Watch Later playlist from the menubar
- Search and filter videos
- Sort by title, duration, or default order
- Remove videos from Watch Later
- Download videos for offline viewing (via yt-dlp)
- Thumbnails and duration display
- Tab view for Watch Later and downloaded videos

## Requirements

- macOS
- Python 3.13+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed globally)
- Safari (used for YouTube authentication cookies)

## Setup

```bash
git clone https://github.com/jswanson/watchbar.git
cd watchbar
chmod +x run.sh
./run.sh
```

The first run creates a virtual environment and installs dependencies automatically.

## Usage

Once running, a small video icon appears in your menubar. Click it to open the popover with your Watch Later playlist.

- **Search**: Filter videos by title
- **Sort**: Reorder by name or duration
- **Remove**: Remove a video from your Watch Later playlist
- **Download**: Save a video locally for offline playback
- **Tabs**: Switch between Watch Later and downloaded videos

## How it works

Watchbar uses yt-dlp to extract authentication cookies from Safari and fetches your Watch Later playlist via YouTube's InnerTube API. The native macOS UI is built with PyObjC.
