"""Data for the weather, calendar and npm screens, and the night mode window. No panel code here."""
import json
import re
import urllib.request
from datetime import date, datetime, timedelta

import icalendar
import recurring_ical_events

HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# WMO weather codes (Open-Meteo) to a Twemoji the panel can draw
WEATHER_ICONS = [
    ((0,), "☀"),
    ((1, 2), "🌤"),
    ((3,), "☁"),
    ((45, 48), "🌫"),
    ((51, 53, 55, 56, 57, 61, 63, 65, 66, 67), "🌧"),
    ((71, 73, 75, 77, 85, 86), "❄"),
    ((80, 81, 82), "🌦"),
    ((95, 96, 99), "⛈"),
]


def weather_icon(code):
    return next((icon for codes, icon in WEATHER_ICONS if code in codes), "☁")


def fetch_weather(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code&timezone=auto"
    with urllib.request.urlopen(url, timeout=15) as r:
        current = json.load(r)["current"]
    return {"temp": round(current["temperature_2m"]), "code": int(current["weather_code"])}


def weather_text(data):
    return "--°" if data is None else f"{data['temp']}°"


# npm's download counts, https://github.com/npm/registry/blob/main/docs/download-counts.md
NPM_PERIODS = ("last-day", "last-week", "last-month", "last-year")
NPM_NAME = re.compile(r"^(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$")


def fetch_npm(package, period):
    with urllib.request.urlopen(f"https://api.npmjs.org/downloads/point/{period}/{package}", timeout=15) as r:
        return int(json.load(r)["downloads"])


def npm_text(n):
    """Downloads in at most 5 characters, to fit next to the icon: 999, 1.23k, 12.3k, 503k, 9.55M."""
    if n is None:
        return "--"
    if n < 1000:
        return str(n)
    for unit in "kMB":
        n /= 1000
        if n < 999.5 or unit == "B":
            return (f"{n:.2f}" if n < 9.995 else f"{n:.1f}" if n < 99.95 else f"{n:.0f}") + unit


def fetch_ics(url):
    # webcal:// is how calendar apps hand out these links, and it is plain https
    url = re.sub(r"^webcal://", "https://", url.strip())
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pi-led"}), timeout=20) as r:
        return r.read()


def _local(dt, tz):
    # all-day events are dates, and floating times have no zone and mean local time
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)


def _owner(cal):
    # Google names a calendar's feed after its owner's address, which is used to spot declined invites
    name = str(cal.get("X-WR-CALNAME", ""))
    return name.lower() if "@" in name else None


def _busy(ev, owner):
    """Whether an event should count: not cancelled, not marked free, not declined by the owner."""
    if str(ev.get("STATUS", "")).upper() == "CANCELLED" or str(ev.get("TRANSP", "")).upper() == "TRANSPARENT":
        return False
    attendees = ev.get("ATTENDEE") or []
    for a in attendees if isinstance(attendees, list) else [attendees]:
        if owner and str(a).lower().removeprefix("mailto:") == owner and str(a.params.get("PARTSTAT", "")).upper() == "DECLINED":
            return False
    return True


def next_event(ics, now):
    """The event in progress, else the next one within a week: (start, end, title) or None.
    Recurring meetings are expanded. All-day, cancelled, free and declined events are skipped."""
    cal = icalendar.Calendar.from_ical(ics)
    owner = _owner(cal)
    best = None
    for ev in recurring_ical_events.of(cal).between(now - timedelta(hours=12), now + timedelta(days=7)):
        if not _busy(ev, owner):
            continue
        start = _local(ev.get("DTSTART").dt, now.tzinfo)
        end_prop = ev.get("DTEND")
        end = _local(end_prop.dt, now.tzinfo) if end_prop else start
        if start is None or end is None or end <= now:
            continue
        if best is None or start < best[0]:
            best = (start, end, str(ev.get("SUMMARY", "")))
    return best


