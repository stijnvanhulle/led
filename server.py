"""HTTP API for the iPixel LED panel, plus a GitHub stars job. The control page is web/ (Nuxt).

POST /command/<name>  JSON body = keyword args of that pypixelcolor command
                      e.g. /command/send_text {"text": "hi", "color": "ff0000"}
POST /stars           show the GitHub star count now. Optional body {"repo": "owner/name"}
POST /clock           {"color", "h24", "blink"}: the Pi draws HH:MM and redraws it every minute
POST /repo            {"repo": "owner/name", "color"?}: track another repo without changing the screen
POST /weather         {"color"?}: show the temperature and an icon, redrawn every 10 minutes
POST /calendar        {"color"?}: show the next event ("in 12m", "14:30", "free"), redrawn every minute
POST /npm             {"color"?}: show an npm package's downloads, checked every hour
POST /config          {"weather"?: {name, lat, lon}, "calendar"?: {url}, "night"?: {enabled, off, on},
                       "busy"?: {urls, auto, soon}, "npm"?: {package, period}}
POST /busy            {"force"?}: show the busy light (green free, orange soon, red in a meeting)
GET  /preview/weather, /preview/calendar, /preview/npm   the exact frames, same shape as /preview/stars. The
                      calendar adds "title": the second page's text pixels and its timing
GET  /preview?text=…  the pixels send_text would draw: {"w", "rows"}, "1" = text color, "rrggbb" = emoji, "" = off
GET  /preview/stars   the exact stars frame, same shape
GET  /health          {"ok": true, "mode": ..., "repo": ..., "stars": <last count>}

The stars job only redraws the panel while mode is "stars". Any other display
command switches the mode to that command, so it is not overwritten. The mode starts
empty: nothing is drawn until a client (the Nuxt server, on start) says what to show.
"""
import io
import json
import math
from concurrent.futures import ThreadPoolExecutor
import re
import signal
import sys
import unicodedata
from datetime import datetime
from functools import lru_cache
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pypixelcolor
from PIL import Image, ImageDraw, ImageFont
from pypixelcolor import Client
from pypixelcolor.commands import COMMANDS
from pypixelcolor.lib.emoji_manager import get_emoji_image, is_emoji
from urllib.parse import parse_qs, urlparse

import features

FONT = Path(pypixelcolor.__file__).parent / "fonts" / "unifont.otf"

ADDRESS = os.environ.get("LED_ADDRESS")  # required, set in .env by install.sh
PORT = int(os.environ.get("PORT", "8080"))
TOKEN = os.environ.get("API_TOKEN")  # optional; when set, require "Authorization: Bearer <token>"
REPO = os.environ.get("GITHUB_REPO", "kubb-labs/kubb")
INTERVAL = int(os.environ.get("STARS_INTERVAL", "600"))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional; raises the 60 req/h anonymous limit

# send_image reads a path on the Pi, so the API uses send_image_hex instead.
ALLOWED = set(COMMANDS) - {"send_image"}

# Commands that change settings, not what is on screen. They keep the current mode.
SETTINGS = {"set_brightness", "set_power", "set_orientation", "set_schedule", "set_time", "delete", "clear"}


@lru_cache(maxsize=1)
def font():
    return ImageFont.truetype(str(FONT), 16)


@lru_cache(maxsize=64)
def emoji(char, size):
    # pypixelcolor keeps the file on disk but decodes and resizes it on every call
    return get_emoji_image(char, size=size)


def paint(img, rows, x0, color):
    """Draw preview rows into img at x0: "1" pixels take color, others keep their own."""
    px, rgb = img.load(), tuple(bytes.fromhex(color))
    for y, row in enumerate(rows):
        for i, c in enumerate(row):
            if c and 0 <= x0 + i < img.width:
                px[x0 + i, y] = rgb if c == "1" else tuple(bytes.fromhex(c))


ble_lock = threading.Lock()  # the panel takes one BLE connection at a time
last_stars = None
# nothing on screen until told: the control page's server restores the last screen on
# start, so starting on stars would flash them first
mode = None
# what the preview needs to look like the panel. Brightness and power are the last values set
panel = {"stars_color": "ffd700", "brightness": 100, "power": True}


