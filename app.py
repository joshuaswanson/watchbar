#!/usr/bin/env python3
"""YouTube Watch Later - macOS menubar app with popover UI."""

import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request
from datetime import date

import objc
from AppKit import (
    NSApplication,
    NSBezierPath,
    NSBitmapImageRep,
    NSBox,
    NSButton,
    NSColor,
    NSCompositingOperationClear,
    NSEvent,
    NSFont,
    NSGraphicsContext,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSPopover,
    NSPopUpButton,
    NSProgressIndicator,
    NSScrollView,
    NSSegmentedControl,
    NSStatusBar,
    NSTextField,
    NSTrackingArea,
    NSView,
    NSViewController,
)
from Foundation import (
    NSMakePoint,
    NSMakeSize,
    NSObject,
    NSTimer,
)
from PyObjCTools import AppHelper

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(_PROJECT_DIR, "downloads")
CACHE_DIR = os.path.join(_PROJECT_DIR, ".cache")
COOKIE_FILE = os.path.join(CACHE_DIR, "cookies.txt")
THUMB_DIR = os.path.join(CACHE_DIR, "thumbnails")
ICON_PATH = os.path.join(CACHE_DIR, "yt_icon.png")
YT_DLP = "yt-dlp"
FFMPEG = "ffmpeg"
# yt-dlp older than this is proactively refreshed on launch. YouTube breaks
# older builds every few weeks, so we stay ahead of its own 90-day warning.
YTDLP_STALE_DAYS = 30

PANEL_WIDTH = 380
PANEL_MAX_HEIGHT = 500
ROW_HEIGHT = 64
HEADER_HEIGHT = 74  # tabs + refresh/sort

SORT_DEFAULT = "Default"
SORT_ALPHA = "Alphabetical"
SORT_DURATION = "Duration"
SORT_OPTIONS = [SORT_DEFAULT, SORT_ALPHA, SORT_DURATION]

TAB_SUBSCRIPTIONS = 0
TAB_WATCH_LATER = 1
TAB_DOWNLOADED = 2
ROW_MODES = {TAB_SUBSCRIPTIONS: "subs", TAB_WATCH_LATER: "wl", TAB_DOWNLOADED: "dl"}

SUBSCRIPTIONS_MAX_AGE_DAYS = 8
SUBSCRIPTIONS_MAX_VIDEOS = 200
BULK_DOWNLOAD_CONCURRENCY = 3

AUTO_REFRESH_INTERVAL = 300.0  # 5 minutes
COOKIE_MAX_AGE = 1800  # 30 minutes

# AppKit enum values, named for readability.
NS_LINE_BREAK_TRUNCATING_TAIL = 4
NS_TEXT_ALIGNMENT_CENTER = 1
NS_IMAGE_LEFT = 2
NS_BITMAP_FILE_TYPE_PNG = 4
NS_POPOVER_BEHAVIOR_TRANSIENT = 1
NS_BOX_SEPARATOR = 2
NS_PROGRESS_STYLE_SPINNING = 1
NS_CONTROL_SIZE_SMALL = 1
NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY = 1
NS_EVENT_MASK_LEFT_AND_RIGHT_MOUSE_DOWN = (1 << 1) | (1 << 3)
# NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
NS_TRACKING_OPTS = 0x01 | 0x80 | 0x200


# ---- Utilities ----


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _load_cookies():
    cj = http.cookiejar.MozillaCookieJar(COOKIE_FILE)
    cj.load()
    cookies = {}
    for c in cj:
        if c.domain in (".youtube.com", "www.youtube.com"):
            cookies[c.name] = c.value
    return cookies


def _sapisidhash(cookies):
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID", "")
    ts = str(int(time.time()))
    h = hashlib.sha1(
        f"{ts} {sapisid} https://www.youtube.com".encode()
    ).hexdigest()
    return f"SAPISIDHASH {ts}_{h}"


_client_version_cache = {"version": None, "fetched": 0}


def _get_client_version():
    cache = _client_version_cache
    if cache["version"] and time.time() - cache["fetched"] < 3600:
        return cache["version"]
    try:
        req = urllib.request.Request("https://www.youtube.com")
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urllib.request.urlopen(req, context=_ssl_ctx(), timeout=10)
        page = resp.read().decode()
        m = re.search(r'"clientVersion":"([\d.]+)"', page)
        if m:
            cache["version"] = m.group(1)
            cache["fetched"] = time.time()
            return cache["version"]
    except Exception:
        pass
    return "2.20260320.01.00"


def _fmt_duration(seconds):
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return ""
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _fmt_age(timestamp):
    if timestamp is None:
        return ""
    days = int((time.time() - timestamp) // 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def create_menubar_icon():
    if os.path.exists(ICON_PATH):
        return ICON_PATH
    os.makedirs(CACHE_DIR, exist_ok=True)

    size = 18
    img = NSImage.alloc().initWithSize_((size, size))
    img.lockFocus()
    rect_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        ((1, 3), (16, 12)), 3, 3
    )
    NSColor.blackColor().setFill()
    rect_path.fill()
    tri = NSBezierPath.bezierPath()
    tri.moveToPoint_((7, 5))
    tri.lineToPoint_((7, 13))
    tri.lineToPoint_((13, 9))
    tri.closePath()
    NSGraphicsContext.currentContext().setCompositingOperation_(
        NSCompositingOperationClear
    )
    tri.fill()
    img.unlockFocus()

    tiff = img.TIFFRepresentation()
    rep = NSBitmapImageRep.imageRepWithData_(tiff)
    png = rep.representationUsingType_properties_(NS_BITMAP_FILE_TYPE_PNG, {})
    png.writeToFile_atomically_(ICON_PATH, True)
    return ICON_PATH


