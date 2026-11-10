"""Calendar source for ICS feeds: Google Calendar, Outlook/Office 365, iCloud shared calendars, school timetables.

Standard library only, read-only. scripts/export_calendar.py uses it when PM_CALENDAR_SOURCES contains "ics".
Feeds are listed in ics_feeds.txt (PM_ICS_FILE), one per line:

    Work      | https://outlook.office365.com/owa/calendar/.../calendar.ics
    Family    | webcal://p01-caldav.icloud.com/published/2/...
    Timetable | ~/Downloads/timetable.ics

Where to find the link: Google Calendar > Settings > (calendar) > "Secret address in iCal format";
Outlook on the web > Settings > Calendar > Shared calendars > Publish a calendar > ICS. A secret link is a
password: keep ics_feeds.txt private (it is gitignored).

Handles line folding, escaping, TZID (IANA names and the common Windows names Outlook uses), all-day events,
RRULE (DAILY/WEEKLY/MONTHLY/YEARLY with INTERVAL, COUNT, UNTIL, BYDAY, BYMONTHDAY, BYMONTH), EXDATE,
RECURRENCE-ID overrides and cancelled events. Produces the same raw records as the EventKit reader.
"""
import re
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Outlook writes Windows zone names. The common ones; anything unknown falls back to local time.
WINDOWS_TZ = {
    "W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest", "Central European Standard Time": "Europe/Warsaw",
    "GMT Standard Time": "Europe/London", "Greenwich Standard Time": "Atlantic/Reykjavik",
    "E. Europe Standard Time": "Europe/Chisinau", "FLE Standard Time": "Europe/Kiev", "GTB Standard Time": "Europe/Athens",
    "Russian Standard Time": "Europe/Moscow", "Turkey Standard Time": "Europe/Istanbul",
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix", "Atlantic Standard Time": "America/Halifax",
    "SA Pacific Standard Time": "America/Bogota", "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires", "Mexico Standard Time": "America/Mexico_City",
    "India Standard Time": "Asia/Kolkata", "China Standard Time": "Asia/Shanghai", "Tokyo Standard Time": "Asia/Tokyo",
    "Singapore Standard Time": "Asia/Singapore", "Korea Standard Time": "Asia/Seoul", "Arabian Standard Time": "Asia/Dubai",
    "AUS Eastern Standard Time": "Australia/Sydney", "New Zealand Standard Time": "Pacific/Auckland",
    "South Africa Standard Time": "Africa/Johannesburg", "Israel Standard Time": "Asia/Jerusalem",
    "UTC": "UTC", "Coordinated Universal Time": "UTC",
}
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
MAX_INSTANCES = 2000   # per series: a runaway rule cannot hang the export


def read_feeds(path):
    """[(name, url_or_path)] from ics_feeds.txt; blank lines and # comments ignored."""
    out = []
    p = Path(path).expanduser()
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        name, src = (x.strip() for x in line.split("|", 1))
        if name and src:
            out.append((name, src))
    return out


def fetch(src, timeout=30):
    if re.match(r"^(https?|webcal)://", src, re.I):
        url = re.sub(r"^webcal://", "https://", src, flags=re.I)
        req = urllib.request.Request(url, headers={"User-Agent": "personal-manager-ics/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    return Path(src).expanduser().read_text(encoding="utf-8", errors="replace")


def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n").replace("\r", "\n").split("\n")


def unescape(v):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def parse_line(line):
    """'DTSTART;TZID=Europe/Berlin:20261110T090000' -> ('DTSTART', {'TZID': 'Europe/Berlin'}, '20261110T090000')."""
    m = re.match(r'^([A-Za-z0-9-]+)((?:;[^:;=]+=(?:"[^"]*"|[^:;]*))*):(.*)$', line)
    if not m:
        return None
    params = {}
    for p in re.findall(r';([^:;=]+)=("[^"]*"|[^:;]*)', m.group(2)):
        params[p[0].upper()] = p[1].strip('"')
    return m.group(1).upper(), params, m.group(3)


def zone(tzid, local):
    if not tzid:
        return local
    tzid = tzid.strip().strip("/")
    for name in (tzid, WINDOWS_TZ.get(tzid, "")):
        if name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                pass
    return local


def parse_dt(value, params, local):
    """-> (datetime aware, all_day bool). A DATE value becomes local midnight."""
    v = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
        d = datetime.strptime(v[:8], "%Y%m%d")
        return d.replace(tzinfo=local), True
    if v.endswith("Z"):
        return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc), False
    return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone(params.get("TZID"), local)), False