client = None
COMMAND_TIMEOUT = 30  # seconds, so a send that hangs doesn't block every later command


def dimmed(hex_string, ext):
    # The panel's brightness only dims its own text and shows images and GIFs as sent.
    # So the Pi darkens what it draws: 50% (the slider's floor) is 20% intensity.
    f = 0.2 + 0.8 * (min(100, max(50, panel["brightness"])) - 50) / 50
    if f >= 0.999:
        return hex_string
    src = Image.open(io.BytesIO(bytes.fromhex(hex_string)))
    frames, durations = [], []
    for i in range(getattr(src, "n_frames", 1)):
        src.seek(i)
        frames.append(src.convert("RGB").point(lambda v: round(v * f)))
        durations.append(src.info.get("duration", 100))
    buf = io.BytesIO()
    if len(frames) > 1:
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0)
    else:
        frames[0].save(buf, "GIF" if ext == ".gif" else "PNG")
    return buf.getvalue().hex()


def run(name, kwargs):
    # One connection kept open: connecting and disconnecting per command made the
    # panel flash its own screen and the saved power-on animation in between.
    global client
    if name == "send_image_hex" and kwargs.get("save_slot", 0) == 0:
        # shown now (not saved as the power-on screen): dim it to the brightness
        kwargs = {**kwargs, "hex_string": dimmed(kwargs["hex_string"], kwargs.get("file_extension", ".png"))}
    with ble_lock:
        for attempt in (1, 2):
            try:
                if client is None:
                    client = Client(ADDRESS)
                    client.connect()
                pool = ThreadPoolExecutor(1)
                try:
                    return pool.submit(getattr(client, name), **kwargs).result(timeout=COMMAND_TIMEOUT)
                finally:
                    pool.shutdown(wait=False)
            except (TypeError, ValueError):
                raise  # bad arguments, not a dropped connection
            except Exception:
                # disconnect in the background: on a hung link it can hang too
                stale, client = client, None
                if stale is not None:
                    threading.Thread(target=drop, args=(stale,), daemon=True).start()
                if attempt == 2:
                    raise


def drop(stale):
    # each Client runs its own event loop thread, which disconnect() leaves running
    try:
        stale.disconnect()
    finally:
        stale._cleanup_loop()


def fetch_stars():
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}",
                                 headers={"Accept": "application/vnd.github+json"})
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["stargazers_count"]


