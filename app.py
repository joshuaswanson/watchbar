#!/usr/bin/env python3
"""YouTube Watch Later - macOS menubar app with popover UI."""

import hashlib
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import threading
import time
import urllib.request

import objc
from AppKit import (
    NSApplication,
    NSBezierPath,
    NSBitmapImageRep,
    NSBox,
    NSButton,
    NSColor,
    NSCompositingOperationClear,
    NSFont,
    NSGraphicsContext,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSPopover,
    NSPopUpButton,
    NSScrollView,
    NSSearchField,
    NSSegmentedControl,
    NSSegmentStyleAutomatic,
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

PANEL_WIDTH = 380
PANEL_MAX_HEIGHT = 500
ROW_HEIGHT = 50
HEADER_HEIGHT = 108  # search + tabs + refresh/sort

SORT_DEFAULT = "Default"
SORT_ALPHA = "Alphabetical"
SORT_DURATION = "Duration"
SORT_OPTIONS = [SORT_DEFAULT, SORT_ALPHA, SORT_DURATION]

TAB_WATCH_LATER = 0
TAB_DOWNLOADED = 1

AUTO_REFRESH_INTERVAL = 300.0  # 5 minutes
COOKIE_MAX_AGE = 1800  # 30 minutes

_TRACKING_OPTS = 0x01 | 0x80 | 0x200


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
    png = rep.representationUsingType_properties_(4, {})
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
        [YT_DLP, "--cookies-from-browser", "safari",
         "--cookies", COOKIE_FILE, "--skip-download", "--no-write-subs",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        capture_output=True,
    )


def fetch_playlist():
    result = subprocess.run(
        [YT_DLP, "--cookies-from-browser", "safari",
         "--flat-playlist", "--print", "%(id)s\t%(title)s\t%(duration)s",
         "https://www.youtube.com/playlist?list=WL"],
        capture_output=True, text=True,
    )
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


def fetch_set_video_ids():
    cookies = _load_cookies()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request("https://www.youtube.com/playlist?list=WL")
    req.add_header("Cookie", cookie_header)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
    resp = urllib.request.urlopen(req, context=_ssl_ctx())
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
        resp = urllib.request.urlopen(req, context=_ssl_ctx())
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
    for f in os.listdir(DOWNLOAD_DIR):
        if f"[{video_id}]" in f and f.endswith(".mp4"):
            return os.path.join(DOWNLOAD_DIR, f)
    return None


def download_video(video_id):
    result = subprocess.run(
        [YT_DLP, "--cookies-from-browser", "safari",
         "-o", os.path.join(DOWNLOAD_DIR, "%(title)s [%(id)s].%(ext)s"),
         f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


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
        self._mode = mode  # "wl" or "dl"
        self._hover = False

        vid = video["id"]
        title = video["title"]
        duration = _fmt_duration(video["duration"])
        local = find_local_file(vid)

        # Thumbnail
        self._thumb = NSImageView.alloc().initWithFrame_(
            NSMakeRect(10, 5, 60, 40)
        )
        thumb_path = os.path.join(THUMB_DIR, f"{vid}.jpg")
        if os.path.exists(thumb_path):
            img = NSImage.alloc().initWithContentsOfFile_(thumb_path)
            if img:
                self._thumb.setImage_(img)
                self._thumb.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.addSubview_(self._thumb)

        # Title (leave room for hover buttons: remove + browser)
        title_width = PANEL_WIDTH - 158 if mode == "wl" else PANEL_WIDTH - 130
        display_title = title if len(title) <= 35 else title[:32] + "..."
        self._title_label = NSTextField.labelWithString_(display_title)
        self._title_label.setFrame_(NSMakeRect(78, 25, title_width, 18))
        self._title_label.setFont_(NSFont.systemFontOfSize_(12.5))
        self._title_label.setTextColor_(NSColor.labelColor())
        self._title_label.setLineBreakMode_(5)
        self.addSubview_(self._title_label)

        # Subtitle
        sub_x = 78
        if mode == "wl" and local:
            # Green checkmark for downloaded indicator on WL tab
            dl_icon = NSImageView.alloc().initWithFrame_(
                NSMakeRect(78, 7, 14, 14)
            )
            check_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "checkmark.circle.fill", "Downloaded"
            )
            if check_img:
                dl_icon.setImage_(check_img)
                dl_icon.setContentTintColor_(NSColor.systemGreenColor())
            self.addSubview_(dl_icon)
            sub_x = 95

        self._sub_label = NSTextField.labelWithString_(duration)
        self._sub_label.setFrame_(NSMakeRect(sub_x, 7, PANEL_WIDTH - 140, 15))
        self._sub_label.setFont_(NSFont.systemFontOfSize_(11))
        self._sub_label.setTextColor_(NSColor.secondaryLabelColor())
        self.addSubview_(self._sub_label)

        # Action buttons (hover only)
        btn_x = PANEL_WIDTH - 38

        # Remove/delete button
        self._action_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(btn_x, 13, 24, 24)
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

        # Open in browser button (hover only, WL tab)
        self._browser_btn = None
        if mode == "wl":
            self._browser_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(btn_x - 28, 13, 24, 24)
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
            self.bounds(), _TRACKING_OPTS, self, None
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
                        sibling.setNeedsDisplay_(True)
        self._hover = True
        self._action_btn.setHidden_(False)
        if self._browser_btn:
            self._browser_btn.setHidden_(False)
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self._hover = False
        self._action_btn.setHidden_(True)
        if self._browser_btn:
            self._browser_btn.setHidden_(True)
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

    def onDelete_(self, sender):
        self._app.handleDeleteLocal_(self._video)

    def onOpenBrowser_(self, sender):
        self._app.handleOpenInBrowser_(self._video)

    def drawRect_(self, rect):
        if self._hover:
            NSColor.controlAccentColor().colorWithAlphaComponent_(0.08).setFill()
            NSBezierPath.fillRect_(self.bounds())


# ---- Main app ----


class WatchLaterApp(NSObject):
    def init(self):
        self = objc.super(WatchLaterApp, self).init()
        self._videos = []
        self._set_video_ids = {}
        self._sort = SORT_DEFAULT
        self._sort_ascending = True
        self._search = ""
        self._tab = TAB_WATCH_LATER
        self._loading = True
        self._popover = None
        self._status_item = None
        self._search_field = None
        self._search_focused = False
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
        btn.setImagePosition_(2)  # NSImageLeft
        btn.setTarget_(self)
        btn.setAction_("togglePopover:")

        self._popover = NSPopover.alloc().init()
        self._popover.setBehavior_(1)
        self._popover.setAnimates_(True)

        threading.Thread(target=self._do_load, daemon=True).start()

        # Auto-refresh timer
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            AUTO_REFRESH_INTERVAL, self, "autoRefresh:", None, True
        )

    def togglePopover_(self, sender):
        if self._popover.isShown():
            self._popover.close()
        else:
            self._build_content()
            self._popover.showRelativeToRect_ofView_preferredEdge_(
                sender.bounds(), sender, 1
            )
            if self._search_field:
                w = self._search_field.window()
                if w:
                    w.makeFirstResponder_(None)

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
            self._set_video_ids = fetch_set_video_ids()
            threads = []
            for v in self._videos:
                t = threading.Thread(
                    target=download_thumbnail, args=(v["id"],), daemon=True
                )
                t.start()
                threads.append(t)
            for t in threads:
                t.join(timeout=10)
        except Exception as e:
            print(f"Load error: {e}")
        self._loading = False
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "postLoadUpdate:", None, False
        )

    def postLoadUpdate_(self, sender):
        self._update_badge()
        if self._popover and self._popover.isShown() and not self._search:
            self._build_content()

    @objc.python_method
    def _update_badge(self):
        btn = self._status_item.button()
        count = len(self._videos)
        btn.setTitle_(str(count) if count > 0 else "")
        font = NSFont.monospacedDigitSystemFontOfSize_weight_(11, 0.0)
        btn.setFont_(font)

    def rebuildContent_(self, sender):
        self._build_content()

    @objc.python_method
    def _get_visible_videos(self):
        if self._tab == TAB_WATCH_LATER:
            return self._filtered_sorted(self._videos)
        return self._filtered_sorted(self._get_downloaded_videos())

    @objc.python_method
    def _get_downloaded_videos(self):
        """Get all locally downloaded videos."""
        if not os.path.isdir(DOWNLOAD_DIR):
            return []
        downloaded = []
        for f in os.listdir(DOWNLOAD_DIR):
            if not f.endswith(".mp4"):
                continue
            m = re.search(r'\[([a-zA-Z0-9_-]{11})\]\.mp4$', f)
            if m:
                vid = m.group(1)
                title = f[:f.rfind(" [")]
                # Try to get duration from WL data
                duration = 0
                for v in self._videos:
                    if v["id"] == vid:
                        duration = v["duration"]
                        break
                downloaded.append({"id": vid, "title": title, "duration": duration})
        return downloaded

    @objc.python_method
    def _filtered_sorted(self, vids):
        if self._search:
            q = self._search.lower()
            vids = [v for v in vids if q in v["title"].lower()]
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

        # Search bar (top)
        search_field = NSSearchField.alloc().initWithFrame_(
            NSMakeRect(10, 74, PANEL_WIDTH - 20, 26)
        )
        search_field.setPlaceholderString_("Search videos...")
        search_field.setFont_(NSFont.systemFontOfSize_(13))
        search_field.setStringValue_(self._search)
        search_field.setTarget_(self)
        search_field.setAction_("onSearch:")
        header.addSubview_(search_field)
        self._search_field = search_field

        # Tab bar (middle)
        tabs = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            ["Watch Later", "Downloaded"], 0, self, "onTabChanged:",
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
        divider.setBoxType_(2)

        # Build rows based on active tab
        rows = []
        if self._loading:
            spacer = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH, 15))
            rows.append(spacer)
            label = NSTextField.labelWithString_("Loading...")
            label.setFrame_(NSMakeRect(0, 0, PANEL_WIDTH, 30))
            label.setAlignment_(1)
            label.setFont_(NSFont.systemFontOfSize_(13))
            label.setTextColor_(NSColor.secondaryLabelColor())
            rows.append(label)
        else:
            mode = "wl" if self._tab == TAB_WATCH_LATER else "dl"
            vids = self._get_visible_videos()
            if not vids:
                rows.append(NSView.alloc().initWithFrame_(
                    NSMakeRect(0, 0, PANEL_WIDTH, 15)
                ))
                if self._search:
                    empty_msg = "No matches"
                elif self._tab == TAB_WATCH_LATER:
                    empty_msg = "No videos in Watch Later"
                else:
                    empty_msg = "No downloaded videos"
                label = NSTextField.labelWithString_(empty_msg)
                label.setFrame_(NSMakeRect(0, 0, PANEL_WIDTH, 30))
                label.setAlignment_(1)
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

        # Restore search field focus if it was active before rebuild
        if self._search_focused and self._search_field:
            w = self._search_field.window()
            if w:
                w.makeFirstResponder_(self._search_field)
                # Place cursor at end of text
                editor = self._search_field.currentEditor()
                if editor:
                    editor.setSelectedRange_((len(self._search), 0))

    def onRefresh_(self, sender):
        if not self._loading:
            self._loading = True
            self._build_content()
            threading.Thread(target=self._do_load, daemon=True).start()

    def onSearch_(self, sender):
        new_search = sender.stringValue()
        if new_search == self._search:
            return
        self._search = new_search
        self._search_focused = True
        self._build_content()
        self._search_focused = False

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
        local = find_local_file(video["id"])
        if local:
            subprocess.Popen(["open", local])
        else:
            self._popover.close()
            threading.Thread(
                target=self._do_download, args=(video,), daemon=True
            ).start()

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
        if not svid:
            print("[remove] Entry not found. Try refreshing.")
            return
        self._videos = [v for v in self._videos if v["id"] != video["id"]]
        self._set_video_ids.pop(video["id"], None)
        self._update_badge()
        self._build_content()
        threading.Thread(
            target=self._do_remove_bg, args=(video, svid), daemon=True
        ).start()

    @objc.python_method
    def _do_download(self, video):
        if download_video(video["id"]):
            local = find_local_file(video["id"])
            if local:
                subprocess.Popen(["open", local])
        else:
            print(f"[download] Failed: {video['title'][:50]}")

    @objc.python_method
    def _do_remove_bg(self, video, svid):
        try:
            if not remove_from_watch_later(video["id"], svid):
                print(f"[remove] Failed: {video['title'][:50]}")
        except Exception as e:
            print(f"[remove] Error: {e}")


if __name__ == "__main__":
    NSApplication.sharedApplication().setActivationPolicy_(1)
    app = WatchLaterApp.alloc().init()
    app.setup()
    AppHelper.runEventLoop()