def parse_duration(v):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def events_of(text, local):
    """VEVENT blocks as dicts of {prop: [(params, value), ...]}."""
    out, cur, depth = [], None, 0
    for line in unfold(text):
        if line.upper() == "BEGIN:VEVENT":
            cur, depth = {}, 0
            continue
        if cur is None:
            continue
        if line.upper().startswith("BEGIN:"):
            depth += 1      # VALARM inside an event
            continue
        if line.upper().startswith("END:") and depth:
            depth -= 1
            continue
        if line.upper() == "END:VEVENT":
            out.append(cur)
            cur = None
            continue
        if depth:
            continue
        p = parse_line(line)
        if p:
            cur.setdefault(p[0], []).append((p[1], p[2]))
    return out


def first(ev, key, default=""):
    return ev[key][0][1] if key in ev else default


def nth_weekday(year, month, wd, n):
    """The n-th (1-based, negative from the end) weekday wd (0=Mon) of a month, or None."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(wd - d.weekday()) % 7 + 7 * (n - 1))
        return d if d.month == month else None
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    d -= timedelta(days=(d.weekday() - wd) % 7 + 7 * (-n - 1))
    return d if d.month == month else None


def expand(rule, start, window_end):
    """Start datetimes of a recurring series, start included, up to window_end (exclusive)."""
    r = dict(kv.split("=", 1) for kv in rule.upper().split(";") if "=" in kv)
    freq, interval = r.get("FREQ"), max(1, int(r.get("INTERVAL", "1") or 1))
    count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
    until = None
    if r.get("UNTIL"):
        u, _ = parse_dt(r["UNTIL"], {}, start.tzinfo)
        until = u if len(r["UNTIL"]) > 8 else u + timedelta(days=1) - timedelta(seconds=1)
    byday = [(int(m.group(1) or 0), DAYS.index(m.group(2)))
             for m in (re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", x) for x in r.get("BYDAY", "").split(",")) if m]
    bymd = [int(x) for x in r.get("BYMONTHDAY", "").split(",") if re.fullmatch(r"-?\d+", x)]
    bymonth = [int(x) for x in r.get("BYMONTH", "").split(",") if x.isdigit()]
    tod = start.timetz()

    def at(d):
        return datetime.combine(d, time(tod.hour, tod.minute, tod.second), tzinfo=start.tzinfo)

    def candidates():
        n, d0 = 0, start.date()
        while n < MAX_INSTANCES * 4:
            if freq == "DAILY":
                d = d0 + timedelta(days=n * interval)
                if (not bymonth or d.month in bymonth) and (not byday or d.weekday() in [w for _, w in byday]):
                    yield [d]
            elif freq == "WEEKLY":
                wk = d0 - timedelta(days=d0.weekday()) + timedelta(weeks=n * interval)
                days = sorted(w for _, w in byday) or [d0.weekday()]
                yield [wk + timedelta(days=w) for w in days]
            elif freq == "MONTHLY":
                y, m = divmod(d0.month - 1 + n * interval, 12)
                y, m = d0.year + y, m + 1
                if bymonth and m not in bymonth:
                    yield []
                elif byday:
                    got = []
                    for k, w in byday:
                        if k:
                            got.append(nth_weekday(y, m, w, k))
                        else:
                            d = date(y, m, 1)
                            while d.month == m:
                                if d.weekday() == w:
                                    got.append(d)
                                d += timedelta(days=1)
                    yield sorted(x for x in got if x)
                else:
                    got = []
                    for md in bymd or [d0.day]:
                        last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
                        day = md if md > 0 else last + md + 1
                        if 1 <= day <= last:
                            got.append(date(y, m, day))
                    yield sorted(got)
            elif freq == "YEARLY":
                y = d0.year + n * interval
                got = []
                for m in bymonth or [d0.month]:
                    if byday:
                        got += [nth_weekday(y, m, w, k or 1) for k, w in byday]
                    else:
                        for md in bymd or [d0.day]:
                            try:
                                got.append(date(y, m, md))
                            except ValueError:
                                pass
                yield sorted(x for x in got if x)
            else:
                return
            n += 1

    out, seen = [], 0
    for group in candidates():
        for d in group:
            dt = at(d)
            if dt < start:
                continue
            if (until and dt > until) or dt >= window_end:
                return out
            seen += 1
            if count is not None and seen > count:
                return out
            out.append(dt)
            if len(out) >= MAX_INSTANCES:
                return out
    return out


def raw_events(name, text, window_start, window_end, local):
    """EventKit-shaped raw records (id, title, start_ts, end_ts, all_day, calendar, source, location, notes)."""
    evs = events_of(text, local)
    overrides = {}   # (uid, original start ts) -> event
    for ev in evs:
        if "RECURRENCE-ID" in ev:
            p, v = ev["RECURRENCE-ID"][0]
            overrides[(first(ev, "UID"), parse_dt(v, p, local)[0].timestamp())] = ev
    out = []

    def emit(ev, start, all_day, length):
        if first(ev, "STATUS").upper() == "CANCELLED":
            return
        end = start + length
        if end <= window_start or start >= window_end:
            return
        out.append({
            "id": f"ics:{name}:{first(ev, 'UID') or first(ev, 'SUMMARY')}",
            "title": unescape(first(ev, "SUMMARY")),
            "start_ts": start.timestamp(),
            # EventKit ends an all-day event at 23:59:59 of its last day; match it
            "end_ts": (end - timedelta(seconds=1)).timestamp() if all_day else end.timestamp(),
            "all_day": all_day,
            "calendar": name,
            "source": "ics",
            "location": unescape(first(ev, "LOCATION")),
            "notes": unescape(first(ev, "DESCRIPTION"))[:2000],
        })

    for ev in evs:
        if "DTSTART" not in ev or "RECURRENCE-ID" in ev:
            continue
        p, v = ev["DTSTART"][0]
        start, all_day = parse_dt(v, p, local)
        if "DTEND" in ev:
            ep, evv = ev["DTEND"][0]
            length = parse_dt(evv, ep, local)[0] - start
        elif "DURATION" in ev:
            length = parse_duration(first(ev, "DURATION")) or timedelta()
        else:
            length = timedelta(days=1) if all_day else timedelta()
        if "RRULE" not in ev:
            emit(ev, start, all_day, length)
            continue
        ex = set()
        for ep, evv in ev.get("EXDATE", []):
            for one in evv.split(","):
                ex.add(parse_dt(one, ep, local)[0].timestamp())
        uid = first(ev, "UID")
        for s in expand(first(ev, "RRULE"), start, window_end):
            if s.timestamp() in ex:
                continue
            o = overrides.pop((uid, s.timestamp()), None)
            if o is not None:
                op, ov = o["DTSTART"][0] if "DTSTART" in o else (p, v)
                os_, oa = parse_dt(ov, op, local)
                if "DTEND" in o:
                    olen = parse_dt(o["DTEND"][0][1], o["DTEND"][0][0], local)[0] - os_
                else:
                    olen = length
                emit({**ev, **o}, os_, oa, olen)
            else:
                emit(ev, s, all_day, length)
    for o in overrides.values():   # a moved occurrence whose original slot was outside the expansion
        if "DTSTART" in o:
            op, ov = o["DTSTART"][0]
            os_, oa = parse_dt(ov, op, local)
            olen = parse_dt(o["DTEND"][0][1], o["DTEND"][0][0], local)[0] - os_ if "DTEND" in o else timedelta()
            emit(o, os_, oa, olen)
    for i, e in enumerate(out):
        e["id"] = f'{e["id"]}#{i}'
    return out


def read_ics(feeds, window_start, window_end):
    """(raw_events, raw_calendars) for the export, like read_eventkit. A failing feed raises with its name."""
    local = window_start.tzinfo
    events, calendars = [], []
    for name, src in feeds:
        try:
            text = fetch(src)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"ICS feed '{name}' could not be read: {e}") from e
        evs = raw_events(name, text, window_start, window_end, local)
        events += evs
        calendars.append({"title": name, "account": "ics", "type": "subscribed", "events": len(evs)})
    return events, calendars