def download_thumbnail(video_id):
    path = os.path.join(THUMB_DIR, f"{video_id}.jpg")
    if os.path.exists(path):
        return path
    try:
        url = f"https://i.ytimg.com/vi/{video_id}/default.jpg"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urllib.request.urlopen(req, context=_ssl_ctx(), timeout=5)
        with open(path, "wb") as f:
            f.write(resp.read())
        return path
    except Exception:
        return None


def _cookies_are_fresh():
    if not os.path.exists(COOKIE_FILE):
        return False
    return time.time() - os.path.getmtime(COOKIE_FILE) < COOKIE_MAX_AGE


def extract_cookies():
    if os.path.exists(COOKIE_FILE):
        os.remove(COOKIE_FILE)
    subprocess.run(
        [YT_DLP, "--ignore-config", "--cookies-from-browser", "safari",
         "--cookies", COOKIE_FILE, "--skip-download", "--no-write-subs",
         "--no-write-auto-subs",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        capture_output=True, cwd=CACHE_DIR, timeout=60,
    )


def fetch_playlist():
    result = subprocess.run(
        [YT_DLP, "--ignore-config", "--cookies-from-browser", "safari",
         "--flat-playlist", "--print", "%(id)s\t%(title)s\t%(duration)s",
         "https://www.youtube.com/playlist?list=WL"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"[load] yt-dlp playlist failed:\n{result.stderr.strip()[-1000:]}")
    videos = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            vid, title = parts[0], parts[1]
            duration = 0
            if len(parts) >= 3:
                try:
                    duration = int(parts[2])
                except (ValueError, TypeError):
                    pass
            videos.append({"id": vid, "title": title, "duration": duration})
    return videos


def fetch_subscriptions():
    """Recent uploads from the subscriptions feed, newest first. Returns None
    when the fetch fails so the caller can keep its previous list."""
    cutoff = int(time.time()) - SUBSCRIPTIONS_MAX_AGE_DAYS * 86400
    result = subprocess.run(
        [YT_DLP, "--ignore-config", "--cookies-from-browser", "safari",
         "--flat-playlist", "--playlist-end", str(SUBSCRIPTIONS_MAX_VIDEOS),
         # The feed only carries relative dates ("3 days ago"); this option
         # converts them to approximate timestamps.
         "--extractor-args", "youtubetab:approximate_date",
         # The feed is newest first, so stop at the first video past the
         # cutoff. ">=?" lets entries without a date (live streams) through.
         "--break-match-filters", f"timestamp>=?{cutoff}",
         "--print", "%(id)s\t%(title)s\t%(duration)s\t%(channel)s\t%(timestamp)s",
         "https://www.youtube.com/feed/subscriptions"],
        capture_output=True, text=True, timeout=90,
    )
    # 101 is yt-dlp's exit code for stopping at --break-match-filters.
    if result.returncode not in (0, 101):
        print(f"[load] yt-dlp subscriptions failed:\n{result.stderr.strip()[-1000:]}")
        return None
    videos = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        vid, title, duration, channel, timestamp = parts
        videos.append({
            "id": vid,
            "title": title,
            "duration": int(duration) if duration.isdigit() else 0,
            "channel": "" if channel == "NA" else channel,
            "timestamp": int(timestamp) if timestamp.isdigit() else None,
        })
    return videos


def fetch_set_video_ids():
    cookies = _load_cookies()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request("https://www.youtube.com/playlist?list=WL")
    req.add_header("Cookie", cookie_header)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
    resp = urllib.request.urlopen(req, context=_ssl_ctx(), timeout=20)
    page = resp.read().decode("utf-8")
    mappings = {}
    for m in re.finditer(r'"playlistVideoRenderer":\{"videoId":"([^"]+)"', page):
        vid = m.group(1)
        chunk = page[m.start():m.start() + 5000]
        svid_match = re.search(r'"setVideoId":"([^"]+)"', chunk)
        if svid_match:
            mappings[vid] = svid_match.group(1)
    return mappings


def remove_from_watch_later(video_id, set_video_id):
    cookies = _load_cookies()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    payload = json.dumps({
        "context": {
            "client": {"clientName": "WEB", "clientVersion": _get_client_version()}
        },
        "actions": [{
            "setVideoId": set_video_id,
            "removedVideoId": video_id,
            "action": "ACTION_REMOVE_VIDEO",
        }],
        "playlistId": "WL",
    }).encode()
    req = urllib.request.Request(
        "https://www.youtube.com/youtubei/v1/browse/edit_playlist",
        data=payload, method="POST",
    )
    req.add_header("Cookie", cookie_header)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", _sapisidhash(cookies))
    req.add_header("Origin", "https://www.youtube.com")
    req.add_header("X-Origin", "https://www.youtube.com")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        resp = urllib.request.urlopen(req, context=_ssl_ctx(), timeout=20)
        body = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"[remove] HTTP {e.code}: {e.read().decode()[:500]}")
        return False
    result = json.loads(body)
    status = result.get("status")
    if status != "STATUS_SUCCEEDED":
        print(f"[remove] Unexpected status: {status}")
        print(f"[remove] Response: {json.dumps(result, indent=2)[:1000]}")
    return status == "STATUS_SUCCEEDED"


def find_local_file(video_id):
    if not os.path.isdir(DOWNLOAD_DIR):
        return None
    # Match only the final merged file (…[id].mp4), never yt-dlp's per-stream
    # intermediates like …[id].f137.mp4, which linger if a merge fails.
    suffix = f"[{video_id}].mp4"
    for f in os.listdir(DOWNLOAD_DIR):
        if f.endswith(suffix):
            return os.path.join(DOWNLOAD_DIR, f)
    return None


def _cleanup_orphan_subs(video_id):
    for f in os.listdir(DOWNLOAD_DIR):
        if f"[{video_id}]" in f and f.endswith(".vtt"):
            try:
                os.remove(os.path.join(DOWNLOAD_DIR, f))
            except OSError:
                pass


def download_video(video_id, progress_cb=None):
    # Signed-in requests can hit YouTube's SABR-only experiment, which hides
    # every stream except 360p format 18. Anonymous requests still get the
    # full format list, so cookies are only used when the anonymous attempt
    # fails (private, members-only, or age-restricted videos).
    succeeded, output = _run_download(video_id, [], progress_cb)
    if not succeeded:
        succeeded, output = _run_download(
            video_id, ["--cookies-from-browser", "safari"], progress_cb)
    _cleanup_orphan_subs(video_id)
    if not succeeded:
        print(f"[download] yt-dlp failed for {video_id}")
        print(output)
    return succeeded, output


def _run_download(video_id, cookie_args, progress_cb):
    # --ignore-errors so a failed subtitle fetch (e.g. HTTP 429 on one of
    # several language variants) doesn't abort the actual video download.
    # --newline prints progress on its own line (instead of a \r-updated
    # line) so we can stream it and report percent to the UI.
    proc = subprocess.Popen(
        [YT_DLP, "--ignore-config", "--ignore-errors", "--newline",
         *cookie_args,
         # Prefer H.264 video + AAC audio so the resulting mp4 plays in
         # QuickTime. yt-dlp's default picks AV1 + Opus by bitrate, which
         # QuickTime won't decode.
         "-f", "bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]"
               "/b[ext=mp4][height<=1080]/bv*[height<=1080]+ba/b",
         "--write-auto-subs", "--sub-langs", "en.*", "--embed-subs",
         "--merge-output-format", "mp4",
         "-o", os.path.join(DOWNLOAD_DIR, "%(title)s [%(id)s].%(ext)s"),
         f"https://www.youtube.com/watch?v={video_id}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    output_tail = []
    for line in proc.stdout:
        line = line.rstrip()
        output_tail.append(line)
        if len(output_tail) > 40:
            output_tail.pop(0)
        if progress_cb:
            m = re.search(r'\[download\]\s+([\d.]+)%', line)
            if m:
                try:
                    progress_cb(float(m.group(1)))
                except ValueError:
                    pass
    proc.wait()
    succeeded = proc.returncode == 0 and find_local_file(video_id) is not None
    return succeeded, "\n".join(output_tail)


# ---- Toolchain health & self-repair ----
#
# Two failures recur in the wild: yt-dlp goes stale (YouTube changes and old
# builds start returning HTTP 403 / extractor errors), and ffmpeg's Homebrew
# dependency dylibs get pruned (e.g. by `brew autoremove`), leaving ffmpeg
# unable to launch so downloads can't be merged. Both are detectable and
# repairable via Homebrew, which is what this section does.

CAUSE_YTDLP = "ytdlp"
CAUSE_FFMPEG = "ffmpeg"
CAUSE_UNKNOWN = "unknown"

# Row messages shown when a download fails even after an auto-repair attempt.
_FAIL_MESSAGES = {
    CAUSE_YTDLP: "yt-dlp couldn't fetch this - click to retry",
    CAUSE_FFMPEG: "ffmpeg is broken - click to retry",
    CAUSE_UNKNOWN: "Download failed - click to retry",
}

# Substrings in yt-dlp output that indicate a stale extractor (fixed by
# upgrading yt-dlp), as opposed to a genuinely unavailable video.
_STALE_SIGNS = (
    "http error 403",
    "unable to extract",
    "failed to extract any player response",
    "sign in to confirm",
    "confirm you're not a bot",
    "nsig extraction failed",
    "unable to download webpage: http error",
    "requested format is not available",
)


def _brew():
    for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.exists(p):
            return p
    return "brew"


def _run_brew(args):
    try:
        r = subprocess.run(
            [_brew()] + args, capture_output=True, text=True,
            env={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"},
        )
    except FileNotFoundError:
        return False, "brew not found"
    if r.returncode != 0:
        print(f"[repair] brew {' '.join(args)} failed:\n{r.stderr.strip()[-1000:]}")
    return r.returncode == 0, r.stdout + r.stderr


def ffmpeg_ok():
    try:
        r = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _ffmpeg_missing_formulae():
    """Homebrew formulae whose dylibs ffmpeg links against but are gone."""
    ffmpeg_path = shutil.which(FFMPEG)
    if not ffmpeg_path:
        return []
    try:
        r = subprocess.run(["otool", "-L", ffmpeg_path],
                           capture_output=True, text=True)
    except FileNotFoundError:
        return []
    formulae = []
    for line in r.stdout.splitlines():
        m = re.match(r'\s*(/opt/homebrew/opt/([^/]+)/lib/\S+)', line)
        if m and not os.path.exists(m.group(1)):
            formulae.append(m.group(2))
    return list(dict.fromkeys(formulae))  # dedup, preserve order


def repair_ffmpeg():
    """Reinstall ffmpeg's missing dependency formulae. Returns True if fixed."""
    missing = _ffmpeg_missing_formulae()
    if missing:
        print(f"[repair] Installing missing ffmpeg deps: {', '.join(missing)}")
        _run_brew(["install"] + missing)
    return ffmpeg_ok()


def ytdlp_age_days():
    """Age of the installed yt-dlp in days, or None if undeterminable."""
    try:
        r = subprocess.run([YT_DLP, "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    parts = r.stdout.strip().split(".")
    try:
        released = date(int(parts[0]), int(parts[1]), int(parts[2][:2]))
    except (ValueError, IndexError):
        return None
    return (date.today() - released).days


def upgrade_ytdlp():
    """Upgrade yt-dlp via Homebrew. Returns True on success."""
    print("[repair] Upgrading yt-dlp")
    ok, _ = _run_brew(["upgrade", "yt-dlp"])
    return ok


def classify_download_failure(output):
    if not ffmpeg_ok():
        return CAUSE_FFMPEG
    low = output.lower()
    if "postprocessing" in low and "ffmpeg" in low:
        return CAUSE_FFMPEG
    if any(sign in low for sign in _STALE_SIGNS):
        return CAUSE_YTDLP
    return CAUSE_UNKNOWN


# ---- Video row view ----


class VideoRowView(NSView):
    """A single video row. mode='wl' or 'dl' controls button behavior."""

    def initWithVideo_app_mode_(self, video, app, mode):
        self = objc.super(VideoRowView, self).initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, ROW_HEIGHT)
        )
        if self is None:
            return None
        self._video = video
        self._app = app
        self._mode = mode  # "subs", "wl" or "dl"
        self._hover = False

        vid = video["id"]
        title = video["title"]
        duration = _fmt_duration(video["duration"])
        local = find_local_file(vid)
        # Rows for a video that is still downloading or has failed get a
        # spinner / status line. On the dl tab they have no file yet, so they
        # also get no trash button.
        is_downloading = video.get("_downloading")
        is_failed = video.get("_failed")
        is_pending = mode == "dl" and (is_downloading or is_failed)

        # Thumbnail
        self._thumb = NSImageView.alloc().initWithFrame_(
            NSMakeRect(10, 12, 60, 40)
        )
        thumb_path = os.path.join(THUMB_DIR, f"{vid}.jpg")
        if os.path.exists(thumb_path):
            img = NSImage.alloc().initWithContentsOfFile_(thumb_path)
            if img:
                self._thumb.setImage_(img)
                self._thumb.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.addSubview_(self._thumb)

        # Title — full width by default, shrinks on hover to make room for buttons.
        self._title_full_width = PANEL_WIDTH - 108
        has_trash_btn = mode != "subs"
        has_browser_btn = mode != "dl"
        has_download_btn = mode != "dl" and not local and not is_downloading
        button_count = has_trash_btn + has_browser_btn + has_download_btn
        self._title_hover_width = PANEL_WIDTH - 102 - 28 * button_count
        # Pending rows have no hover buttons, so keep the title full width.
        if is_pending:
            self._title_hover_width = self._title_full_width
        self._title_label = NSTextField.labelWithString_(title)
        self._title_label.setFrame_(NSMakeRect(78, 32, self._title_full_width, 18))
        self._title_label.setFont_(NSFont.systemFontOfSize_(12.5))
        self._title_label.setTextColor_(NSColor.labelColor())
        self._title_label.setLineBreakMode_(NS_LINE_BREAK_TRUNCATING_TAIL)
        self.addSubview_(self._title_label)

        # Subtitle
        sub_x = 78
        sub_text = duration
        if mode == "subs":
            sub_text = " · ".join(filter(None, [
                video.get("channel"), duration, _fmt_age(video.get("timestamp")),
            ]))
        sub_color = NSColor.secondaryLabelColor()
        if mode != "dl" and local:
            # Green checkmark for downloaded indicator on the subs and WL tabs
            dl_icon = NSImageView.alloc().initWithFrame_(
                NSMakeRect(78, 14, 14, 14)
            )
            check_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "checkmark.circle.fill", "Downloaded"
            )
            if check_img:
                dl_icon.setImage_(check_img)
                dl_icon.setContentTintColor_(NSColor.systemGreenColor())
            self.addSubview_(dl_icon)
            sub_x = 95
        elif is_downloading:
            spinner = NSProgressIndicator.alloc().initWithFrame_(
                NSMakeRect(78, 13, 16, 16)
            )
            spinner.setStyle_(NS_PROGRESS_STYLE_SPINNING)
            spinner.setControlSize_(NS_CONTROL_SIZE_SMALL)
            spinner.setIndeterminate_(True)
            spinner.startAnimation_(None)
            self.addSubview_(spinner)
            sub_x = 98
            status_text = video.get("_status_text")
            if status_text:
                sub_text = status_text  # e.g. "Repairing ffmpeg..."
            else:
                progress = video.get("_progress")
                sub_text = (
                    f"Downloading {int(progress)}%" if progress is not None
                    else "Downloading..."
                )
        elif is_failed:
            sub_text = video.get("_status_text") or "Download failed - click to retry"
            sub_color = NSColor.systemRedColor()

        self._sub_label = NSTextField.labelWithString_(sub_text)
        self._sub_label.setFrame_(NSMakeRect(sub_x, 14, PANEL_WIDTH - 140, 15))
        self._sub_label.setFont_(NSFont.systemFontOfSize_(11))
        self._sub_label.setTextColor_(sub_color)
        self.addSubview_(self._sub_label)

        # Action buttons (hover only). Pending (downloading/failed) rows have
        # no file to act on, so their trash button stays hidden even on hover.
        self._show_action = has_trash_btn and not is_pending
        btn_x = PANEL_WIDTH - 38
        next_btn_x = btn_x - 28 if has_trash_btn else btn_x

        # Remove/delete button
        self._action_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(btn_x, 20, 24, 24)
        )
        self._action_btn.setBordered_(False)
        self._action_btn.setHidden_(True)

        if mode == "wl":
            icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "trash", "Remove from Watch Later"
            )
            if icon:
                self._action_btn.setImage_(icon)
                self._action_btn.setTitle_("")
            self._action_btn.setToolTip_("Remove from Watch Later")
            self._action_btn.setTarget_(self)
            self._action_btn.setAction_("onRemove:")
        else:
            icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "trash", "Delete download"
            )
            if icon:
                self._action_btn.setImage_(icon)
                self._action_btn.setTitle_("")
            self._action_btn.setToolTip_("Delete download")
            self._action_btn.setTarget_(self)
            self._action_btn.setAction_("onDelete:")

        self.addSubview_(self._action_btn)

        # Download-only button (hover only, rows without a local file)
        self._download_btn = None
        if has_download_btn:
            self._download_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(next_btn_x, 20, 24, 24)
            )
            next_btn_x -= 28
            self._download_btn.setBordered_(False)
            self._download_btn.setHidden_(True)
            download_icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "arrow.down.circle", "Download"
            )
            if download_icon:
                self._download_btn.setImage_(download_icon)
                self._download_btn.setTitle_("")
            self._download_btn.setToolTip_("Download")
            self._download_btn.setTarget_(self)
            self._download_btn.setAction_("onDownload:")
            self.addSubview_(self._download_btn)

        # Open in browser button (hover only, subs and WL tabs)
        self._browser_btn = None
        if has_browser_btn:
            self._browser_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(next_btn_x, 20, 24, 24)
            )
            self._browser_btn.setBordered_(False)
            self._browser_btn.setHidden_(True)
            browser_icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "safari", "Open in browser"
            )
            if browser_icon:
                self._browser_btn.setImage_(browser_icon)
                self._browser_btn.setTitle_("")
            self._browser_btn.setToolTip_("Open in browser")
            self._browser_btn.setTarget_(self)
            self._browser_btn.setAction_("onOpenBrowser:")
            self.addSubview_(self._browser_btn)

        return self

    def updateTrackingAreas(self):
        objc.super(VideoRowView, self).updateTrackingAreas()
        for ta in list(self.trackingAreas()):
            self.removeTrackingArea_(ta)
        ta = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), NS_TRACKING_OPTS, self, None
        )
        self.addTrackingArea_(ta)

    def mouseEntered_(self, event):
        parent = self.superview()
        if parent:
            for sibling in parent.subviews():
                if isinstance(sibling, VideoRowView) and sibling is not self:
                    if sibling._hover:
                        sibling._hover = False
                        sibling._action_btn.setHidden_(True)
                        if sibling._browser_btn:
                            sibling._browser_btn.setHidden_(True)
                        if sibling._download_btn:
                            sibling._download_btn.setHidden_(True)
                        f = sibling._title_label.frame()
                        sibling._title_label.setFrame_(
                            NSMakeRect(f.origin.x, f.origin.y,
                                       sibling._title_full_width, f.size.height)
                        )
                        sibling.setNeedsDisplay_(True)
        self._hover = True
        if self._show_action:
            self._action_btn.setHidden_(False)
        if self._browser_btn:
            self._browser_btn.setHidden_(False)
        if self._download_btn:
            self._download_btn.setHidden_(False)
        f = self._title_label.frame()
        self._title_label.setFrame_(
            NSMakeRect(f.origin.x, f.origin.y, self._title_hover_width, f.size.height)
        )
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self._hover = False
        self._action_btn.setHidden_(True)
        if self._browser_btn:
            self._browser_btn.setHidden_(True)
        if self._download_btn:
            self._download_btn.setHidden_(True)
        f = self._title_label.frame()
        self._title_label.setFrame_(
            NSMakeRect(f.origin.x, f.origin.y, self._title_full_width, f.size.height)
        )
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        # Check if click is in button area
        btn_x = self._action_btn.frame().origin.x
        browser_x = self._browser_btn.frame().origin.x if self._browser_btn else btn_x
        min_btn_x = min(btn_x, browser_x)
        if not self._action_btn.isHidden() and loc.x >= min_btn_x:
            return
        self._app.handleVideoClick_(self._video)

    def onRemove_(self, sender):
        self._app.handleRemove_(self._video)

    def onDownload_(self, sender):
        self._app.handleDownload_(self._video)

    def onDelete_(self, sender):
        self._app.handleDeleteLocal_(self._video)

    def onOpenBrowser_(self, sender):
        self._app.handleOpenInBrowser_(self._video)

    def drawRect_(self, rect):
        NSColor.separatorColor().setFill()
        NSBezierPath.fillRect_(NSMakeRect(78, 0, PANEL_WIDTH - 78, 1))


