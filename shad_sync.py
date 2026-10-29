"""Read-only SHAD sync with manual login in an isolated local Edge profile."""
import argparse
import ctypes
import os
from datetime import datetime
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

from app_paths import DATA_ROOT as ROOT

from deadline_core import ASSIGNMENTS_URL, STATUS, MOSCOW, UnsupportedPage, atomic_json, parse_assignments, save_deadlines

PROFILE = ROOT / 'shad-browser-profile'
AUTH = ROOT / 'shad-connected.flag'
STOP = ROOT / 'shad-stop.request'


def state(name, **fields):
    atomic_json(STATUS, {'state': name, 'pid': os.getpid(),
                        'checked_at': datetime.now(MOSCOW).isoformat(), **fields})


def assignments_page(page):
    parsed = urlsplit(page.url)
    return (parsed.hostname == 'lk.dataschool.yandex.ru'
            and parsed.path.rstrip('/') == '/learning/assignments')


def main(login=False):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, 'Local\\WeeklySchedulePublicSHADSync')
    if not mutex:
        raise OSError('sync_mutex_failed')
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)
        return 0  # Another sync or manual login is already using our own profile.
    try:
        if not login and not AUTH.exists():
            state('login_required')
            return 0
        STOP.unlink(missing_ok=True)
        state('connecting' if login else 'syncing')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as driver:
            # The ordinary user's browser profile is never opened or copied.
            context = driver.chromium.launch_persistent_context(
                str(PROFILE), channel='msedge', headless=not login,
                viewport={'width': 1180, 'height': 820}, timeout=30000,
                args=['--no-first-run', '--no-default-browser-check'],
                accept_downloads=False,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(ASSIGNMENTS_URL, wait_until='domcontentloaded', timeout=30000)
                if login:
                    finish = time.monotonic() + 20*60
                    while time.monotonic() < finish and context.pages and not STOP.exists():
                        for candidate in context.pages:
                            if assignments_page(candidate) and candidate.locator('#id_status').count():
                                page = candidate
                                break
                        if assignments_page(page) and page.locator('#id_status').count():
                            break
                        page.wait_for_timeout(750)
                    else:
                        state('login_required')
                        return 0
                if not assignments_page(page):
                    if any(part in urlsplit(page.url).hostname for part in ['passport', 'id.yandex']):
                        AUTH.unlink(missing_ok=True)
                        state('login_required')
                    else:
                        state('error', error='unexpected_page')
                    return 0
                items = parse_assignments(page.content())
                save_deadlines(items)
                AUTH.touch()
                state('ok', count=len(items))
                return 0
            finally:
                # Closing the context persists its own login and releases the profile.
                context.close()
    except UnsupportedPage:
        state('unsupported')
        return 1
    except Exception as error:
        # Never include HTML, auth URLs, cookies, passwords or browser logs.
        state('error', error=type(error).__name__)
        return 1
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--login', action='store_true')
    parser.add_argument('--once', action='store_true')
    arguments = parser.parse_args()
    sys.exit(main(login=arguments.login))
