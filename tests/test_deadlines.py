from tests import support
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import subprocess
import sys

import deadline_core as core


def page(date='31 октября 2026 18:00', completed=False):
    status='completed' if completed else 'not-submitted'
    row=f'''<tr><td><div class="assignment-date">{date}</div></td>
    <td><a href="/learning/assignments/123/">ДЗ &amp; проверка</a></td>
    <td><a href="/courses/example/">Алгоритмы</a></td>
    <td><span class="assignment-status {status}">Выполнено</span></td><td>Через сайт</td></tr>'''
    head='<thead><tr><th>Срок сдачи</th><th></th><th>Курс</th><th>Статус</th><th>Формат задания</th></tr></thead>'
    return ('<div id="login" data-user-id="test"></div><select id="id_status"></select>'
            '<div><h3>Открытые задания</h3><table>'+head+'<tbody>'+row+'</tbody></table></div>'
            '<div><h3>Архив</h3><table>'+head+'<tbody>'+row+'</tbody></table></div>')


class Checks(unittest.TestCase):
    def test_week_markers_group_equal_times_and_exclude_completed_or_undated(self):
        first=core.parse_assignments(page())[0]
        same=replace(first,uid='second',title='Second')
        completed=replace(first,uid='done',completed=True)
        unscheduled=replace(first,uid='no-date',due=None)
        outside=replace(first,uid='next-week',due=first.due+timedelta(days=7))
        date_only=replace(first,uid='date-only',date_only=True,
                          due=first.due.replace(hour=0,minute=0))
        week=datetime(2026,10,26).date()
        markers=core.week_deadline_markers([first,same,completed,unscheduled,outside,date_only],week)
        self.assertEqual(len(markers),2)
        timed=next(marker for marker in markers if not marker.date_only)
        self.assertEqual({item.uid for item in timed.items},{first.uid,same.uid})
        self.assertEqual(timed.due.hour,18)
        self.assertTrue(any(marker.date_only for marker in markers))

    def test_background_cleanup_only_stops_its_own_job(self):
        from shad_background import OwnProcessJob
        command=[sys.executable,'-c','import time; time.sleep(30)']
        streams=dict(stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
        owned=subprocess.Popen(command,**streams)
        unrelated=subprocess.Popen(command,**streams)
        job=OwnProcessJob()
        try:
            job.assign(owned)
            job.close()
            self.assertIsNotNone(owned.wait(timeout=5))
            self.assertIsNone(unrelated.poll())
        finally:
            job.close()
            for process in [owned,unrelated]:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)

    def test_widget_refresh_schedule_and_manual_refresh(self):
        import widget
        app=widget.WeekWidget.__new__(widget.WeekWidget)
        app.config={'shad_enabled':True}
        app.shad_last_attempt=100
        app.shad_state={}
        app.start_shad_process=Mock()
        app.poll_deadlines=Mock()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'shad-connected.flag').touch()
            with patch.object(widget,'ROOT',root), patch('widget.clock.monotonic',return_value=3699):
                app.refresh_deadlines()
                app.start_shad_process.assert_not_called()
                app.refresh_deadlines(True)
                app.start_shad_process.assert_called_once()
            app.start_shad_process.reset_mock()
            with patch.object(widget,'ROOT',root), patch('widget.clock.monotonic',return_value=3700):
                app.refresh_deadlines()
                app.start_shad_process.assert_called_once()
                app.start_shad_process.reset_mock()
                app.config['shad_enabled']=False
                app.refresh_deadlines(True)
                app.start_shad_process.assert_not_called()

    def test_recent_background_check_prevents_duplicate_widget_sync(self):
        import widget
        app=widget.WeekWidget.__new__(widget.WeekWidget)
        app.config={'shad_enabled':True}
        app.shad_last_attempt=0
        app.shad_state={'checked_at':datetime.now(core.MOSCOW).isoformat()}
        app.start_shad_process=Mock()
        with patch('widget.clock.monotonic',return_value=10000):
            app.refresh_deadlines()
        app.start_shad_process.assert_not_called()

    def test_parse_and_exclude_archive(self):
        items=core.parse_assignments(page())
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].title,'ДЗ & проверка')
        self.assertEqual(items[0].course,'Алгоритмы')
        self.assertEqual(items[0].due.isoformat(),'2026-10-31T18:00:00+03:00')
        self.assertFalse(items[0].date_only)
        self.assertEqual(items[0].url,'https://lk.dataschool.yandex.ru/learning/assignments/123/')

    def test_completed_filter_and_missing_time(self):
        items=core.parse_assignments(page('31 октября 2026',True))
        self.assertTrue(items[0].completed)
        self.assertTrue(items[0].date_only)
        self.assertEqual(core.visible_deadlines(items),[])
        self.assertEqual(len(core.visible_deadlines(items,True)),1)
        self.assertIsNone(core.parse_assignments(page('—'))[0].due)

    def test_invalid_page_and_dates_do_not_clear_cache(self):
        for html in ['<form><input type="password"></form>',page('31 февраля 2026 18:00'),
                     page('31 октября 2026 25:00'),page('unknown')]:
            with self.assertRaises(core.UnsupportedPage):
                core.parse_assignments(html)

    def test_full_snapshot_replaces_old_dates_completed_and_removed_items(self):
        first=core.parse_assignments(page())[0]
        with tempfile.TemporaryDirectory() as temporary:
            cache=Path(temporary)/'cache.json'
            with patch.object(core,'CACHE',cache):
                core.save_deadlines([first,replace(first,uid='removed')])
                changed=replace(first,due=datetime(2026,11,5,23,59,tzinfo=core.MOSCOW),completed=True)
                core.save_deadlines([changed])
                items,updated=core.load_deadlines()
                self.assertEqual(items,[changed])
                self.assertTrue(updated)
                before=cache.read_bytes()
                with self.assertRaises(core.UnsupportedPage):
                    parsed=core.parse_assignments('<form>Login</form>')
                    core.save_deadlines(parsed)
                self.assertEqual(cache.read_bytes(),before)
                core.save_deadlines([])
                self.assertEqual(core.load_deadlines()[0],[])

    def test_date_only_is_not_overdue_at_midday_and_urls_stay_on_shad(self):
        item=core.parse_assignments(page('31 октября 2026'))[0]
        now=datetime(2026,10,31,12,tzinfo=core.MOSCOW)
        self.assertEqual(core.deadline_label(item,now)[0],'Сегодня')
        no_time=replace(item,due=None)
        self.assertEqual(core.deadline_label(no_time,now)[0],'Срок не указан')
        for url in ['javascript:alert(1)','https://example.com/','https://bad@lk.dataschool.yandex.ru/']:
            self.assertEqual(core.safe_assignment_url(url),core.ASSIGNMENTS_URL)


if __name__=='__main__':
    unittest.main(verbosity=2)
