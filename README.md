# Watchbar

A macOS menubar app for managing your YouTube Watch Later playlist.

![macOS](https://img.shields.io/badge/macOS-only-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)

## Features

- Browse your Watch Later playlist from the menubar with video count badge
- Search and filter videos by title
- Sort by alphabetical, duration, or default order with ascending/descending toggle
- Download and play videos locally (no ads, no autoplay)
- Open videos in browser
- Remove videos from Watch Later
- Keyboard navigation (arrow keys, Enter to play, Delete to remove)
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

### Mouse

- **Click** a video to download and play locally
- **Hover** to reveal action buttons: open in browser (safari icon) and remove (X)

### Keyboard

| Key     | Action                       |
| ------- | ---------------------------- |
| Up/Down | Navigate videos              |
| Enter   | Download/play selected video |
| Delete  | Remove selected video        |
| Escape  | Close popover                |

### Sorting

Use the dropdown to pick a sort field (Default, Alphabetical, Duration) and the arrow button to toggle ascending/descending.

## How it works

Watchbar uses yt-dlp to extract authentication cookies from Safari and fetches your Watch Later playlist via YouTube's InnerTube API. The native macOS UI is built with PyObjC. Videos can be downloaded locally via yt-dlp for offline playback.