# ---- Main app ----


class WatchLaterApp(NSObject):
    def init(self):
        self = objc.super(WatchLaterApp, self).init()
        self._videos = []
        self._subscriptions = []
        self._set_video_ids = {}
        # video_id -> {title, duration, progress, status}. Tracks in-flight and
        # failed downloads so the Downloaded tab can show live status.
        self._downloading = {}
        self._bulk_download_slots = threading.BoundedSemaphore(
            BULK_DOWNLOAD_CONCURRENCY
        )
        self._sort = SORT_DEFAULT
        self._sort_ascending = True
        self._tab = TAB_WATCH_LATER
        self._loading = True
        self._popover = None
        self._status_item = None
        self._scroll_view = None
        self._scroll_tab = None
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        os.makedirs(THUMB_DIR, exist_ok=True)
        return self

    @objc.python_method
    def setup(self):
        icon_path = create_menubar_icon()
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
        icon.setTemplate_(True)
        btn = self._status_item.button()
        btn.setImage_(icon)
        btn.setImagePosition_(NS_IMAGE_LEFT)
        btn.setTarget_(self)
        btn.setAction_("togglePopover:")

        self._popover = NSPopover.alloc().init()
        self._popover.setBehavior_(NS_POPOVER_BEHAVIOR_TRANSIENT)
        self._popover.setAnimates_(True)
        # A transient popover only closes on outside clicks while this app is
        # active, and an accessory app usually is not. The global monitor sees
        # clicks delivered to other apps.
        self._click_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NS_EVENT_MASK_LEFT_AND_RIGHT_MOUSE_DOWN, self._close_popover
        )

        threading.Thread(target=self._do_load, daemon=True).start()
        # Proactively keep the toolchain healthy so the first download works.
        threading.Thread(target=self._health_check, daemon=True).start()

        # Auto-refresh timer
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            AUTO_REFRESH_INTERVAL, self, "autoRefresh:", None, True
        )

    @objc.python_method
    def _close_popover(self, event):
        if self._popover.isShown():
            self._popover.close()

    @objc.python_method
    def _health_check(self):
        """Runs once at launch. Repairs a broken ffmpeg and refreshes a stale
        yt-dlp before the user ever clicks download."""
        try:
            if not ffmpeg_ok():
                print("[health] ffmpeg is not runnable; repairing")
                if repair_ffmpeg():
                    print("[health] ffmpeg repaired")
                else:
                    print("[health] ffmpeg repair did not succeed")
            age = ytdlp_age_days()
            if age is not None and age > YTDLP_STALE_DAYS:
                print(f"[health] yt-dlp is {age} days old; upgrading")
                upgrade_ytdlp()
        except Exception as e:
            print(f"[health] check error: {e}")

    def togglePopover_(self, sender):
        if self._popover.isShown():
            self._popover.close()
        else:
            self._build_content()
            self._popover.showRelativeToRect_ofView_preferredEdge_(
                sender.bounds(), sender, 1
            )

    def autoRefresh_(self, timer):
        if not self._loading and not self._popover.isShown():
            threading.Thread(target=self._do_load, daemon=True).start()

    @objc.python_method
    def _do_load(self):
        self._loading = True
        try:
            if not _cookies_are_fresh():
                extract_cookies()
            self._videos = fetch_playlist()
        except Exception as e:
            print(f"[load] playlist error: {e}")
        # setVideoIds are only needed for removing from Watch Later; a failure
        # here must not block the list from rendering.
        try:
            self._set_video_ids = fetch_set_video_ids()
        except Exception as e:
            print(f"[load] setVideoIds error: {e}")
        try:
            subscriptions = fetch_subscriptions()
            if subscriptions is not None:
                self._subscriptions = subscriptions
        except Exception as e:
            print(f"[load] subscriptions error: {e}")
        try:
            threads = []
            for v in self._videos + self._subscriptions:
                t = threading.Thread(
                    target=download_thumbnail, args=(v["id"],), daemon=True
                )
                t.start()
                threads.append(t)
            for t in threads:
                t.join(timeout=10)
        except Exception as e:
            print(f"[load] thumbnail error: {e}")
        self._loading = False
        print(f"[load] done: {len(self._videos)} videos, "
              f"{len(self._subscriptions)} subscription uploads")
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "postLoadUpdate:", None, False
        )

    def postLoadUpdate_(self, sender):
        self._update_badge()
        if self._popover and self._popover.isShown():
            self._build_content()

    @objc.python_method
    def _update_badge(self):
        btn = self._status_item.button()
        count = len(self._videos)
        btn.setTitle_(str(count) if count > 0 else "")
        font = NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0.0)
        btn.setFont_(font)

    @objc.python_method
    def _get_visible_videos(self):
        if self._tab == TAB_SUBSCRIPTIONS:
            return self._filtered_sorted(
                [self._with_download_status(v) for v in self._subscriptions]
            )
        if self._tab == TAB_WATCH_LATER:
            return self._filtered_sorted(
                [self._with_download_status(v) for v in self._videos]
            )
        return self._filtered_sorted(self._get_downloaded_videos())

    @objc.python_method
    def _with_download_status(self, video):
        entry = self._downloading.get(video["id"])
        if entry is None:
            return video
        status = entry.get("status")
        return {
            **video,
            # "fixing" shows a spinner too, just with a repair message.
            "_downloading": status in ("downloading", "fixing"),
            "_failed": status == "failed",
            "_progress": entry.get("progress"),
            "_status_text": entry.get("message"),
        }

    @objc.python_method
    def _get_downloaded_videos(self):
        """Get all locally downloaded videos, ordered to match Watch Later.

        Downloads still present in Watch Later follow the playlist order;
        any that are no longer in Watch Later fall to the end (in filesystem
        order) since they have no playlist position to anchor to.
        """
        durations = {v["id"]: v["duration"] for v in self._videos}
        wl_order = {v["id"]: i for i, v in enumerate(self._videos)}
        downloaded = []
        seen = set()
        if os.path.isdir(DOWNLOAD_DIR):
            for f in os.listdir(DOWNLOAD_DIR):
                if not f.endswith(".mp4"):
                    continue
                m = re.search(r'\[([a-zA-Z0-9_-]{11})\]\.mp4$', f)
                if m:
                    vid = m.group(1)
                    seen.add(vid)
                    title = f[:f.rfind(" [")]
                    downloaded.append(
                        {"id": vid, "title": title,
                         "duration": durations.get(vid, 0)}
                    )
        # In-flight / failed downloads have no file yet; surface them too.
        for vid, entry in self._downloading.items():
            if vid in seen:
                continue
            downloaded.append(self._with_download_status({
                "id": vid,
                "title": entry["title"],
                "duration": entry.get("duration", 0),
            }))
        # Sort by Watch Later position; non-WL downloads sort after all others.
        downloaded.sort(key=lambda v: wl_order.get(v["id"], len(wl_order)))
        return downloaded

    @objc.python_method
    def _filtered_sorted(self, vids):
        reverse = not self._sort_ascending
        if self._sort == SORT_ALPHA:
            return sorted(vids, key=lambda v: v["title"].lower(), reverse=reverse)
        if self._sort == SORT_DURATION:
            return sorted(vids, key=lambda v: v["duration"], reverse=reverse)
        if reverse:
            return list(reversed(vids))
        return list(vids)

    @objc.python_method
    def _build_content(self):
        # Header
        header = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, HEADER_HEIGHT)
        )

        # Tab bar (top)
        tabs = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            ["Subscriptions", "Watch Later", "Downloaded"], 0, self, "onTabChanged:",
        )
        tabs.setFrame_(NSMakeRect(10, 40, PANEL_WIDTH - 20, 26))
        tabs.setSelectedSegment_(self._tab)
        tabs.setFont_(NSFont.systemFontOfSize_(12))
        header.addSubview_(tabs)

        # Refresh button + sort (bottom row)
        refresh_btn = NSButton.buttonWithImage_target_action_(
            NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "arrow.clockwise", "Refresh"
            ),
            self,
            "onRefresh:",
        )
        refresh_btn.setFrame_(NSMakeRect(10, 8, 30, 24))
        refresh_btn.setBordered_(False)
        refresh_btn.setToolTip_("Refresh")
        header.addSubview_(refresh_btn)

        if self._tab != TAB_DOWNLOADED:
            download_all_btn = NSButton.buttonWithImage_target_action_(
                NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "arrow.down.circle", "Download all"
                ),
                self,
                "onDownloadAll:",
            )
            download_all_btn.setFrame_(NSMakeRect(42, 8, 30, 24))
            download_all_btn.setBordered_(False)
            download_all_btn.setToolTip_("Download all")
            header.addSubview_(download_all_btn)

        sort_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(PANEL_WIDTH - 145, 8, 105, 24), False
        )
        sort_popup.setFont_(NSFont.systemFontOfSize_(12))
        for opt in SORT_OPTIONS:
            sort_popup.addItemWithTitle_(opt)
        sort_popup.selectItemWithTitle_(self._sort)
        sort_popup.setTarget_(self)
        sort_popup.setAction_("onSortChanged:")
        header.addSubview_(sort_popup)

        arrow_symbol = "arrow.up" if self._sort_ascending else "arrow.down"
        dir_btn = NSButton.buttonWithImage_target_action_(
            NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                arrow_symbol,
                "Ascending" if self._sort_ascending else "Descending",
            ),
            self,
            "onSortDirectionChanged:",
        )
        dir_btn.setFrame_(NSMakeRect(PANEL_WIDTH - 36, 8, 26, 24))
        dir_btn.setBordered_(False)
        dir_btn.setToolTip_(
            "Ascending" if self._sort_ascending else "Descending"
        )
        header.addSubview_(dir_btn)

        # Divider
        divider = NSBox.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, 1)
        )
        divider.setBoxType_(NS_BOX_SEPARATOR)

        # Build rows based on active tab
        rows = []
        if self._loading:
            spacer = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH, 15))
            rows.append(spacer)
            label = NSTextField.labelWithString_("Loading...")
            label.setFrame_(NSMakeRect(0, 0, PANEL_WIDTH, 30))
            label.setAlignment_(NS_TEXT_ALIGNMENT_CENTER)
            label.setFont_(NSFont.systemFontOfSize_(13))
            label.setTextColor_(NSColor.secondaryLabelColor())
            rows.append(label)
        else:
            mode = ROW_MODES[self._tab]
            vids = self._get_visible_videos()
            if not vids:
                rows.append(NSView.alloc().initWithFrame_(
                    NSMakeRect(0, 0, PANEL_WIDTH, 15)
                ))
                if self._tab == TAB_SUBSCRIPTIONS:
                    empty_msg = "No recent uploads from your subscriptions"
                elif self._tab == TAB_WATCH_LATER:
                    empty_msg = "No videos in Watch Later"
                else:
                    empty_msg = "No downloaded videos"
                label = NSTextField.labelWithString_(empty_msg)
                label.setFrame_(NSMakeRect(0, 0, PANEL_WIDTH, 30))
                label.setAlignment_(NS_TEXT_ALIGNMENT_CENTER)
                label.setFont_(NSFont.systemFontOfSize_(13))
                label.setTextColor_(NSColor.secondaryLabelColor())
                rows.append(label)
            else:
                for v in vids:
                    row = VideoRowView.alloc().initWithVideo_app_mode_(
                        v, self, mode
                    )
                    rows.append(row)

        # Layout - fixed height to avoid jarring resizes on tab switch
        rows_height = sum(r.frame().size.height for r in rows)
        visible_height = PANEL_MAX_HEIGHT
        scroll_area_height = visible_height - HEADER_HEIGHT - 1

        content_height = max(rows_height, scroll_area_height)
        scroll_content = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, content_height)
        )
        y = content_height
        for row in rows:
            h = row.frame().size.height
            y -= h
            row.setFrameOrigin_(NSMakePoint(0, y))
            scroll_content.addSubview_(row)

        scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, scroll_area_height)
        )
        scroll_view.setHasVerticalScroller_(False)
        scroll_view.setHasHorizontalScroller_(False)
        scroll_view.setDrawsBackground_(False)
        scroll_view.setDocumentView_(scroll_content)
        # The document view is unflipped, so a new scroll view starts at the
        # bottom of the list. Restore the previous distance from the top.
        max_offset = content_height - scroll_area_height
        offset = min(self._scroll_offset_from_top(), max_offset)
        scroll_view.contentView().scrollToPoint_(
            NSMakePoint(0, max_offset - offset)
        )
        scroll_view.reflectScrolledClipView_(scroll_view.contentView())
        self._scroll_view = scroll_view
        self._scroll_tab = self._tab
        container = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, visible_height)
        )
        scroll_view.setFrameOrigin_(NSMakePoint(0, 0))
        container.addSubview_(scroll_view)
        divider.setFrameOrigin_(NSMakePoint(0, scroll_area_height))
        container.addSubview_(divider)
        header.setFrameOrigin_(NSMakePoint(0, scroll_area_height + 1))
        container.addSubview_(header)

        vc = NSViewController.alloc().init()
        vc.setView_(container)
        self._popover.setContentViewController_(vc)
        self._popover.setContentSize_(NSMakeSize(PANEL_WIDTH, visible_height))

    @objc.python_method
    def _scroll_offset_from_top(self):
        if self._scroll_view is None or self._scroll_tab != self._tab:
            return 0
        visible = self._scroll_view.contentView().documentVisibleRect()
        doc_height = self._scroll_view.documentView().frame().size.height
        return max(0, doc_height - (visible.origin.y + visible.size.height))

    def onRefresh_(self, sender):
        if not self._loading:
            self._loading = True
            self._build_content()
            threading.Thread(target=self._do_load, daemon=True).start()

    def onSortChanged_(self, sender):
        self._sort = sender.titleOfSelectedItem()
        self._build_content()

    def onSortDirectionChanged_(self, sender):
        self._sort_ascending = not self._sort_ascending
        self._build_content()

    def onTabChanged_(self, sender):
        self._tab = sender.selectedSegment()
        self._build_content()

    def handleVideoClick_(self, video):
        vid = video["id"]
        local = find_local_file(vid)
        if local:
            subprocess.Popen(["open", local])
            return
        self._start_download(video, True)

    def handleDownload_(self, video):
        if not find_local_file(video["id"]):
            self._start_download(video, False)

    def onDownloadAll_(self, sender):
        if self._tab == TAB_SUBSCRIPTIONS:
            videos = self._subscriptions
        else:
            videos = self._videos
        for video in videos:
            if self._is_in_flight(video["id"]) or find_local_file(video["id"]):
                continue
            self._track_download(video, "Queued")
            threading.Thread(
                target=self._do_queued_download, args=(video,), daemon=True
            ).start()
        self._build_content()

    @objc.python_method
    def _is_in_flight(self, vid):
        entry = self._downloading.get(vid)
        return bool(entry) and entry.get("status") in ("downloading", "fixing")

    @objc.python_method
    def _track_download(self, video, message):
        self._downloading[video["id"]] = {
            "title": video["title"],
            "duration": video.get("duration", 0),
            "progress": None,
            "status": "downloading",
            "message": message,
        }

    @objc.python_method
    def _start_download(self, video, play_when_done):
        if self._is_in_flight(video["id"]):
            return  # ignore repeat clicks
        self._track_download(video, None)
        self._build_content()
        threading.Thread(
            target=self._do_download, args=(video, play_when_done), daemon=True
        ).start()

    @objc.python_method
    def _do_queued_download(self, video):
        with self._bulk_download_slots:
            self._set_status(video["id"], "downloading", None)
            self._do_download(video, False)

    def handleOpenInBrowser_(self, video):
        url = f"https://www.youtube.com/watch?v={video['id']}"
        subprocess.Popen(["open", url])
        self._popover.close()

    def handleDeleteLocal_(self, video):
        local = find_local_file(video["id"])
        if local:
            os.remove(local)
            base = os.path.splitext(os.path.basename(local))[0]
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(base) and f != os.path.basename(local):
                    os.remove(os.path.join(DOWNLOAD_DIR, f))
            self._build_content()

    def handleRemove_(self, video):
        svid = self._set_video_ids.get(video["id"])
        self._videos = [v for v in self._videos if v["id"] != video["id"]]
        self._set_video_ids.pop(video["id"], None)
        self._update_badge()
        self._build_content()
        threading.Thread(
            target=self._do_remove_bg, args=(video, svid), daemon=True
        ).start()

    @objc.python_method
    def _set_status(self, vid, status, message=None, progress=None):
        entry = self._downloading.get(vid)
        if entry is not None:
            entry["status"] = status
            entry["message"] = message
            entry["progress"] = progress
        self._request_content_refresh()

    @objc.python_method
    def _run_download(self, vid):
        """Run one download attempt, streaming percent into the row."""
        last_pct = {"v": -1}

        def on_progress(pct):
            entry = self._downloading.get(vid)
            if entry is not None:
                entry["progress"] = pct
            # Rebuild only on a whole-percent change to avoid thrashing the UI.
            if int(pct) != last_pct["v"]:
                last_pct["v"] = int(pct)
                self._request_content_refresh()

        return download_video(vid, progress_cb=on_progress)

    @objc.python_method
    def _do_download(self, video, play_when_done):
        vid = video["id"]
        ok, output = self._run_download(vid)

        # On failure, try a one-shot toolchain repair (upgrade yt-dlp / restore
        # ffmpeg's deps) and retry the download once before giving up.
        if not ok:
            cause = classify_download_failure(output)
            if cause == CAUSE_YTDLP:
                self._set_status(vid, "fixing", "Updating yt-dlp...")
                fixed = upgrade_ytdlp()
            elif cause == CAUSE_FFMPEG:
                self._set_status(vid, "fixing", "Repairing ffmpeg...")
                fixed = repair_ffmpeg()
            else:
                fixed = False
            if fixed:
                self._set_status(vid, "downloading", None)
                ok, output = self._run_download(vid)

        if ok:
            self._downloading.pop(vid, None)
            self._request_content_refresh()
            local = find_local_file(vid)
            if local and play_when_done:
                subprocess.Popen(["open", local])
        else:
            cause = classify_download_failure(output)
            self._set_status(vid, "failed", _FAIL_MESSAGES[cause])
            print(f"[download] Failed ({cause}): {video['title'][:50]}")

    @objc.python_method
    def _request_content_refresh(self):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "refreshContent:", None, False
        )

    def refreshContent_(self, sender):
        if self._popover and self._popover.isShown():
            self._build_content()

    @objc.python_method
    def _do_remove_bg(self, video, svid):
        try:
            if svid and remove_from_watch_later(video["id"], svid):
                return
            # Safari rotates YouTube's session cookies, which logs out the
            # cached copy before COOKIE_MAX_AGE is reached.
            extract_cookies()
            svid = fetch_set_video_ids().get(video["id"])
            if not svid:
                print(f"[remove] Entry not found: {video['title'][:50]}")
            elif not remove_from_watch_later(video["id"], svid):
                print(f"[remove] Failed: {video['title'][:50]}")
        except Exception as e:
            print(f"[remove] Error: {e}")


if __name__ == "__main__":
    NSApplication.sharedApplication().setActivationPolicy_(
        NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY
    )
    app = WatchLaterApp.alloc().init()
    app.setup()
    AppHelper.runEventLoop()
