"""Attach our own window above desktop icons and below normal application windows."""
import ctypes
import time as clock
from ctypes import wintypes as w

u = ctypes.WinDLL("user32", use_last_error=True)
CALLBACK = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [CALLBACK, w.LPARAM]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.GetParent.argtypes = [w.HWND]
u.GetParent.restype = w.HWND
u.SetParent.argtypes = [w.HWND, w.HWND]
u.SetParent.restype = w.HWND
u.IsWindow.argtypes = [w.HWND]
u.IsWindowVisible.argtypes = [w.HWND]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
u.GetWindowLongW.restype = ctypes.c_long
u.SetWindowLongW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_long]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
u.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.SetLayeredWindowAttributes.argtypes = [w.HWND, w.DWORD, w.BYTE, w.DWORD]
u.GetLayeredWindowAttributes.argtypes = [w.HWND, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.BYTE), ctypes.POINTER(w.DWORD)]
u.RedrawWindow.argtypes = [w.HWND, ctypes.c_void_p, ctypes.c_void_p, w.UINT]


def desktop_host():
    found = []
    @CALLBACK
    def visit(hwnd, _):
        if u.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            found.append(hwnd)
        return True
    u.EnumWindows(visit, 0)
    return found[0] if found else None


def bounds(hwnd):
    rect = w.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError("Widget window is unavailable")
    return [rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top]


def wait_for_desktop(timeout=120, poll=0.5):
    deadline=clock.monotonic()+timeout
    while True:
        host=desktop_host()
        if host:
            return host
        if clock.monotonic() >= deadline:
            return None
        clock.sleep(poll)


class DesktopAnchor:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.enabled = False
        self.hidden = False
        self.host = None
        self.requested = False
        self.requested_topmost = False

    def configure(self, enabled, topmost=False):
        self.requested = bool(enabled)
        self.requested_topmost = bool(topmost)
        saved = bounds(self.hwnd)
        style = ctypes.c_uint32(u.GetWindowLongW(self.hwnd, -16)).value
        extended = ctypes.c_uint32(u.GetWindowLongW(self.hwnd, -20)).value
        if enabled:
            host = desktop_host()
            if not host:
                return False
            # WS_CHILD, rather than a top-level popup, is unaffected by Show Desktop.
            if u.GetParent(self.hwnd) != host:
                u.SetWindowLongW(self.hwnd, -16, (style & ~0x80000000) | 0x40000000)
                u.SetParent(self.hwnd, host)
                if u.GetParent(self.hwnd) != host:
                    u.SetWindowLongW(self.hwnd, -16, style)
                    return False
            u.SetWindowLongW(self.hwnd, -20, (extended & ~0x40000) | 0x80)
            self.enabled, self.host = True, host
            point = w.POINT(saved[0], saved[1])
            u.ScreenToClient(host, ctypes.byref(point))
            u.SetWindowPos(self.hwnd, 0, point.x, point.y, saved[2], saved[3], 0x0010 | 0x0020)
        else:
            if self.enabled or u.GetParent(self.hwnd):
                u.SetParent(self.hwnd, None)
                u.SetWindowLongW(self.hwnd, -16, (style & ~0x40000000) | 0x80000000)
            u.SetWindowLongW(self.hwnd, -20, (extended | 0x40000) & ~0x80)
            self.enabled, self.host = False, None
            u.SetWindowPos(self.hwnd, -1 if topmost else -2, *saved, 0x0010 | 0x0020)
        # Desktop-hosted GDI windows can otherwise inherit transparent composition
        # from Explorer/live wallpapers. Give the whole dark surface explicit opacity.
        self.opaque_backing()
        if not self.hidden:
            self.show()
        return True

    def opaque_backing(self):
        extended=ctypes.c_uint32(u.GetWindowLongW(self.hwnd,-20)).value
        u.SetWindowLongW(self.hwnd,-20,extended | 0x80000)
        result=bool(u.SetLayeredWindowAttributes(self.hwnd,0,255,0x2))
        u.RedrawWindow(self.hwnd,None,None,0x185)
        return result

    def show(self):
        self.hidden = False
        if self.enabled:
            u.ShowWindow(self.hwnd, 4)
            # HWND_TOP affects only siblings on the desktop, never windows above it.
            u.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
        else:
            u.ShowWindow(self.hwnd, 9)

    def minimize(self):
        if self.enabled:
            self.hidden = True
            u.ShowWindow(self.hwnd, 0)
        else:
            u.ShowWindow(self.hwnd, 6)

    def maintain(self):
        if self.requested and (not self.enabled or not u.IsWindow(self.host)
                               or u.GetParent(self.hwnd) != self.host):
            try:
                return self.configure(True,self.requested_topmost)
            except OSError:
                return False
        return True

    def report(self):
        color,alpha,flags=w.DWORD(),w.BYTE(),w.DWORD()
        has_alpha=u.GetLayeredWindowAttributes(self.hwnd,ctypes.byref(color),ctypes.byref(alpha),ctypes.byref(flags))
        return {"desktop_mode": self.enabled, "desktop_host": self.host or 0,
                "parent_handle": u.GetParent(self.hwnd) or 0,
                "visible": bool(u.IsWindowVisible(self.hwnd)), "hidden_by_user": self.hidden,
                "opaque_background":bool(has_alpha and flags.value & 2 and alpha.value==255)}
