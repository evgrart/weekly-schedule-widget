"""Scrollable deadline list alongside the existing week grid."""
import tkinter as tk
import webbrowser

from deadline_core import ASSIGNMENTS_URL, BACKGROUND, read_json, deadline_label, visible_deadlines

BG, PANEL, TEXT, MUTED = '#0c121c', '#141f2e', '#f1f6ff', '#a8b8cc'


class DeadlinePanel(tk.Frame):
    def __init__(self, parent, p, font, connect, refresh):
        super().__init__(parent, bg=PANEL, width=p(265))
        self.p, self.font, self.connect, self.refresh = p, font, connect, refresh
        self.pack_propagate(False)
        self.items, self.state, self.updated_at = [], {}, None
        title = tk.Frame(self, bg=PANEL)
        title.pack(fill='x', padx=p(12), pady=(p(12), p(4)))
        tk.Label(title, text='Дедлайны ШАДа', bg=PANEL, fg=TEXT,
                 font=font(14, True)).pack(side='left')
        tk.Button(title, text='↻', command=refresh, bg=PANEL, fg=MUTED,
                  relief='flat', bd=0, font=font(15), cursor='hand2').pack(side='right')
        self.status = tk.Label(self, bg=PANEL, fg=MUTED, font=font(10), justify='left',
                               anchor='w', wraplength=p(235))
        self.status.pack(fill='x', padx=p(12), pady=(0, p(8)))
        self.connect_button = tk.Button(self, text='Войти в ШАД', command=connect,
                                       bg='#315f88', fg=TEXT, relief='flat',
                                       font=font(11), cursor='hand2', pady=p(5))
        self.connect_button.pack(fill='x', padx=p(12), pady=(0, p(8)))
        self.show_completed = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text='Показывать завершённые', variable=self.show_completed,
                       command=self.render, bg=PANEL, fg=MUTED, selectcolor=BG,
                       activebackground=PANEL, activeforeground=TEXT,
                       font=font(10)).pack(anchor='w', padx=p(8))
        content = tk.Frame(self, bg=PANEL)
        content.pack(fill='both', expand=True, padx=p(8), pady=p(5))
        self.canvas = tk.Canvas(content, bg=PANEL, highlightthickness=0, width=p(240))
        bar = tk.Scrollbar(content, orient='vertical', command=self.canvas.yview)
        bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=bar.set)
        self.cards = tk.Frame(self.canvas, bg=PANEL)
        self.window = self.canvas.create_window(0, 0, window=self.cards, anchor='nw')
        self.cards.bind('<Configure>', lambda event:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self.resize)
        self.canvas.bind('<MouseWheel>', self.wheel)
        tk.Button(self, text='Открыть задания ↗', command=lambda:webbrowser.open(ASSIGNMENTS_URL),
                  bg=PANEL, fg='#89c7ff', relief='flat', font=font(10), cursor='hand2').pack(
                      fill='x', padx=p(10), pady=(0, p(8)))

    def resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        for label in self.cards.winfo_children():
            for child in label.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(wraplength=max(50, event.width-self.p(25)))

    def wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'

    def update_data(self, items, state, updated_at):
        self.items, self.state, self.updated_at = items, state, updated_at
        self.render()

    def render(self):
        scroll = self.canvas.yview()[0]
        state = self.state.get('state', 'login_required')
        messages = {
            'login_required': 'Подключи аккаунт, чтобы загрузить задания.',
            'connecting': 'Открыт вход в Яндекс. Войди в аккаунт ШАДа.',
            'syncing': 'Проверяю задания…',
            'busy': 'Подключение ШАДа уже выполняется…',
            'error': 'Не удалось обновить. Повторю автоматически.',
            'unsupported': 'Страница заданий изменилась. Сохранённые сроки оставлены.',
            'ok': 'Автообновление раз в час',
        }
        message = messages.get(state, messages['error'])
        if state == 'ok' and read_json(BACKGROUND, {}).get('enabled'):
            message += '\nДаже при закрытом виджете'
        if self.updated_at:
            from datetime import datetime
            try:
                stamp = datetime.fromisoformat(self.updated_at).strftime('%d.%m %H:%M')
                message += '\n' + ('Обновлено ' if state == 'ok' else 'Сохранённая копия ') + stamp
            except ValueError:
                pass
        self.status.configure(text=message)
        self.connect_button.configure(text='Войти в ШАД' if state == 'login_required' else 'Переподключить ШАД')
        if state in {'connecting', 'syncing', 'busy'}:
            self.connect_button.configure(state='disabled')
        else:
            self.connect_button.configure(state='normal')
        for child in self.cards.winfo_children():
            child.destroy()
        items = visible_deadlines(self.items, self.show_completed.get())
        if not items:
            text = 'Незавершённых заданий нет' if state == 'ok' else 'Дедлайны появятся после подключения'
            tk.Label(self.cards, text=text, bg=PANEL, fg=MUTED, font=self.font(11),
                     wraplength=self.p(220), justify='left', anchor='w').pack(fill='x', pady=self.p(12))
        width = max(self.p(180), self.canvas.winfo_width()-self.p(25))
        for item in items:
            card = tk.Frame(self.cards, bg='#202339', cursor='hand2')
            card.pack(fill='x', pady=(0, self.p(8)))
            due, color = deadline_label(item)
            texts = [(due, color, self.font(10, True)),
                     (item.title, TEXT, self.font(12, True)),
                     (item.course, MUTED, self.font(10)),
                     (item.status, MUTED, self.font(10))]
            for text, fg, font in texts:
                if not text:
                    continue
                label = tk.Label(card, text=text, bg='#202339', fg=fg, font=font,
                                 wraplength=width, justify='left', anchor='w', cursor='hand2')
                label.pack(fill='x', padx=self.p(9), pady=(self.p(5), self.p(4)))
                label.bind('<Button-1>', lambda event, url=item.url:webbrowser.open(url))
                label.bind('<MouseWheel>', self.wheel)
            card.bind('<Button-1>', lambda event, url=item.url:webbrowser.open(url))
            card.bind('<MouseWheel>', self.wheel)
        self.cards.update_idletasks()
        self.canvas.yview_moveto(scroll)
