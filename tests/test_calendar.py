"""Regression checks for live-feed replacement, exceptions, layout and GUI navigation."""
from tests import support
from datetime import datetime, timedelta, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import threading
import unittest
from unittest.mock import patch
from desktop_anchor import wait_for_desktop

from calendar_core import MOSCOW, Appointment, fetch_calendar, parse_calendar, week_events, arrange, monday


def sample(updated=False):
    # A recurring class with a moved occurrence; a second class is removed on refresh.
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Widget verification//EN",
             "BEGIN:VEVENT", "UID:recurring-test", "DTSTAMP:20261028T000000Z",
             "DTSTART:20261026T150000Z", "DTEND:20261026T180000Z", "RRULE:FREQ=WEEKLY;COUNT=3",
             "SUMMARY:Recurring", "END:VEVENT", "BEGIN:VEVENT", "UID:recurring-test",
             "DTSTAMP:20261028T000000Z", "RECURRENCE-ID:20261102T150000Z",
             "DTSTART:20261102T160000Z", "DTEND:20261102T180000Z", "SUMMARY:Moved", "END:VEVENT"]
    if updated:
        lines += ["BEGIN:VEVENT", "UID:new-test", "DTSTAMP:20261028T000000Z",
                  "DTSTART:20261028T150000Z", "DTEND:20261028T180000Z", "SUMMARY:New", "END:VEVENT"]
    else:
        lines += ["BEGIN:VEVENT", "UID:removed-test", "DTSTAMP:20261028T000000Z",
                  "DTSTART:20261027T150000Z", "DTEND:20261027T180000Z", "SUMMARY:Remove me", "END:VEVENT"]
    lines += ["END:VCALENDAR", ""]
    return "\r\n".join(lines).encode()


class Checks(unittest.TestCase):
    def test_waits_for_late_desktop_and_handles_timeout(self):
        with patch("desktop_anchor.desktop_host",side_effect=[None,None,123]):
            self.assertEqual(wait_for_desktop(timeout=1,poll=0),123)
        with patch("desktop_anchor.desktop_host",return_value=None):
            self.assertIsNone(wait_for_desktop(timeout=0,poll=0))

    def test_refetch_replaces_deleted_and_added_events(self):
        class Handler(BaseHTTPRequestHandler):
            counter=0
            def do_GET(self):
                payload=sample(updated=Handler.counter>0)
                Handler.counter+=1
                self.send_response(200)
                self.send_header("Content-Type","text/calendar")
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self,*args):
                pass
        server=HTTPServer(("127.0.0.1",0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            url=f"http://127.0.0.1:{server.server_port}/calendar.ics"
            _,before=fetch_calendar(url)
            _,after=fetch_calendar(url)
            a={e.uid for e in week_events(before,datetime(2026,10,26).date())}
            b={e.uid for e in week_events(after,datetime(2026,10,26).date())}
            self.assertIn("removed-test",a)
            self.assertNotIn("removed-test",b)
            self.assertIn("new-test",b)
        finally:
            server.shutdown()
            server.server_close()

    def test_exception_and_moscow_conversion(self):
        events=week_events(parse_calendar(sample()),datetime(2026,11,2).date())
        self.assertEqual(len(events),1)
        self.assertEqual(events[0].title,"Moved")
        self.assertEqual(events[0].start.hour,19)
        self.assertEqual(events[0].end.hour,21)

    def test_overlap_lanes_and_touching_edges(self):
        day=datetime(2026,10,28).date()
        def event(uid,begin,end):
            return Appointment(uid,uid,datetime.combine(day,time(begin),MOSCOW),datetime.combine(day,time(end),MOSCOW))
        placed=arrange([event("one",17,19),event("two",18,21),event("three",19,20),event("four",21,22)],day)
        self.assertEqual([x[4] for x in placed],[2,2,2,1])
        for i,a in enumerate(placed):
            for b in placed[i+1:]:
                if a[1] < b[2] and b[1] < a[2]:
                    self.assertNotEqual(a[3],b[3])

    def test_all_day_and_cancelled(self):
        raw=b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:all-day\r\nDTSTART;VALUE=DATE:20261028\r\nDTEND;VALUE=DATE:20261029\r\nSUMMARY:All day\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:cancelled\r\nDTSTART:20261028T150000Z\r\nDTEND:20261028T180000Z\r\nSTATUS:CANCELLED\r\nSUMMARY:Cancelled\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        events=week_events(parse_calendar(raw),datetime(2026,10,26).date())
        self.assertEqual(len(events),1)
        self.assertTrue(events[0].all_day)


if __name__=="__main__":
    unittest.main(verbosity=2)
