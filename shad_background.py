"""Bounded scheduled worker. Only its own browser process tree is cleaned up."""
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time

from app_paths import CODE_ROOT
from deadline_core import ROOT, MOSCOW, STATUS, atomic_json, read_json


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                ('max_working_set', ctypes.c_size_t), ('active_limit', wintypes.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                ('scheduling', wintypes.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ['read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes']]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IoCounters),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class OwnProcessJob:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                        ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            process.kill()
            process.wait(timeout=5)
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run():
    job, process, result = None, None, 1
    forced, terminal_at = False, None
    cache = ROOT / 'shad-deadlines.json'
    before = cache.stat().st_mtime_ns if cache.exists() else 0
    try:
        job = OwnProcessJob()
        # Explicit stdio and a hidden console make subprocess cleanup predictable
        # when launched in the Task Scheduler session rather than from the widget.
        process = subprocess.Popen(
            [str(Path(sys.executable).with_name('python.exe')), str(CODE_ROOT/'shad_sync.py'), '--once'],
            cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job.assign(process)
        started = time.monotonic()
        while time.monotonic()-started < 90:
            code = process.poll()
            if code is not None:
                result = code
                break
            status = read_json(STATUS, {})
            if status.get('pid') == process.pid and status.get('state') in {
                    'ok', 'login_required', 'error', 'unsupported'}:
                terminal_at = terminal_at or time.monotonic()
                if time.monotonic()-terminal_at > 10:
                    # The fetch has finished; stop only this job's browser if its
                    # close handshake stalled. Other Edge windows are untouched.
                    result = 0 if status['state'] in {'ok', 'login_required'} else 1
                    forced = True
                    break
            time.sleep(0.25)
        else:
            atomic_json(STATUS, {'state':'error', 'error':'background_timeout',
                                 'checked_at':datetime.now(MOSCOW).isoformat()})
            forced = True
    except Exception as error:
        atomic_json(STATUS, {'state':'error', 'error':type(error).__name__,
                             'checked_at':datetime.now(MOSCOW).isoformat()})
    finally:
        if job:
            job.close()
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                result = 1
        after = cache.stat().st_mtime_ns if cache.exists() else 0
        atomic_json(ROOT/'shad-background-last-run.json', {
            'finished_at':datetime.now(MOSCOW).isoformat(), 'result':result,
            'cache_updated':after > before, 'cleanup_forced':forced,
        })
    return result


if __name__ == '__main__':
    sys.exit(run())
