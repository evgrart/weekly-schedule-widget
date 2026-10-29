"""Local deadline records. Authentication data never belongs in these records."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import json
import os
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from calendar_core import ROOT, MOSCOW

ASSIGNMENTS_URL = 'https://lk.dataschool.yandex.ru/learning/assignments/'
CACHE = ROOT / 'shad-deadlines.json'
STATUS = ROOT / 'shad-sync-status.json'
SYNC_INTERVAL = 3600
BACKGROUND = ROOT / 'shad-background.json'


@dataclass(frozen=True)
class Deadline:
    uid: str
    title: str
    course: str
    due: datetime | None
    url: str
    completed: bool = False
    date_only: bool = False
    status: str = ''

    def to_dict(self):
        return dict(uid=self.uid, title=self.title, course=self.course,
                    due=self.due.isoformat() if self.due else None, url=self.url,
                    completed=self.completed, date_only=self.date_only, status=self.status)


def safe_assignment_url(value):
    url = urljoin(ASSIGNMENTS_URL, str(value or ''))
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'lk.dataschool.yandex.ru':
        return ASSIGNMENTS_URL
    if parsed.username or parsed.password:
        return ASSIGNMENTS_URL
    return url


def from_dict(value):
    raw = value.get('due')
    due = datetime.fromisoformat(raw) if raw else None
    if due:
        due = due.replace(tzinfo=MOSCOW) if due.tzinfo is None else due.astimezone(MOSCOW)
    return Deadline(str(value['uid']), str(value['title']), str(value.get('course', '')),
                    due, safe_assignment_url(value.get('url')),
                    bool(value.get('completed')), bool(value.get('date_only')), str(value.get('status', '')))


def atomic_json(path, value):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def load_deadlines():
    data = read_json(CACHE, {})
    try:
        return [from_dict(value) for value in data.get('items', [])], data.get('updated_at')
    except (KeyError, TypeError, ValueError):
        return [], None


def save_deadlines(items):
    # Each successful fetch replaces the previous snapshot, including deletions.
    unique = {item.uid: item for item in items}
    atomic_json(CACHE, {'updated_at': datetime.now(MOSCOW).isoformat(),
                        'items': [item.to_dict() for item in unique.values()]})


def deadline_label(item, now=None):
    now = now or datetime.now(MOSCOW)
    if item.completed:
        return 'Завершено', '#8293a8'
    if item.due is None:
        return 'Срок не указан', '#a8b8cc'
    due = item.due
    effective = datetime.combine(due.date(), time.max, MOSCOW) if item.date_only else due
    day = due.date()
    difference = (day - now.date()).days
    label = 'Сегодня' if difference == 0 else 'Завтра' if difference == 1 else due.strftime('%d.%m.%Y')
    if not item.date_only:
        label += due.strftime(' · %H:%M')
    if effective < now:
        return 'Просрочено · ' + label, '#f49aa6'
    return label, '#efc183' if (effective-now).total_seconds() <= 48*3600 else '#c3a7eb'


def visible_deadlines(items, completed=False):
    return sorted((item for item in items if completed or not item.completed),
                  key=lambda item: (item.completed, item.due is None,
                                    item.due or datetime.max.replace(tzinfo=MOSCOW), item.title))


@dataclass(frozen=True)
class DeadlineMarker:
    items: tuple[Deadline, ...]

    @property
    def due(self):
        return self.items[0].due

    @property
    def date_only(self):
        return self.items[0].date_only

    @property
    def title(self):
        return self.items[0].title if len(self.items) == 1 else f'Дедлайны ({len(self.items)})'


def week_deadline_markers(items, first_day):
    """Group equal deadlines, excluding completed and unscheduled assignments."""
    groups = {}
    for item in visible_deadlines(items):
        if item.due is None or not first_day <= item.due.date() < first_day+timedelta(days=7):
            continue
        groups.setdefault((item.due, item.date_only), []).append(item)
    return [DeadlineMarker(tuple(group)) for group in groups.values()]


class UnsupportedPage(ValueError):
    pass


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
        self.parent = None

    def text(self):
        return ' '.join(' '.join(child.text() if isinstance(child, Node) else child
                                 for child in self.children).split())

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def find(self, tag, predicate=lambda node:True):
        return next((node for node in self.walk() if node.tag == tag and predicate(node)), None)

    def has_class(self, value):
        return value in self.attrs.get('class', '').split()


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        node.parent = self.stack[-1]
        node.parent.children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                       'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


MONTHS = {name:index for index, name in enumerate(
    ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
     'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'], 1)}


def parse_due(text):
    text = ' '.join(text.split()).casefold()
    if text in {'', '—', '-', 'не указан', 'без срока', 'срок не указан'}:
        return None, False
    match = re.fullmatch(r'(\d{1,2})\s+([а-яё]+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?', text)
    if not match or match[2] not in MONTHS:
        raise UnsupportedPage('unrecognized_deadline')
    try:
        due = datetime(int(match[3]), MONTHS[match[2]], int(match[1]),
                       int(match[4] or 0), int(match[5] or 0), tzinfo=MOSCOW)
    except ValueError as error:
        raise UnsupportedPage('invalid_deadline') from error
    return due, match[4] is None


def parse_assignments(html):
    """Read the observed SHAD 'Открытые задания' table; never mix in its archive."""
    document = Document(html).root
    logged_in = document.find('div', lambda node:node.attrs.get('id') == 'login'
                              and bool(node.attrs.get('data-user-id')))
    filters = document.find('select', lambda node:node.attrs.get('id') == 'id_status')
    if not logged_in or not filters:
        raise UnsupportedPage('not_assignments_page')
    heading = document.find('h3', lambda node:node.text() == 'Открытые задания')
    if heading is None:
        archive = document.find('h3', lambda node:node.text() == 'Архив')
        if archive or 'Нет заданий' in document.text():
            return []
        raise UnsupportedPage('open_assignments_missing')
    table = heading.parent.find('table')
    if table is None:
        raise UnsupportedPage('assignments_table_missing')
    headers = [node.text() for node in table.walk() if node.tag == 'th']
    if len(headers) != 5 or headers[0] != 'Срок сдачи' or headers[2] != 'Курс':
        raise UnsupportedPage('assignments_columns_changed')
    items = []
    for row in (node for node in table.walk() if node.tag == 'tr'):
        cells = [node for node in row.children if isinstance(node, Node) and node.tag == 'td']
        if not cells:
            continue
        if len(cells) != 5:
            raise UnsupportedPage('assignment_row_changed')
        link = cells[1].find('a', lambda node:bool(re.fullmatch(
            r'/learning/assignments/\d+/', node.attrs.get('href', ''))))
        status = cells[3].find('span', lambda node:node.has_class('assignment-status'))
        if not link or not link.text() or not status:
            raise UnsupportedPage('assignment_fields_changed')
        due, date_only = parse_due(cells[0].text())
        url = safe_assignment_url(link.attrs['href'])
        items.append(Deadline(urlsplit(url).path, link.text(), cells[2].text(), due,
                              url, status.has_class('completed'), date_only, status.text()))
    return items
