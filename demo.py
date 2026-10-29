"""Offline demonstration with a disposable data directory and fictional events."""
import argparse
from datetime import date
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot', type=Path, help='Save a synthetic demo screenshot and exit')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='weekly-schedule-demo-') as temporary:
        os.environ['WEEKLY_SCHEDULE_DATA_DIR'] = temporary
        import tkinter as tk
        from app_paths import CODE_ROOT
        from calendar_core import parse_calendar
        from config_store import load_config
        from deadline_core import CACHE, STATUS, atomic_json, read_json, parse_assignments, save_deadlines
        import widget

        class DemoWidget(widget.WeekWidget):
            def refresh(self, force=False):
                pass

            def refresh_deadlines(self, force=False):
                pass

            def connect_shad(self):
                pass

            def poll_deadlines(self):
                pass

            def update_status(self):
                self.status.configure(text='Демо · вымышленные данные · без подключения к аккаунтам')

            def today(self):
                self.first_day = date(2030, 1, 7)
                self.follow_today = False
                self.draw()

            def click_event(self, event):
                # Fixture assignment links are not real tasks and must not be opened.
                pass

        items = parse_assignments((CODE_ROOT/'examples'/'assignments.html').read_text(encoding='utf-8'))
        save_deadlines(items)
        snapshot=read_json(CACHE)
        snapshot['updated_at']='2030-01-07T09:00:00+03:00'
        atomic_json(CACHE,snapshot)
        atomic_json(STATUS, {'state':'ok'})
        root = tk.Tk()
        root.withdraw()
        root.tk.call('tk','scaling',1.0)
        app = DemoWidget(root,load_config())
        root.title('Weekly Schedule Demo')
        app.calendar = parse_calendar((CODE_ROOT/'examples'/'demo.ics').read_bytes())
        app.today()
        app.deadline_panel.connect_button.configure(text='Демо · вымышленные задания',state='disabled')
        if args.screenshot:
            root.geometry('2400x1100+20000+20000')
        root.deiconify()
        root.update()
        app.draw()
        root.update_idletasks()
        try:
            if args.screenshot:
                target = args.screenshot.resolve()
                target.parent.mkdir(parents=True,exist_ok=True)
                powershell = Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
                subprocess.run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',
                                str(CODE_ROOT/'tools'/'capture_window.ps1'),'-WindowHandle',str(app.hwnd),
                                '-OutputPath',str(target)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                root.mainloop()
        finally:
            if root.winfo_exists():
                for job in root.tk.call('after','info'):
                    root.after_cancel(job)
                root.destroy()


if __name__ == '__main__':
    main()
