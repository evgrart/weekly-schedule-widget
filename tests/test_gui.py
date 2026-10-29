"""Windows GUI checks using fictional data, with all network work disabled."""
from tests import support
from dataclasses import replace
from datetime import date
import re
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

from app_paths import CODE_ROOT
from calendar_core import parse_calendar
from deadline_core import parse_assignments
import widget


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.withdraw()
        self.root.tk.call('tk','scaling',1.0)
        config={'feed_url':'','refresh_seconds':120,'topmost':False,'autostart':False,
                'desktop_mode':False,'shad_enabled':True,'wide_layout_version':1,
                'bounds':[20000,20000,2200,1100]}
        with patch.object(widget.WeekWidget,'refresh'),patch.object(widget.WeekWidget,'refresh_deadlines'):
            self.app=widget.WeekWidget(self.root,config)
        self.root.title('Weekly Schedule UI Verification')
        for job in self.root.tk.call('after','info'):
            self.root.after_cancel(job)
        self.app.draw_job=None
        self.app.refresh=lambda *args:None
        self.app.refresh_deadlines=lambda *args:None
        self.app.calendar=parse_calendar((CODE_ROOT/'examples'/'demo.ics').read_bytes())
        self.app.shad_items=parse_assignments((CODE_ROOT/'examples'/'assignments.html').read_text(encoding='utf-8'))
        self.app.first_day=date(2030,1,7)
        self.app.follow_today=False
        self.root.geometry('2200x1100+20000+20000')
        self.root.deiconify()
        self.root.update()
        self.app.draw()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):
            self.root.after_cancel(job)
        self.root.destroy()

    def test_grid_groups_deadlines_and_includes_late_and_date_only_markers(self):
        app=self.app
        self.assertEqual(len(app.week_deadline_markers),3)
        self.assertEqual(app.geometry_data[5],24)
        timed=[box for box in app.deadline_boxes if not box[4].date_only]
        self.assertEqual(sorted(len(box[4].items) for box in timed),[1,2])
        self.assertTrue(any(box[4].date_only for box in app.deadline_boxes))
        for x1,y1,x2,y2,marker in app.deadline_boxes:
            self.assertEqual(app.event_at((x1+x2)/2,(y1+y2)/2),marker)
            self.assertLessEqual(y2,app.canvas.winfo_height())
        completed=[replace(item,completed=True) for item in app.shad_items]
        app.shad_items=completed
        app.draw()
        self.assertFalse(app.deadline_boxes)

    def test_marker_click_and_week_navigation(self):
        app=self.app
        box=next(box for box in app.deadline_boxes if box[4].date_only)
        x1,y1,x2,y2,marker=box
        event=SimpleNamespace(x=(x1+x2)/2,y=(y1+y2)/2,x_root=0,y_root=0)
        with patch('widget.webbrowser.open') as open_link:
            app.click_event(event)
        open_link.assert_called_once_with(marker.items[0].url)
        app.change_week(1)
        self.assertFalse(app.deadline_boxes)
        app.change_week(-1)
        self.assertEqual(len(app.deadline_boxes),3)

    def test_clock_labels_never_wrap_inside_a_timestamp(self):
        for item in self.app.canvas.find_withtag('event-time'):
            text=self.app.canvas.itemcget(item,'text')
            self.assertTrue(all(re.fullmatch(r'\d{2}:\d{2}(?:–\d{2}:\d{2})?',line)
                                for line in text.splitlines()))
            x,y=self.app.canvas.coords(item)
            cards=[box for box in self.app.event_boxes if box[0]<=x<=box[2] and box[1]<=y<=box[3]]
            self.assertTrue(cards)
            self.assertLessEqual(self.app.canvas.bbox(item)[2],max(box[2] for box in cards)+2)


if __name__=='__main__':
    unittest.main()
