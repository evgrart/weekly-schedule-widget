from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import hashlib
import sys

from app_paths import DATA_ROOT as ROOT
from icalendar import Calendar
import recurring_ical_events

MOSCOW = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class Appointment:
    uid: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False

    @property
    def shad(self):
        title = self.title.casefold().strip()
        return ("шад" in title or "shad" in self.uid.casefold() or "dataschool" in self.uid.casefold()
                or title in {"c++", "алгоритмы", "ml и теория информации"})


def monday(day):
    return day - timedelta(days=day.weekday())


def parse_calendar(data):
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("calendar_too_large")
    if not data.lstrip(b"\xef\xbb\xbf\r\n ").startswith(b"BEGIN:VCALENDAR"):
        raise ValueError("not_a_calendar")
    calendar = Calendar.from_ical(data)
    if calendar.name != "VCALENDAR":
        raise ValueError("not_a_calendar")
    return calendar


def fetch_calendar(url):
    request = Request(url, headers={"User-Agent": "WeeklyScheduleWidget/1.0",
                                   "Accept": "text/calendar", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=20) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    return data, parse_calendar(data)


def week_events(calendar, first_day):
    begin = datetime.combine(first_day, time.min, MOSCOW)
    finish = begin + timedelta(days=7)
    result = []
    for event in recurring_ical_events.of(calendar).between(begin, finish):
        if str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start = event.decoded("DTSTART")
        all_day = not isinstance(start, datetime)
        end = event.decoded("DTEND") if "DTEND" in event else None
        if all_day:
            end = end or start + timedelta(days=1)
            start = datetime.combine(start, time.min, MOSCOW)
            end = datetime.combine(end, time.min, MOSCOW)
        else:
            start = start.replace(tzinfo=MOSCOW) if start.tzinfo is None else start.astimezone(MOSCOW)
            end = end or start + event.decoded("DURATION", timedelta(minutes=30))
            end = end.replace(tzinfo=MOSCOW) if end.tzinfo is None else end.astimezone(MOSCOW)
        result.append(Appointment(str(event.get("UID", "")), str(event.get("SUMMARY", "Без названия")),
                                  start, end, all_day))
    return sorted(result, key=lambda e: (e.start, e.end, e.title))


def day_events(events, day):
    begin = datetime.combine(day, time.min, MOSCOW)
    end = begin + timedelta(days=1)
    return [e for e in events if not e.all_day and e.start < end and e.end > begin]


def arrange(events, day):
    """Allocate lanes per connected overlap group; touching edges don't overlap."""
    begin = datetime.combine(day, time.min, MOSCOW)
    finish = begin + timedelta(days=1)
    items = [(e, max(e.start, begin), min(e.end, finish)) for e in events]
    items.sort(key=lambda item: (item[1], item[2], item[0].title))
    groups, current, limit = [], [], None
    for item in items:
        if current and item[1] >= limit:
            groups.append(current)
            current = []
        current.append(item)
        limit = max([x[2] for x in current])
    if current:
        groups.append(current)
    result = []
    for group in groups:
        lane_ends, placed = [], []
        for event, start, end in group:
            lane = next((i for i, last in enumerate(lane_ends) if last <= start), len(lane_ends))
            if lane == len(lane_ends):
                lane_ends.append(end)
            else:
                lane_ends[lane] = end
            placed.append((event, start, end, lane))
        result.extend((e, s, f, lane, len(lane_ends)) for e, s, f, lane in placed)
    return result


def cache_path(url):
    return ROOT / ("cache-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".ics")
