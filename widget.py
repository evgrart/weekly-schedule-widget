import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time as clock
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit
import webbrowser
import winreg

try:
    if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        ctypes.windll.user32.SetProcessDPIAware()
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Public.WeeklyScheduleWidget")
except Exception:
    pass

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from calendar_core import ROOT, MOSCOW, monday, fetch_calendar, parse_calendar, week_events, day_events, arrange, cache_path
from desktop_anchor import DesktopAnchor, bounds as native_bounds, wait_for_desktop
from deadline_core import (STATUS as SHAD_STATUS, BACKGROUND as SHAD_BACKGROUND, SYNC_INTERVAL,
                           DeadlineMarker, week_deadline_markers, load_deadlines, read_json)
from deadline_panel import DeadlinePanel
from app_paths import CODE_ROOT
from config_store import load_config, save_config, valid_feed

BG, PANEL, TEXT, MUTED, LINE = "#0c121c", "#141f2e", "#f1f6ff", "#a8b8cc", "#2a374a"
DAYS = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def startup(enabled):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    command = f'"{pythonw}" "{CODE_ROOT / "widget.py"}"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "WeeklyScheduleWidgetPublic", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "WeeklyScheduleWidgetPublic")
            except FileNotFoundError:
                pass


def short_title(title):
    return title.replace("English B1.2 / Английский язык B1.2", "Английский B1.2")