def calendar_text(event, now):
    """Fits the panel next to a small icon (52px, so 5 characters past an hour):
    "now", "in 12m", "1h16m", "14:30", "tmrw" or "free"."""
    if event is None:
        return "free"
    start, _end, _title = event
    if start <= now:
        return "now"
    minutes = int((start - now).total_seconds() // 60) + 1
    if minutes < 60:
        return f"in {minutes}m"
    if minutes < 600:
        return f"{minutes // 60}h{minutes % 60:02d}m"
    if start.date() == now.date():
        return start.strftime("%H:%M")
    if start.date() == now.date() + timedelta(days=1):
        return "tmrw"
    return "free"


def busy_state(calendars, now, soon_minutes=15):
    """For the busy light, across all work calendars (ics bytes): ("busy", end) while a
    meeting is on, ("soon", start) when one starts within soon_minutes, else ("free", None)."""
    events = [ev for ev in (next_event(ics, now) for ics in calendars) if ev]
    on = [ev for ev in events if ev[0] <= now < ev[1]]
    if on:
        # back-to-back or overlapping meetings: busy until the last of them ends
        return "busy", max(ev[1] for ev in on)
    upcoming = [ev[0] for ev in events if ev[0] > now]
    if upcoming and min(upcoming) - now <= timedelta(minutes=soon_minutes):
        return "soon", min(upcoming)
    return "free", None


def in_night(now, off, on):
    """Whether now (HH:MM) is inside the off window, which may run past midnight."""
    hm = now.strftime("%H:%M")
    return off <= hm < on if off < on else hm >= off or hm < on


if __name__ == "__main__":
    # self-check of the pure parts: python3 features.py
    from datetime import timezone

    tz = timezone(timedelta(hours=1))
    now = datetime(2026, 11, 3, 14, 0, tzinfo=tz)
    assert weather_icon(0) == "☀" and weather_icon(63) == "🌧" and weather_icon(999) == "☁"
    assert weather_text({"temp": 12, "code": 0}) == "12°" and weather_text(None) == "--°"
    assert npm_text(None) == "--" and npm_text(999) == "999" and npm_text(1234) == "1.23k" and npm_text(9_996) == "10.0k"
    assert npm_text(503_269) == "503k" and npm_text(999_499) == "999k" and npm_text(999_999) == "1.00M"
    assert npm_text(9_545_513) == "9.55M" and npm_text(123_456_789) == "123M"
    assert NPM_NAME.match("@kubb/core") and NPM_NAME.match("react") and not NPM_NAME.match("React") and not NPM_NAME.match("../x")
    assert calendar_text(None, now) == "free"
    assert calendar_text((now + timedelta(minutes=11, seconds=30), now, ""), now) == "in 12m"
    assert calendar_text((now - timedelta(minutes=5), now, ""), now) == "now"
    assert calendar_text((now + timedelta(minutes=75, seconds=30), now, ""), now) == "1h16m"
    assert calendar_text((now + timedelta(minutes=59), now, ""), now) == "1h00m"
    assert calendar_text((now + timedelta(minutes=57, seconds=30), now, ""), now) == "in 58m"
    assert calendar_text((now.replace(hour=17, minute=30), now, ""), now) == "3h31m"
    assert calendar_text((now.replace(hour=23, minute=59), now, ""), now.replace(hour=8)) == "23:59"
    assert calendar_text((now + timedelta(days=1), now, ""), now) == "tmrw"
    assert in_night(now.replace(hour=23, minute=30), "23:00", "07:00")
    assert in_night(now.replace(hour=6, minute=59), "23:00", "07:00")
    assert not in_night(now.replace(hour=7, minute=0), "23:00", "07:00")
    assert in_night(now.replace(hour=13, minute=0), "12:00", "14:00") and not in_night(now, "12:00", "14:00")
    ics = b"""BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:a\r\nDTSTART:20261103T130000Z\r\nDTEND:20261103T133000Z\r\nRRULE:FREQ=DAILY\r\nSUMMARY:Standup\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:b\r\nDTSTART;VALUE=DATE:20261103\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"""
    ev = next_event(ics, now)
    assert ev and ev[2] == "Standup" and ev[0] == datetime(2026, 11, 3, 14, 0, tzinfo=tz), ev  # 13:00Z daily = 14:00 here
    assert calendar_text(ev, now) == "now"
    ev = next_event(ics, now + timedelta(hours=1))
    assert ev[0].date() == date(2026, 11, 4) and calendar_text(ev, now + timedelta(hours=1)) == "tmrw"
    # cancelled, free and declined-by-owner events don't count, but a plain one at 16:00 does
    skip = b"""BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:me@example.com\r\n""" + b"".join(
        b"BEGIN:VEVENT\r\nUID:" + uid + b"\r\nDTSTART:20261103T" + hm + b"00Z\r\nDTEND:20261103T" + hm[:2] + b"5900Z\r\n" + extra + b"END:VEVENT\r\n"
        for uid, hm, extra in [
            (b"c", b"1330", b"STATUS:CANCELLED\r\n"),
            (b"f", b"1400", b"TRANSP:TRANSPARENT\r\n"),
            (b"d", b"1430", b"ATTENDEE;PARTSTAT=DECLINED:mailto:me@example.com\r\nATTENDEE;PARTSTAT=ACCEPTED:mailto:you@example.com\r\n"),
            (b"o", b"1500", b"ATTENDEE;PARTSTAT=ACCEPTED:mailto:me@example.com\r\n"),
        ]
    ) + b"END:VCALENDAR\r\n"
    ev = next_event(skip, now)
    assert ev and ev[0] == datetime(2026, 11, 3, 16, 0, tzinfo=tz), ev
    # busy light: standup 14:00-14:30 here (13:00Z), the skip calendar's real one at 16:00
    assert busy_state([ics], now) == ("busy", datetime(2026, 11, 3, 14, 30, tzinfo=tz))
    assert busy_state([skip], now.replace(hour=15, minute=56)) == ("soon", datetime(2026, 11, 3, 16, 0, tzinfo=tz))
    assert busy_state([skip], now.replace(hour=15, minute=40))[0] == "free"
    assert busy_state([], now) == ("free", None)
    assert busy_state([ics, skip], now.replace(hour=14, minute=10))[0] == "busy"
    print("features ok")