def stars_frame(stars, color="ffd700", size=(64, 16), icon=10):
    # send_text draws emoji at the full 16px height, dwarfing the digits, so draw
    # the whole frame ourselves: a small 👍 next to the count, centered.
    img = Image.new("RGB", size)
    thumb = emoji("👍", icon).convert("RGBA")
    text = str(stars)
    left, top, right, bottom = font().getbbox(text)
    x = (size[0] - (icon + 2 + right - left)) // 2
    img.paste(thumb, (x, (size[1] - icon) // 2), thumb)
    ImageDraw.Draw(img).text((x + icon + 2 - left, (size[1] - (bottom - top)) // 2 - top), text, font=font(), fill=f"#{color}")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue().hex()


def grid(img):
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    return {"w": w, "rows": [["%02x%02x%02x" % px[x, y][:3] if px[x, y][3] > 127 and any(px[x, y][:3]) else "" for x in range(w)] for y in range(h)]}


@lru_cache(maxsize=512)
def text_preview(text):
    # Mirrors pypixelcolor's char_to_hex for a 16px panel: Unifont 16, each char in an
    # 8px cell (16px when wide), threshold 128. Emoji are 16px Twemoji images.
    # Cached, so callers must not change what it returns.
    # shortcut: one code point per glyph, so multi-code-point emoji (flags, skin tones) split
    cells = []
    for ch in text[:200]:
        if is_emoji(ch) and (img := emoji(ch, 16)) is not None:
            cells.append(grid(img)["rows"])
            continue
        left, _, right, _ = font().getbbox(ch)
        wide = unicodedata.east_asian_width(ch) in ("W", "F") or right - left > 10
        img = Image.new("L", (16 if wide else 8, 16), 0)
        ImageDraw.Draw(img).text((0, 0), ch, fill=255, font=font())
        cells.append([["1" if img.getpixel((x, y)) >= 128 else "" for x in range(img.width)] for y in range(16)])
    rows = [sum((c[y] for c in cells), []) for y in range(16)]
    return {"w": len(rows[0]), "rows": rows}


# What the panel shows now, as an image, so a mode switch can wipe from it to the new
# screen like the app's preview does: a left-to-right sweep with a white edge.
screen = {"img": None}
WIPE_FRAMES, WIPE_MS = 8, 40  # the preview's wipe takes 320 ms too


def image_of(hex_string):
    return Image.open(io.BytesIO(bytes.fromhex(hex_string))).convert("RGB")  # first frame of a GIF


def text_image(args):
    # send_text (its arguments) as a still: the first 64px of the text in the panel's font, centered when shorter
    rows = text_preview(str(args.get("text", "")) or " ")["rows"]
    return frame_image([r[:64] for r in rows], str(args.get("color", "ffffff")).removeprefix("#"))


def wipe(new):
    old = screen["img"]
    if old is None or old.tobytes() == new.tobytes():
        return
    frames = []
    for k in range(1, WIPE_FRAMES + 1):
        edge = round(k * 64 / WIPE_FRAMES)
        f = old.copy()
        f.paste(new.crop((0, 0, edge, 16)), (0, 0))
        if edge < 64:
            for y in range(16):
                f.putpixel((edge, y), (255, 255, 255))  # always a white edge, whatever the screens' colors
        frames.append(f)
    buf = io.BytesIO()
    # the last frame holds the new screen for minutes, so the loop never restarts before
    # the real screen arrives
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=[WIPE_MS] * (WIPE_FRAMES - 1) + [600_000], loop=0)
    run("send_image_hex", {"hex_string": buf.getvalue().hex(), "file_extension": ".gif"})
    time.sleep(WIPE_FRAMES * WIPE_MS / 1000)
    screen["img"] = new


def show_stars(force=False, switching=False, fetch=True):
    global last_stars
    # fetch=False redraws the last count, e.g. on a brightness change, without asking GitHub
    stars = fetch_stars() if fetch or last_stars is None else last_stars
    if mode == "stars" and (force or stars != last_stars):
        hex_string = stars_frame(stars, panel["stars_color"])
        if switching:
            wipe(image_of(hex_string))
        run("send_image_hex", {"hex_string": hex_string, "file_extension": ".png"})
        screen["img"] = image_of(hex_string)
    last_stars = stars
    return stars


clock = {"color": "6fb6ff", "h24": True, "blink": True}


def clock_text(now, colon=True):
    hour = now.hour if clock["h24"] else now.hour % 12 or 12
    return f"{hour:02d}{':' if colon else ' '}{now.minute:02d}"


def frame_image(rows, color):
    # a preview grid, centered on the 64×16 panel, where "1" pixels take the given color
    img = Image.new("RGB", (64, 16))
    paint(img, rows, (64 - len(rows[0])) // 2, color)
    return img


def clock_frame(now):
    # Drawn by the Pi with the preview's renderer, so the page shows exactly this.
    # A blinking colon is a two-frame GIF, and the Pi sends a new one every minute.
    frames = [frame_image(text_preview(clock_text(now, colon))["rows"], clock["color"]) for colon in ((True, False) if clock["blink"] else (True,))]
    buf = io.BytesIO()
    if len(frames) > 1:
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=500, loop=0)
        return buf.getvalue().hex(), ".gif"
    frames[0].save(buf, "PNG")
    return buf.getvalue().hex(), ".png"


def show_clock(switching=False):
    hex_string, ext = clock_frame(datetime.now())
    if switching:
        wipe(image_of(hex_string))
    run("send_image_hex", {"hex_string": hex_string, "file_extension": ext})
    screen["img"] = image_of(hex_string)


# weather, calendar, night mode, the busy light and npm, set from the settings page through /config
config = {
    "weather": {"name": None, "lat": None, "lon": None, "color": "ffffff"},
    "calendar": {"url": None, "color": "f0b049"},
    "night": {"enabled": False, "off": "23:00", "on": "07:00"},
    # the busy light: work calendars' links, switch to it by itself, minutes that count as soon
    "busy": {"urls": [], "auto": True, "soon": 15, "force": False},
    # period is one of features.NPM_PERIODS
    "npm": {"package": None, "period": "last-week", "color": "cb3837"},
}
ics_cache = {}  # url -> (fetched at, ics bytes), shared by the calendar screen and the busy light
busy = {"state": "free", "at": None, "auto_from": None}  # auto_from: the screen to go back to
cache = {"weather": None, "weather_at": 0}
drawn = {}  # what each screen last drew, to skip identical redraws


def ics_for(url):
    """The calendar at url, fetched at most every 10 minutes: (fetched at, ics bytes), (0, None) before the first fetch."""
    at, ics = ics_cache.get(url, (0, None))
    if ics is None or time.time() - at > 600:
        try:
            at, ics = time.time(), features.fetch_ics(url)
            ics_cache[url] = (at, ics)
        except Exception as e:
            print(f"calendar fetch failed: {e}", flush=True)
    return at, ics


def compose(icon, text, color, size=10):
    # a small icon left of the text, centered as one group, with the text in the panel's font
    rows = text_preview(text)["rows"]
    img = Image.new("RGB", (64, 16))
    x = (64 - (size + 2 + len(rows[0]))) // 2
    if (icon_img := emoji(icon, size)) is not None:
        icon_img = icon_img.convert("RGBA")
        img.paste(icon_img, (x, (16 - size) // 2), icon_img)
    paint(img, rows, x + size + 2, color)
    return img


def weather_data():
    w = config["weather"]
    if w["lat"] is None:
        return None
    if cache["weather"] is None or time.time() - cache["weather_at"] > 600:
        try:
            cache["weather"], cache["weather_at"] = features.fetch_weather(w["lat"], w["lon"]), time.time()
        except Exception as e:
            print(f"weather fetch failed: {e}", flush=True)
    return cache["weather"]


def weather_screen():
    if config["weather"]["lat"] is None:
        return "☁", "no loc"
    data = weather_data()
    return features.weather_icon(data["code"] if data else -1), features.weather_text(data)


def calendar_screen():
    url = config["calendar"]["url"]
    if not url:
        cache.update(title=None, calendar_key=None)  # no second page left over from the last calendar
        return "📅", "no cal"
    at, ics = ics_for(url)
    if ics is None:
        cache.update(title=None, calendar_key=None)
        return "📅", "--"
    now = datetime.now().astimezone()
    # expanding the calendar takes up to a second on the Pi, and its answer holds for the minute
    key = (url, at, now.strftime("%Y%m%d%H%M"))
    if cache.get("calendar_key") == key:
        return "📅", cache["calendar_text"]
    try:
        event = features.next_event(ics, now)
        # the title becomes the screen's second page
        cache["title"] = event[2].strip() if event and event[2] else None
        cache["calendar_key"], cache["calendar_text"] = key, features.calendar_text(event, now)
        return "📅", cache["calendar_text"]
    except Exception as e:
        print(f"calendar parse failed: {e}", flush=True)
        cache["title"] = None
        return "📅", "--"


def npm_screen():
    n = config["npm"]
    if not n["package"]:
        return "📦", "no pkg"
    # npm counts a day once it's over, so an hourly check is plenty
    key = (n["package"], n["period"])
    if cache.get("npm_key") != key or time.time() - cache.get("npm_at", 0) > 3600:
        try:
            cache["npm"], cache["npm_at"], cache["npm_key"] = features.fetch_npm(*key), time.time(), key
        except Exception as e:
            print(f"npm fetch failed: {e}", flush=True)
    return "📦", features.npm_text(cache.get("npm") if cache.get("npm_key") == key else None)


# The calendar's second page, the event title. A title that fits is shown still and
# centered. A longer one starts left-aligned, scrolls slowly until its end is in view
# and pauses at both ends, so it can be read. The preview (web/src/utils/led.ts) plays
# the same timing.
TITLE_HOLD_MS = 4000  # the countdown page
TITLE_STILL_MS = 3000  # a title that fits
TITLE_PAUSE_MS = 1500  # a long title, at its start and at its end
TITLE_MS = 80  # per pixel of scroll, about 12 px a second: slow enough to read


def title_rows(title):
    return text_preview(title[:40])["rows"]


def two_pages(first, title, color):
    rows = title_rows(title)
    tw = len(rows[0])
    # the title is drawn once, and each frame is a 64px window onto it
    strip = Image.new("RGB", (tw, 16))
    paint(strip, rows, 0, color)

    def at(x):
        f = Image.new("RGB", (64, 16))
        f.paste(strip, (x, 0))
        return f

    frames, durations = [first], [TITLE_HOLD_MS]
    if tw <= 64:
        frames.append(at((64 - tw) // 2))
        durations.append(TITLE_STILL_MS)
    else:
        overflow = tw - 64
        frames += [at(-x) for x in range(overflow + 1)]
        durations += [TITLE_PAUSE_MS] + [TITLE_MS] * (overflow - 1) + [TITLE_PAUSE_MS]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0)
    return buf.getvalue().hex()


SCREENS = {"weather": weather_screen, "calendar": calendar_screen, "npm": npm_screen}


# The busy light: the whole panel glows green (free), orange (a work meeting starts within
# a few minutes) or red (in one), breathing on a sine. The panel plays a GIF smoothly only
# at about a third of a second per frame or slower, so every frame is 333 ms and a faster
# breath has fewer steps. LEDs dim linearly but eyes don't, so the steps are even as seen
# (gamma 2.2). The preview draws the same steps (web/src/utils/led.ts, glowFrame), in seen
# values, which a screen shows as these. pypixelcolor sends a GIF in 12 KB windows, and one
# that needs two windows doesn't always play, so each breath stays under 12 KB as sent
# (about 0.6 KB a frame). Step counts are even, since an odd one merges the two dimmest
# frames into one long one.
GLOW = {"free": ("00ff30", 10, 0.8), "soon": ("ff7a00", 6, 0.6), "busy": ("ff0000", 8, 0.6)}  # color, steps per breath, dimmest as seen
GLOW_MS = 333
GAMMA = 2.2


def glow_seen(state, t):
    """How bright the glow looks at time t, 0..1, in even steps."""
    _, steps, low = GLOW[state]
    step = int(t // GLOW_MS) % steps
    return low + (1 - low) * (0.5 + 0.5 * math.cos(step / steps * 2 * math.pi))


# a soft glow from the middle, down to 35% as seen at the edges, so it still shows at the
# dimmest step and a low brightness, and grows and shrinks as it breathes. Rounded to 64 shades, which halves the GIF,
# and gamma-corrected like the breath, so the panel shows the falloff the preview draws.
GLOW_FALLOFF = [[(round(max(0.3, 1 - math.hypot((x - 31.5) / 32, (y - 7.5) / 8) * 0.65) * 64) / 64) ** GAMMA for x in range(64)] for y in range(16)]


def glow_image(state, t=0):
    # the panel's value for how bright it should look: LEDs give light in proportion to the value
    rgb, v = bytes.fromhex(GLOW[state][0]), glow_seen(state, t) ** GAMMA
    img = Image.new("RGB", (64, 16))
    px = img.load()
    for y, row in enumerate(GLOW_FALLOFF):
        for x, f in enumerate(row):
            px[x, y] = tuple(round(c * v * f) for c in rgb)
    return img


@lru_cache(maxsize=None)
def glow_gif(state):
    # the same for every send of a state, so drawn once
    frames = [glow_image(state, i * GLOW_MS) for i in range(GLOW[state][1])]
    buf = io.BytesIO()
    # optimize=False keeps every step, so the panel gets them all at an even pace
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=GLOW_MS, loop=0, optimize=False)
    return frames[0], buf.getvalue().hex()


def busy_now():
    """free / soon / busy across the work calendars. The manual switch counts as busy."""
    b = config["busy"]
    if b["force"]:
        return "busy", None
    now = datetime.now().astimezone()
    fetched = [(url, *ics_for(url)) for url in b["urls"]]
    # like the calendar screen: the answer holds for the minute and these calendars
    key = (now.strftime("%Y%m%d%H%M"), b["soon"], tuple((url, at) for url, at, _ in fetched))
    if busy.get("key") == key:
        return busy["answer"]
    try:
        busy["key"], busy["answer"] = key, features.busy_state([ics for _, _, ics in fetched if ics is not None], now, b["soon"])
        return busy["answer"]
    except Exception as e:
        print(f"busy state failed: {e}", flush=True)
        return "free", None


def show_busy(switching=False):
    state, at = busy_now()
    busy.update(state=state, at=at.isoformat(timespec="minutes") if at else None)
    first, hex_string = glow_gif(state)
    if switching:
        wipe(first)
    run("send_image_hex", {"hex_string": hex_string, "file_extension": ".gif"})
    screen["img"] = first
    drawn["busy"] = state


last_text = {}  # the last send_text arguments, to put text back after the busy light


def redraw(m, switching=False):
    """Draw screen m again, as its own endpoint would."""
    if m == "stars":
        show_stars(force=True, switching=switching, fetch=False)
    elif m == "clock":
        show_clock(switching=switching)
    elif m in SCREENS:
        show_screen(m, switching=switching)
    elif m == "busy":
        show_busy(switching=switching)
    elif m == "send_text" and last_text:
        still = text_image(last_text)
        if switching:
            wipe(still)
        run("send_text", last_text)
        screen["img"] = still


def busy_tick():
    # automatic busy light: take over for soon/busy, go back to the previous screen after
    global mode
    b = config["busy"]
    if not (b["urls"] or b["force"]):
        return
    state, _ = busy_now()
    if mode == "busy":
        if busy["auto_from"] and state == "free" and not b["force"]:
            back, busy["auto_from"] = busy["auto_from"], None
            redraw(back, switching=True)
            mode = back
        elif drawn.get("busy") != state:
            show_busy(switching=True)
    elif b["auto"] and state in ("soon", "busy") and mode is not None:
        busy["auto_from"] = mode
        show_busy(switching=True)
        mode = "busy"


def show_screen(name, force=True, switching=False):
    icon, text = SCREENS[name]()
    color = config[name]["color"]
    title = cache.get("title") if name == "calendar" else None
    if not force and drawn.get(name) == (icon, text, color, title):
        return
    img = compose(icon, text, color)
    if switching:
        wipe(img)
    if title:
        run("send_image_hex", {"hex_string": two_pages(img, title, color), "file_extension": ".gif"})
    else:
        buf = io.BytesIO()
        img.save(buf, "PNG")
        run("send_image_hex", {"hex_string": buf.getvalue().hex(), "file_extension": ".png"})
    screen["img"] = img
    drawn[name] = (icon, text, color, title)


def set_power(on):
    run("set_power", {"on": on})
    panel["power"] = on


def night_tick(now):
    n = config["night"]
    if not n["enabled"]:
        return
    hm = now.strftime("%H:%M")
    if hm == n["off"] and panel["power"]:
        set_power(False)
    elif hm == n["on"] and not panel["power"]:
        set_power(True)


def tick_loop():
    # once a minute, just after it turns: night mode, then redraw what changes over time
    while True:
        time.sleep(60 - datetime.now().second + 0.2)
        now = datetime.now()
        try:
            night_tick(now)
            busy_tick()
            if mode == "clock":
                show_clock()
            elif mode in SCREENS:
                show_screen(mode, force=False)
        except Exception as e:
            print(f"tick failed: {e}", flush=True)


def link_loop():
    # A panel that loses power drops the link and starts again on its power-on screen, where
    # a screen that rarely changes would stay until its next change. So once the panel shows
    # up again, put back its brightness, power and screen. It only advertises while nothing is
    # connected, and a scan starts no Client, so nothing piles up while it is unplugged.
    while True:
        time.sleep(10)
        c = client
        # pypixelcolor 0.5 has no public link state, but its session clears this flag on a drop
        if mode is None or (c is not None and c._session.is_connected):
            continue
        try:
            if ADDRESS.upper() not in {d.address.upper() for d in Client.scan(timeout=3)}:
                continue
            run("set_brightness", {"level": panel["brightness"]})
            if panel["power"]:
                redraw(mode)
            else:
                run("set_power", {"on": False})
            print(f"panel back, showing {mode} again", flush=True)
        except Exception as e:
            print(f"panel restore failed: {e}", flush=True)


def apply_config(body):
    if "weather" in body:
        w = body["weather"] or {}
        lat, lon = w.get("lat"), w.get("lon")
        if lat is not None and not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
            raise ValueError("lat/lon out of range")
        config["weather"].update(name=w.get("name"), lat=None if lat is None else float(lat), lon=None if lon is None else float(lon))
        cache["weather"] = None
    if "calendar" in body:
        url = (body["calendar"] or {}).get("url") or None
        if url and not re.match(r"^(https?|webcal)://", url.strip()):
            raise ValueError("calendar url must start with https:// or webcal://")
        config["calendar"]["url"] = url.strip() if url else None
    if "npm" in body:
        n = {**config["npm"], **(body["npm"] or {})}
        if n["package"] is not None and not features.NPM_NAME.match(str(n["package"])):
            raise ValueError("npm package must look like name or @scope/name")
        if n["period"] not in features.NPM_PERIODS:
            raise ValueError(f"npm period must be one of {', '.join(features.NPM_PERIODS)}")
        config["npm"].update(package=n["package"], period=n["period"])
    if "night" in body:
        n = {**config["night"], **(body["night"] or {})}
        if not (features.HM.match(n["off"]) and features.HM.match(n["on"])) or n["off"] == n["on"]:
            raise ValueError("night times must be HH:MM and differ")
        config["night"].update(enabled=bool(n["enabled"]), off=n["off"], on=n["on"])
        # turned on inside the window: go dark now rather than at the next boundary
        if config["night"]["enabled"] and features.in_night(datetime.now(), n["off"], n["on"]) and panel["power"]:
            set_power(False)
    if "busy" in body:
        b = {**config["busy"], **(body["busy"] or {})}
        urls = [u.strip() for u in b.get("urls") or [] if isinstance(u, str) and re.match(r"^(https?|webcal)://", u.strip())]
        config["busy"].update(urls=urls, auto=bool(b["auto"]), soon=max(1, min(30, int(b["soon"]))), force=bool(b["force"]))
    drawn.clear()
    if mode in SCREENS:
        show_screen(mode)
    elif mode == "busy":
        show_busy()


def public_config():
    # the calendar link is private, and the page only needs to know one is set
    b = config["busy"]
    return {
        **config,
        "calendar": {"color": config["calendar"]["color"], "set": bool(config["calendar"]["url"])},
        "busy": {"calendars": len(b["urls"]), "auto": b["auto"], "soon": b["soon"], "force": b["force"], "state": busy["state"], "at": busy["at"]},
    }


def marked_grid(img_for_color):
    # pixels drawn in a marker color come back as "1", so the page can color them live
    g = grid(img_for_color("ff00ff"))
    g["rows"] = [["1" if c == "ff00ff" else c for c in row] for row in g["rows"]]
    return g


def hex_color(body, default):
    color = str(body.get("color", default)).removeprefix("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", color):
        raise ValueError("color must be a 6-digit hex value")
    return color


def stars_loop():
    while True:
        try:
            show_stars()
        except Exception as e:
            print(f"stars job failed: {e}", flush=True)
        time.sleep(INTERVAL)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if TOKEN and self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.reply(401, {"error": "unauthorized"})
            return False
        return True

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else {}
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/preview":
            return self.reply(200, text_preview(parse_qs(url.query).get("text", [""])[0]))
        if url.path in ("/preview/weather", "/preview/calendar", "/preview/npm"):
            name = url.path.rsplit("/", 1)[1]
            icon, text = SCREENS[name]()
            g = marked_grid(lambda c: compose(icon, text, c))
            if name == "calendar" and cache.get("title"):
                # the second page, for the preview to play the same loop as the panel
                g["title"] = {"rows": title_rows(cache["title"]), "hold": TITLE_HOLD_MS, "still": TITLE_STILL_MS, "pause": TITLE_PAUSE_MS, "ms": TITLE_MS}
            return self.reply(200, g)
        if url.path == "/preview/stars":
            if last_stars is None:
                return self.reply(404, {"error": "no star count yet"})
            return self.reply(200, marked_grid(lambda c: image_of(stars_frame(last_stars, c))))
        if self.path == "/health":
            return self.reply(200, {"ok": True, "mode": mode, "repo": REPO, "stars": last_stars, "clock": clock, **panel, **public_config()})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            return
        global mode, REPO, last_stars
        try:
            body = self.read_json()
            if self.path in ("/stars", "/repo"):
                color = hex_color(body, panel["stars_color"])
                recolor, panel["stars_color"] = color != panel["stars_color"], color
                repo = body.get("repo", REPO)
                if not re.fullmatch(r"[\w.-]+/[\w.-]+", str(repo)):
                    return self.reply(400, {"error": "repo must look like owner/name"})
                if repo != REPO:
                    REPO, last_stars = repo, None
                # /repo only changes which repo is tracked, while /stars also puts it on screen
                switching = self.path == "/stars" and mode not in ("stars", None)
                if self.path == "/stars":
                    mode, busy["auto_from"] = "stars", None
                stars = show_stars(force=self.path == "/stars" or recolor, switching=switching)
                return self.reply(200, {"ok": True, "repo": REPO, "color": color, "stars": stars})
            if self.path == "/config":
                apply_config(body)
                return self.reply(200, {"ok": True, **public_config()})
            if self.path == "/busy":
                if "force" in body:
                    config["busy"]["force"] = bool(body["force"])
                show_busy(switching=mode not in ("busy", None))
                # chosen by hand: stays until another screen is picked
                mode, busy["auto_from"] = "busy", None
                return self.reply(200, {"ok": True, "mode": mode, **public_config()})
            if self.path in ("/weather", "/calendar", "/npm"):
                name = self.path[1:]
                config[name]["color"] = hex_color(body, config[name]["color"])
                show_screen(name, switching=mode not in (name, None))
                mode, busy["auto_from"] = name, None
                return self.reply(200, {"ok": True, "mode": mode, **public_config()})
            if self.path == "/clock":
                clock.update(color=hex_color(body, clock["color"]), h24=bool(body.get("h24", clock["h24"])), blink=bool(body.get("blink", clock["blink"])))
                show_clock(switching=mode not in ("clock", None))
                mode, busy["auto_from"] = "clock", None
                return self.reply(200, {"ok": True, "mode": mode, "clock": clock})
            name = self.path.removeprefix("/command/")
            if not self.path.startswith("/command/") or name not in ALLOWED:
                return self.reply(404, {"error": "unknown command", "commands": sorted(ALLOWED)})
            # a switch to text wipes to it first, then the panel draws it with its own effect
            if name == "send_text":
                still = text_image(body)
                if mode not in ("send_text", None):
                    wipe(still)
            run(name, body)
            if name == "send_text":
                screen["img"] = still
                last_text.clear()
                last_text.update(body)
            elif name == "send_image_hex" and body.get("save_slot", 0) == 0:
                try:
                    screen["img"] = image_of(str(body.get("hex_string", "")))
                except Exception:
                    screen["img"] = None  # unknown now: the next switch just doesn't wipe
            if name == "set_brightness":
                panel["brightness"] = int(body.get("level", panel["brightness"]))
                # image screens are dimmed by the Pi, so draw the current one again. The panel dims text itself
                if mode != "send_text":
                    redraw(mode)
            elif name == "set_power":
                panel["power"] = bool(body.get("on", True))
            if name not in SETTINGS:
                mode, busy["auto_from"] = name, None
            self.reply(200, {"ok": True, "mode": mode})
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            self.reply(400, {"error": str(e)})
        except Exception as e:
            self.reply(502, {"error": f"panel: {e}"})


def stop(*_):
    # close the Bluetooth link on systemctl stop/restart. A link left open keeps the
    # panel from advertising, so the next start can't find it
    if client is not None:
        try:
            client.disconnect()
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    if not ADDRESS:
        sys.exit("LED_ADDRESS is not set: put the panel's Bluetooth address in .env (.venv/bin/pypixelcolor --scan lists it)")
    signal.signal(signal.SIGTERM, stop)
    threading.Thread(target=stars_loop, daemon=True).start()
    threading.Thread(target=tick_loop, daemon=True).start()
    threading.Thread(target=link_loop, daemon=True).start()
    print(f"listening on :{PORT}, panel {ADDRESS}, repo {REPO}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