class WeekWidget:
    def __init__(self, root, config):
        self.root, self.config = root, config
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
        except AttributeError:
            dpi = root.winfo_fpixels("1i")
        self.scale = min(1.6, max(1.0, dpi / 96))
        self.p = lambda number: max(1, round(number * self.scale))
        self.font = lambda size, bold=False: ("Segoe UI", -self.p(size), "bold" if bold else "normal")
        self.first_day = monday(datetime.now(MOSCOW).date())
        self.follow_today = True
        self.calendar, self.events = None, []
        self.results, self.busy = queue.Queue(), False
        self.checked_at, self.last_attempt = None, 0
        self.successful_refreshes = 0
        self.last_health = 0
        self.issue, self.closed = "", False
        self.geometry_data, self.event_boxes = None, []
        self.deadline_boxes, self.week_deadline_markers = [], []
        self.measure_fonts = {}
        self.hover, self.tooltip, self.tip_job = None, None, None
        self.draw_job, self.drag_start, self.resize_start = None, None, None
        self.settings_window = None
        self.shad_process, self.shad_signature = None, None
        self.shad_last_attempt = 0
        self.shad_items, self.shad_updated_at = load_deadlines()
        self.shad_state = read_json(SHAD_STATUS, {"state": "login_required"})
        self.root.title("Weekly Schedule Widget")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(config["topmost"]))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = min(self.p(1560), sw-self.p(24)), min(self.p(650), sh-self.p(100))
        bounds = config.get("bounds", [sw-width-self.p(20), self.p(55), width, height])
        x, y, width, height = [int(v) for v in bounds]
        width = min(max(self.p(720), width), sw)
        height = min(max(self.p(350), height), sh)
        if config.get("wide_layout_version", 0) < 1:
            width = max(width, sw-self.p(24))
            x = (sw-width)//2
            config["wide_layout_version"] = 1
        x, y = max(0, min(x, sw-width)), max(0, min(y, sh-height))
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.header = tk.Frame(root, bg=PANEL, height=self.p(46))
        self.header.pack(fill="x", padx=1, pady=(1, 0))
        self.header.pack_propagate(False)
        self.range_label = tk.Label(self.header, bg=PANEL, fg=TEXT, font=self.font(15, True), anchor="w")
        self.range_label.pack(side="left", padx=self.p(14), fill="both", expand=True)
        controls = tk.Frame(self.header, bg=PANEL)
        controls.pack(side="right", padx=self.p(5))
        for text, action, width in [("‹", lambda:self.change_week(-1), 3),
                                     ("Сегодня", self.today, 8),
                                     ("›", lambda:self.change_week(1), 3),
                                     ("↻", lambda:self.refresh(True), 3),
                                     ("Сроки", self.toggle_deadlines, 6),
                                     ("⚙", self.settings, 3),
                                     ("−", self.minimize, 3),
                                     ("×", self.close, 3)]:
            tk.Button(controls, text=text, command=action, width=width, bg=PANEL, fg=MUTED,
                      activebackground="#2b3b50", activeforeground=TEXT, font=self.font(14),
                      relief="flat", bd=0, cursor="hand2", takefocus=False).pack(side="left", padx=1)
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=1)
        self.deadline_panel = DeadlinePanel(self.body, self.p, self.font,
                                            self.connect_shad, lambda:self.refresh_deadlines(True))
        if self.config.get("shad_enabled", True):
            self.deadline_panel.pack(side="right", fill="y", padx=(1, 0))
        self.canvas = tk.Canvas(self.body, bg=BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.deadline_panel.update_data(self.shad_items, self.shad_state, self.shad_updated_at)
        footer = tk.Frame(root, bg=PANEL, height=self.p(27))
        footer.pack(fill="x", padx=1, pady=(0, 1))
        footer.pack_propagate(False)
        self.status = tk.Label(footer, bg=PANEL, fg=MUTED, anchor="w", font=self.font(10))
        self.status.pack(side="left", fill="both", expand=True, padx=self.p(12))
        tk.Label(footer, text="Москва · 24 ч", bg=PANEL, fg=MUTED, font=self.font(10)).pack(side="right", padx=self.p(10))
        grip = tk.Label(footer, text="◢", bg=PANEL, fg=MUTED, cursor="sizing", font=self.font(13))
        grip.pack(side="right")
        grip.bind("<ButtonPress-1>", self.start_resize)
        grip.bind("<B1-Motion>", self.resize)
        grip.bind("<ButtonRelease-1>", self.remember_bounds)
        for element in [self.header, self.range_label]:
            element.bind("<ButtonPress-1>", self.start_drag)
            element.bind("<B1-Motion>", self.drag)
            element.bind("<ButtonRelease-1>", self.remember_bounds)
        self.canvas.bind("<Configure>", self.queue_draw)
        self.canvas.bind("<Motion>", self.motion)
        self.canvas.bind("<Leave>", lambda event:self.hide_tip())
        self.canvas.bind("<Button-1>", self.click_event)
        self.root.bind("<Left>", lambda event:self.change_week(-1))
        self.root.bind("<Right>", lambda event:self.change_week(1))
        self.root.bind("<Escape>", lambda event:self.hide_tip())
        self.root.bind("<Control-r>", lambda event:self.refresh(True))
        self.menu = tk.Menu(root, tearoff=0, bg=PANEL, fg=TEXT)
        self.menu.add_command(label="Обновить", command=lambda:self.refresh(True))
        self.menu.add_command(label="Открыть Google Календарь", command=self.open_google)
        self.menu.add_command(label="Настройки", command=self.settings)
        self.menu.add_separator()
        self.menu.add_command(label="Закрыть виджет", command=self.close)
        root.bind("<Button-3>", lambda event:self.menu.tk_popup(event.x_root,event.y_root))
        try:
            self.root.iconbitmap(str(CODE_ROOT / "widget.ico"))
        except tk.TclError:
            pass
        self.root.update_idletasks()
        self.hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)
        # Give the borderless window its own taskbar entry, so minimisation is reversible.
        get_style = ctypes.windll.user32.GetWindowLongW
        style = get_style(self.hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(self.hwnd, -20, (style | 0x40000) & ~0x80)
        self.anchor = DesktopAnchor(self.hwnd)
        self.apply_window_mode()
        try:
            cached = cache_path(config["feed_url"])
            self.calendar = parse_calendar(cached.read_bytes())
            self.checked_at = datetime.fromtimestamp(cached.stat().st_mtime, MOSCOW)
            self.issue = "Проверяю обновления"
        except (OSError, ValueError, KeyError):
            pass
        self.root.after(100, self.refresh)
        self.root.after(400, self.show)
        self.root.after(200, self.tick)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.draw()

    def remember_bounds(self, event=None):
        self.config["bounds"] = native_bounds(self.hwnd)
        save_config(self.config)

    def start_drag(self, event):
        x,y,_,_=native_bounds(self.hwnd)
        self.drag_start = (event.x_root, event.y_root, x, y)

    def drag(self, event):
        if self.drag_start:
            x,y,wx,wy = self.drag_start
            self.root.geometry(f"+{max(0,wx+event.x_root-x)}+{max(0,wy+event.y_root-y)}")

    def start_resize(self, event):
        self.resize_start = (event.x_root,event.y_root,self.root.winfo_width(),self.root.winfo_height())

    def resize(self, event):
        x,y,w,h = self.resize_start
        self.root.geometry(f"{max(self.p(720),w+event.x_root-x)}x{max(self.p(350),h+event.y_root-y)}")

    def minimize(self):
        self.anchor.minimize()

    def show(self):
        self.anchor.show()
        if not self.anchor.enabled:
            self.root.lift()

    def apply_window_mode(self):
        enabled=bool(self.config.get("desktop_mode"))
        if enabled:
            self.config["topmost"]=False
            self.root.attributes("-topmost",False)
        else:
            self.root.attributes("-topmost",bool(self.config["topmost"]))
        if not self.anchor.configure(enabled,self.config["topmost"]):
            self.issue="Не удалось закрепиться на рабочем столе — повторю автоматически"

    def close(self):
        self.remember_bounds()
        if self.shad_process is not None and self.shad_process.poll() is None:
            (ROOT / "shad-stop.request").touch()
        self.closed = True
        self.root.destroy()

    def open_google(self):
        webbrowser.open("https://calendar.google.com/calendar/")

    def change_week(self, offset):
        self.first_day += timedelta(days=7*offset)
        self.follow_today = self.first_day == monday(datetime.now(MOSCOW).date())
        self.draw()

    def today(self):
        self.first_day = monday(datetime.now(MOSCOW).date())
        self.follow_today = True
        self.draw()

    def queue_draw(self, event=None):
        if self.draw_job:
            self.root.after_cancel(self.draw_job)
        self.draw_job = self.root.after(70,self.draw)

    def refresh(self, force=False):
        self.refresh_deadlines(force)
        if self.busy:
            return
        self.last_attempt = clock.monotonic()
        url = self.config.get("feed_url", "")
        if not valid_feed(url):
            self.issue = "Укажи ссылку Google Календаря в настройках"
            self.update_status()
            return
        self.busy = True
        self.update_status()
        def worker():
            try:
                data, calendar = fetch_calendar(url)
                target = cache_path(url)
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(data)
                os.replace(temporary,target)
                self.results.put((url,calendar,None))
            except Exception as error:
                # Do not put the private feed URL into messages or logs.
                self.results.put((url,None,type(error).__name__))
        threading.Thread(target=worker,daemon=True).start()

    def toggle_deadlines(self):
        enabled = not self.config.get("shad_enabled", True)
        self.config["shad_enabled"] = enabled
        if enabled:
            self.deadline_panel.pack(side="right", fill="y", padx=(1, 0), before=self.canvas)
            self.refresh_deadlines(True)
        else:
            self.deadline_panel.pack_forget()
        save_config(self.config)
        self.queue_draw()

    def start_shad_process(self, login=False):
        if self.shad_process is not None and self.shad_process.poll() is None:
            return
        self.shad_last_attempt = clock.monotonic()
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        try:
            self.shad_process = subprocess.Popen(
                [str(pythonw), str(CODE_ROOT / "shad_sync.py"), "--login" if login else "--once"],
                cwd=str(ROOT), creationflags=subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.shad_state = {"state": "connecting" if login else "syncing"}
        except OSError:
            self.shad_state = {"state": "error"}
        self.deadline_panel.update_data(self.shad_items, self.shad_state, self.shad_updated_at)

    def connect_shad(self):
        self.start_shad_process(login=True)

    def refresh_deadlines(self, force=False):
        if not self.config.get("shad_enabled", True):
            return
        if not force:
            if clock.monotonic()-self.shad_last_attempt < SYNC_INTERVAL:
                return
            # A background task may already have refreshed the shared snapshot.
            checked = self.shad_state.get("checked_at")
            if checked:
                try:
                    age = (datetime.now(MOSCOW)-datetime.fromisoformat(checked)).total_seconds()
                    if 0 <= age < SYNC_INTERVAL:
                        return
                except (ValueError, TypeError):
                    pass
        if not (ROOT / "shad-connected.flag").exists():
            self.shad_last_attempt = clock.monotonic()
            self.poll_deadlines()
            return
        self.start_shad_process()

    def poll_deadlines(self):
        if self.shad_process is not None and self.shad_process.poll() is not None:
            self.shad_process = None
        paths = [SHAD_STATUS, ROOT / "shad-deadlines.json", SHAD_BACKGROUND]
        signature = tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in paths)
        signature += (datetime.now(MOSCOW).strftime("%Y-%m-%d %H:%M"),)
        if signature == self.shad_signature:
            return
        self.shad_signature = signature
        previous_items = self.shad_items
        self.shad_items, self.shad_updated_at = load_deadlines()
        self.shad_state = read_json(SHAD_STATUS, {"state": "login_required"})
        self.deadline_panel.update_data(self.shad_items, self.shad_state, self.shad_updated_at)
        if previous_items != self.shad_items:
            self.queue_draw()

    def update_status(self):
        if self.busy:
            text = "Google Календарь · проверяю обновления…"
        elif self.issue:
            text = self.issue
            if self.checked_at:
                text += " · сохранённая копия " + self.checked_at.strftime("%H:%M")
        elif self.checked_at:
            text = "Google Календарь · обновлено " + self.checked_at.strftime("%H:%M")
            text += f" · каждые {self.config['refresh_seconds']//60} мин"
        else:
            text = "Подключаю Google Календарь…"
        self.status.configure(text=text,fg="#e5b674" if self.issue and not self.busy else MUTED)

    def tick(self):
        if self.closed:
            return
        self.poll_deadlines()
        self.refresh_deadlines()
        try:
            while True:
                url,calendar,error = self.results.get_nowait()
                self.busy = False
                if url != self.config["feed_url"]:
                    self.refresh(True)
                    continue
                if error:
                    self.issue = "Нет обновления — повторю проверку автоматически"
                else:
                    self.calendar = calendar
                    self.checked_at = datetime.now(MOSCOW)
                    self.successful_refreshes += 1
                    self.issue = ""
                    self.last_health = 0
                    self.draw()
                self.update_status()
        except queue.Empty:
            pass
        if not self.busy and clock.monotonic()-self.last_attempt >= self.config["refresh_seconds"]:
            self.refresh()
        request = ROOT / "show.request"
        if request.exists():
            try:
                request.unlink()
            except OSError:
                pass
            self.show()
        if self.geometry_data:
            self.draw_now()
        attached=self.anchor.maintain()
        if attached and self.issue=="Не удалось закрепиться на рабочем столе — повторю автоматически":
            self.issue=""
            self.update_status()
        current_week = monday(datetime.now(MOSCOW).date())
        if self.follow_today and self.first_day != current_week:
            self.first_day = current_week
            self.draw()
        if clock.monotonic()-self.last_health >= 15:
            self.write_health()
            self.last_health = clock.monotonic()
        self.root.after(1000,self.tick)

    def write_health(self):
        report = {"source":"Google Calendar", "week_start":self.first_day.isoformat(),
                  "event_count":len(self.events), "refresh_seconds":self.config["refresh_seconds"],
                  "last_success":self.checked_at.isoformat() if self.checked_at else None,
                  "successful_refreshes":self.successful_refreshes, "issue":self.issue,
                  "busy":self.busy, "window_handle":int(self.hwnd),
                  "bounds":native_bounds(self.hwnd)}
        report.update(shad_state=self.shad_state.get("state"), shad_deadline_count=len(self.shad_items),
                      shad_last_success=self.shad_updated_at,
                      shad_interval_seconds=SYNC_INTERVAL,
                      shad_background_enabled=bool(read_json(SHAD_BACKGROUND, {}).get("enabled")),
                      shad_grid_markers=len(self.week_deadline_markers),
                      shad_panel_visible=bool(self.config.get("shad_enabled", True)))
        report.update(self.anchor.report())
        (ROOT/"status.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    def draw(self):
        self.draw_job = None
        self.hide_tip()
        self.canvas.delete("all")
        self.event_boxes = []
        self.deadline_boxes = []
        width,height = self.canvas.winfo_width(),self.canvas.winfo_height()
        if width < 100 or height < 100:
            return
        last = self.first_day+timedelta(days=6)
        self.range_label.configure(text=f"{self.first_day.day} {MONTHS[self.first_day.month-1]} — {last.day} {MONTHS[last.month-1]}  {last.year}")
        try:
            self.events = week_events(self.calendar,self.first_day) if self.calendar else []
        except Exception:
            self.issue = "Не удалось развернуть повторения календаря"
            self.events = []
        margin = self.p(53)
        day_width = (width-margin)/7
        header = self.p(43)
        self.week_deadline_markers = week_deadline_markers(self.shad_items, self.first_day)
        all_days = [[e for e in self.events if e.all_day and e.start.date() <= self.first_day+timedelta(days=i) < e.end.date()] for i in range(7)]
        for index in range(7):
            due_day = self.first_day+timedelta(days=index)
            banners = [marker for marker in self.week_deadline_markers
                       if marker.date_only and marker.due.date() == due_day]
            all_days[index] = banners+all_days[index]
        all_day_rows = min(2,max((len(items) for items in all_days),default=0))
        grid_top = header+(self.p(23)*all_day_rows+self.p(5) if all_day_rows else 0)
        timed = [e for e in self.events if not e.all_day]
        deadline_times = [marker.due for marker in self.week_deadline_markers if not marker.date_only]
        first_hour = min([8]+[e.start.hour for e in timed]+[due.hour for due in deadline_times])
        last_hour = max([22]+[min(24,e.end.hour+(bool(e.end.minute))) for e in timed]
                        +[min(24,due.hour+1) for due in deadline_times])
        grid_bottom = height-self.p(15)
        hour_height = (grid_bottom-grid_top)/(last_hour-first_hour)
        self.geometry_data = (margin,day_width,grid_top,grid_bottom,first_hour,last_hour,hour_height,width)
        today = datetime.now(MOSCOW).date()
        for index in range(7):
            day = self.first_day+timedelta(days=index)
            x = margin+index*day_width
            if day == today:
                self.canvas.create_rectangle(x,0,x+day_width,height,fill="#17283e",outline="",tags="daybg")
            self.canvas.create_text(x+day_width/2,self.p(20),text=f"{DAYS[index]}  {day:%d.%m}",
                                    fill="#89c7ff" if day == today else TEXT,font=self.font(12,True))
            self.canvas.create_line(x,0,x,height,fill=LINE)
            for k,event in enumerate(all_days[index][:2]):
                if isinstance(event, DeadlineMarker):
                    self.draw_deadline(event, x+self.p(3), header+k*self.p(23), day_width-self.p(6), banner=True)
                else:
                    self.draw_card(event,x+self.p(3),header+k*self.p(23),day_width-self.p(6),self.p(21),True)
            for event,start,end,lane,total in arrange(day_events(self.events,day),day):
                begin = datetime.combine(day,time.min,MOSCOW)
                s = (start-begin).total_seconds()/3600
                f = (end-begin).total_seconds()/3600
                y1 = max(grid_top,grid_top+(s-first_hour)*hour_height)
                y2 = min(grid_bottom,grid_top+(f-first_hour)*hour_height)
                if y2 <= y1:
                    continue
                lane_width = day_width/total
                self.draw_card(event,x+lane*lane_width+self.p(3),y1+self.p(2),lane_width-self.p(6),max(self.p(10),y2-y1-self.p(4)))
        # Lower grid lines behind event cards.
        for hour in range(first_hour,last_hour+1):
            y = grid_top+(hour-first_hour)*hour_height
            item=self.canvas.create_line(margin,y,width,y,fill=LINE,tags="grid")
            self.canvas.tag_lower(item)
            self.canvas.create_text(margin-self.p(9),y,text=f"{hour:02}:00",fill=MUTED,font=self.font(10),anchor="e")
        self.canvas.tag_lower("daybg")
        for marker in self.week_deadline_markers:
            if marker.date_only:
                continue
            index = (marker.due.date()-self.first_day).days
            position = marker.due.hour+marker.due.minute/60+marker.due.second/3600
            y = grid_top+(position-first_hour)*hour_height
            self.draw_deadline(marker, margin+index*day_width+self.p(3), y, day_width-self.p(6))
        if self.calendar is None:
            self.canvas.create_text(width/2,height/2,text="Подключаю твой Google Календарь…",fill=MUTED,font=self.font(16),tags="empty")
        elif not self.events and not self.week_deadline_markers:
            self.canvas.create_text(width/2,height/2,text="На этой неделе нет занятий",fill=MUTED,font=self.font(16))
        self.draw_now()
        self.update_status()

    def measure_font(self, font):
        if font not in self.measure_fonts:
            self.measure_fonts[font] = tkfont.Font(root=self.root, font=font)
        return self.measure_fonts[font]

    def fit_line(self, text, width, font):
        measure = self.measure_font(font).measure
        if measure(text) <= width:
            return text
        if measure("…") > width:
            return ""
        left, right = 0, len(text)
        while left < right:
            middle = (left+right+1)//2
            if measure(text[:middle]+"…") <= width:
                left = middle
            else:
                right = middle-1
        return text[:left].rstrip()+"…"

    def wrap_label(self, text, width, max_lines, font):
        if max_lines < 1:
            return ""
        words, lines = text.split(), []
        measure = self.measure_font(font).measure
        while words and len(lines) < max_lines:
            line = words.pop(0)
            if measure(line) > width:
                line = self.fit_line(line, width, font)
            else:
                while words and measure(line+" "+words[0]) <= width:
                    line += " "+words.pop(0)
            lines.append(line)
        if words and lines:
            lines[-1] = self.fit_line(lines[-1]+" …", width, font)
        return "\n".join(lines)

    def draw_deadline(self, marker, x, y, width, banner=False):
        red, fill = "#ff566c", "#512431"
        height = self.p(21)
        label_y = y if banner else max(self.geometry_data[2], y-height-self.p(3))
        if not banner:
            self.canvas.create_line(x,y,x+width,y,fill=red,width=self.p(3),tags="deadline")
        self.canvas.create_rectangle(x,label_y,x+width,label_y+height,fill=fill,outline=red,tags="deadline")
        prefix = "ДД" if banner else f"ДД {marker.due:%H:%M}"
        name = marker.items[0].title if len(marker.items) == 1 else f"заданий: {len(marker.items)}"
        font = self.font(10, True)
        text = self.fit_line(prefix+" · "+name, width-self.p(12), font)
        self.canvas.create_text(x+self.p(6),label_y+height/2,text=text,anchor="w",
                                fill="#ffe1e6",font=font,tags="deadline")
        self.deadline_boxes.append((x,label_y,x+width,max(label_y+height,y+self.p(4)),marker))

    def draw_card(self,event,x,y,width,height,all_day=False):
        color,edge = ("#48335f","#bd91ef") if event.shad else ("#204767","#78bff0")
        self.canvas.create_rectangle(x,y,x+width,y+height,fill=color,outline="")
        self.canvas.create_rectangle(x,y,x+self.p(3),y+height,fill=edge,outline="")
        pad = self.p(7)
        available = max(0,width-2*pad)
        title_font = self.font(10 if width < self.p(100) else 12, True)
        clock_text, clock_font, clock_height = "", self.font(10), 0
        if not all_day and height >= self.p(34):
            full_clock = f"{event.start:%H:%M}–{event.end:%H:%M}"
            for size in [10,9,8]:
                candidate = self.font(size)
                measure = self.measure_font(candidate)
                if measure.measure(f"{event.start:%H:%M}") <= available:
                    clock_font = candidate
                    clock_text = full_clock if measure.measure(full_clock) <= available else f"{event.start:%H:%M}\n{event.end:%H:%M}"
                    clock_height = measure.metrics("linespace")*(clock_text.count("\n")+1)
                    remaining = height-self.p(18)-clock_height
                    if remaining >= self.measure_font(title_font).metrics("linespace") or size == 8:
                        break
        allowed = height-self.p(10)-(clock_height+self.p(8) if clock_text else 0)
        lines = max(0,int(allowed//self.measure_font(title_font).metrics("linespace")))
        title = self.wrap_label(short_title(event.title),available,lines,title_font)
        if title:
            self.canvas.create_text(x+pad,y+self.p(5),text=title,fill=TEXT,
                                    anchor="nw",font=title_font,tags="event-title")
        if clock_text:
            self.canvas.create_text(x+pad,y+height-self.p(6),text=clock_text,fill="#cee0f2",anchor="sw",
                                    font=clock_font,tags="event-time")
        self.event_boxes.append((x,y,x+width,y+height,event))

    def draw_now(self):
        self.canvas.delete("now")
        if not self.geometry_data:
            return
        left,dw,top,bottom,first,last,hh,width = self.geometry_data
        now=datetime.now(MOSCOW)
        index=(now.date()-self.first_day).days
        value=now.hour+now.minute/60+now.second/3600
        if 0 <= index < 7 and first <= value <= last:
            x,y=left+index*dw,top+(value-first)*hh
            self.canvas.create_line(x,y,x+dw,y,fill="#f27f8e",width=self.p(2),tags="now")
            self.canvas.create_oval(x-self.p(3),y-self.p(3),x+self.p(3),y+self.p(3),fill="#f27f8e",outline="",tags="now")

    def event_at(self,x,y):
        boxes = self.event_boxes+self.deadline_boxes
        return next((event for x1,y1,x2,y2,event in reversed(boxes) if x1<=x<=x2 and y1<=y<=y2),None)

    def motion(self,event):
        item=self.event_at(event.x,event.y)
        if item == self.hover:
            return
        self.hide_tip()
        self.hover=item
        self.canvas.configure(cursor="hand2" if item else "")
        if item:
            self.tip_job=self.root.after(400,lambda:self.show_tip(item,event.x_root,event.y_root))

    def hide_tip(self):
        if self.tip_job:
            self.root.after_cancel(self.tip_job)
            self.tip_job=None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip=None
        self.hover=None

    def show_tip(self,event,x,y):
        self.tip_job=None
        tip=tk.Toplevel(self.root,bg=LINE)
        tip.overrideredirect(True)
        tip.attributes("-topmost",True)
        if isinstance(event, DeadlineMarker):
            clock_text = event.due.strftime("%d.%m.%Y")+(" · день сдачи" if event.date_only else event.due.strftime(" · %H:%M · Москва"))
            details = "Дедлайн · "+clock_text+"\n\n"+"\n\n".join(
                item.title+"\n"+item.course for item in event.items)
        else:
            clock_text="Весь день" if event.all_day else f"{event.start:%d.%m · %H:%M}–{event.end:%H:%M} · Москва"
            details = event.title+"\n"+clock_text
        tk.Label(tip,text=details,bg=PANEL,fg=TEXT,font=self.font(12),
                 justify="left",wraplength=self.p(370),padx=self.p(12),pady=self.p(10)).pack(padx=1,pady=1)
        tip.update_idletasks()
        x=min(x+self.p(12),self.root.winfo_screenwidth()-tip.winfo_width()-self.p(10))
        y=min(y+self.p(16),self.root.winfo_screenheight()-tip.winfo_height()-self.p(10))
        tip.geometry(f"+{max(0,x)}+{max(0,y)}")
        self.tooltip=tip

    def click_event(self,event):
        item=self.event_at(event.x,event.y)
        if item:
            self.hide_tip()
            if isinstance(item, DeadlineMarker):
                if len(item.items) == 1:
                    webbrowser.open(item.items[0].url)
                else:
                    choices = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=TEXT)
                    for assignment in item.items:
                        choices.add_command(label=assignment.title+" · "+assignment.course,
                                            command=lambda url=assignment.url:webbrowser.open(url))
                    choices.tk_popup(event.x_root,event.y_root)
                return
            messagebox.showinfo(item.title,f"{item.title}\n\n{item.start:%d.%m.%Y}\n"+
                                ("Весь день" if item.all_day else f"{item.start:%H:%M}–{item.end:%H:%M} (Москва)"),parent=self.root)

    def settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        window=tk.Toplevel(self.root,bg=PANEL)
        window.title("Настройки расписания")
        window.resizable(False,False)
        self.settings_window=window
        box=tk.Frame(window,bg=PANEL,padx=self.p(18),pady=self.p(16))
        box.pack()
        def label(text):
            tk.Label(box,text=text,bg=PANEL,fg=TEXT,font=self.font(12),anchor="w").pack(fill="x",pady=(0,self.p(6)))
        label("Секретный адрес Google Календаря в формате iCal")
        url=tk.StringVar(value=self.config["feed_url"])
        entry=tk.Entry(box,textvariable=url,width=55,font=self.font(11),show="•",bg=BG,fg=TEXT,insertbackground=TEXT,relief="flat")
        entry.pack(fill="x",ipady=self.p(6))
        reveal=tk.BooleanVar(value=False)
        tk.Checkbutton(box,text="Показать ссылку",variable=reveal,command=lambda:entry.configure(show="" if reveal.get() else "•"),
                       bg=PANEL,fg=MUTED,selectcolor=BG,activebackground=PANEL,activeforeground=TEXT,font=self.font(11)).pack(anchor="w")
        label("Проверять обновления каждые")
        interval=tk.StringVar(value=str(self.config["refresh_seconds"]//60))
        ttk.Combobox(box,textvariable=interval,values=["1","2","5","10"],state="readonly",width=8).pack(anchor="w")
        tk.Label(box,text="минуты · изменения в самой ленте Google могут появляться с задержкой",bg=PANEL,fg=MUTED,font=self.font(10)).pack(anchor="w",pady=self.p(5))
        label("Расположение виджета")
        modes=["На рабочем столе", "Обычное окно", "Поверх всех окон"]
        mode=tk.StringVar(value=modes[0] if self.config.get("desktop_mode") else modes[2] if self.config["topmost"] else modes[1])
        ttk.Combobox(box,textvariable=mode,values=modes,state="readonly",width=28).pack(anchor="w",pady=self.p(4))
        auto=tk.BooleanVar(value=self.config["autostart"])
        for title,value in [("Запускать вместе с Windows",auto)]:
            tk.Checkbutton(box,text=title,variable=value,bg=PANEL,fg=TEXT,selectcolor=BG,activebackground=PANEL,
                           activeforeground=TEXT,font=self.font(12)).pack(anchor="w",pady=self.p(3))
        def apply():
            new_url=url.get().strip()
            if not valid_feed(new_url):
                messagebox.showerror("Проверь ссылку","Нужен HTTPS-адрес iCal с сайта calendar.google.com, заканчивающийся на .ics.",parent=window)
                return
            changed=new_url!=self.config["feed_url"]
            self.config.update(feed_url=new_url,refresh_seconds=int(interval.get())*60,topmost=mode.get()==modes[2],
                               desktop_mode=mode.get()==modes[0],autostart=auto.get())
            save_config(self.config)
            startup(auto.get())
            self.apply_window_mode()
            if changed:
                self.calendar,self.checked_at,self.issue=None,None,""
            self.draw()
            self.refresh(True)
            window.destroy()
        tk.Button(box,text="Сохранить",command=apply,bg="#315f88",fg=TEXT,activebackground="#4176a3",activeforeground=TEXT,
                  relief="flat",font=self.font(12),padx=self.p(20),pady=self.p(7)).pack(anchor="e",pady=(self.p(14),0))
        window.update_idletasks()
        window.geometry(f"+{max(0,self.root.winfo_x()+self.p(30))}+{max(0,self.root.winfo_y()+self.p(50))}")


def main():
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    name="Local\\WeeklyScheduleWidgetPublic-"+os.environ.get("USERNAME","user")
    mutex=kernel.CreateMutexW(None,False,name)
    if ctypes.get_last_error()==183:
        (ROOT/"show.request").touch()
        return
    def lifecycle(event):
        with (ROOT/"launch.log").open("a",encoding="utf-8") as output:
            output.write(f"{datetime.now(MOSCOW).isoformat()} pid={os.getpid()} {event}\n")
    lifecycle("start")
    config=load_config()
    if config.get("desktop_mode"):
        lifecycle("waiting_for_desktop")
        host=wait_for_desktop()
        lifecycle("desktop_ready" if host else "desktop_wait_timeout_will_retry")
    root=tk.Tk()
    root.tk.call("tk","scaling",1.0)
    app=WeekWidget(root,config)
    lifecycle("mainloop")
    root.mainloop()
    lifecycle("closed")
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    kernel.CloseHandle(mutex)


if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        (ROOT/"error.log").write_text(traceback.format_exc(),encoding="utf-8")
        raise
