"""Win32 helpers: DPI awareness, monitors, low-level input hooks, hidden-cursor window, clipboard."""
import ctypes
import threading
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_MOUSEMOVE = 0x200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x201, 0x202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x204, 0x205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x207, 0x208
WM_MOUSEWHEEL = 0x20A
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x20B, 0x20C
WM_MOUSEHWHEEL = 0x20E
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_SETCURSOR = 0x20
WM_APP = 0x8000
WM_QUIT = 0x12

LLKHF_EXTENDED = 0x01
LLMHF_INJECTED = 0x01


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, wt.BYTE, wt.DWORD]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.SetCursor.argtypes = [wt.HANDLE]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), MONITORENUMPROC, wt.LPARAM]
user32.OpenClipboard.argtypes = [wt.HWND]
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.GetModuleHandleW.restype = wt.HMODULE


def set_dpi_aware():
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


class Monitor:
    def __init__(self, rect, primary, name):
        self.left, self.top, self.right, self.bottom = rect.left, rect.top, rect.right, rect.bottom
        self.primary = primary
        self.name = name

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    def label(self, i):
        return f"{i + 1}: {self.width}x{self.height} @({self.left},{self.top})" + (" 주 모니터" if self.primary else "")


def monitors():
    result = []

    def cb(hmon, hdc, rect, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        result.append(Monitor(mi.rcMonitor, bool(mi.dwFlags & 1), mi.szDevice))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    result.sort(key=lambda m: (not m.primary, m.left, m.top))
    return result


def set_cursor_pos(x, y):
    user32.SetCursorPos(int(x), int(y))


def get_cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ---- clipboard ----
CF_UNICODETEXT = 13


def clipboard_seq():
    return user32.GetClipboardSequenceNumber()


def get_clipboard_text():
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        kernel32.Sleep(20)
    else:
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        kernel32.Sleep(20)
    else:
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, size)  # GMEM_MOVEABLE
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, size)
        kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, h))
    finally:
        user32.CloseClipboard()


# ---- keyboard mapping: Windows set-1 scancode (+extended) -> HID usage ----
_SC = {
    0x01: 0x29, 0x0E: 0x2A, 0x0F: 0x2B, 0x1C: 0x28, 0x39: 0x2C, 0x3A: 0x39,
    0x0C: 0x2D, 0x0D: 0x2E, 0x1A: 0x2F, 0x1B: 0x30, 0x2B: 0x31, 0x27: 0x33, 0x28: 0x34,
    0x29: 0x35, 0x33: 0x36, 0x34: 0x37, 0x35: 0x38, 0x56: 0x64,
    0x1D: 0xE0, 0x2A: 0xE1, 0x38: 0xE2, 0x36: 0xE5,
    0x37: 0x55, 0x45: 0x53, 0x46: 0x47, 0x4A: 0x56, 0x4E: 0x57, 0x53: 0x63,
    0x47: 0x5F, 0x48: 0x60, 0x49: 0x61, 0x4B: 0x5C, 0x4C: 0x5D, 0x4D: 0x5E,
    0x4F: 0x59, 0x50: 0x5A, 0x51: 0x5B, 0x52: 0x62,
    0x57: 0x44, 0x58: 0x45,
}
for _i, _u in enumerate([0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27]):
    _SC[0x02 + _i] = _u  # 1..0
for _i, _u in enumerate([0x14, 0x1A, 0x08, 0x15, 0x17, 0x1C, 0x18, 0x0C, 0x12, 0x13]):
    _SC[0x10 + _i] = _u  # QWERTYUIOP
for _i, _u in enumerate([0x04, 0x16, 0x07, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F]):
    _SC[0x1E + _i] = _u  # ASDFGHJKL
for _i, _u in enumerate([0x1D, 0x1B, 0x06, 0x19, 0x05, 0x11, 0x10]):
    _SC[0x2C + _i] = _u  # ZXCVBNM
for _i in range(10):
    _SC[0x3B + _i] = 0x3A + _i  # F1..F10

_SC_EXT = {
    0x1C: 0x58, 0x1D: 0xE4, 0x35: 0x54, 0x37: 0x46, 0x38: 0xE6,
    0x47: 0x4A, 0x48: 0x52, 0x49: 0x4B, 0x4B: 0x50, 0x4D: 0x4F, 0x4F: 0x4D,
    0x50: 0x51, 0x51: 0x4E, 0x52: 0x49, 0x53: 0x4C, 0x5B: 0xE3, 0x5C: 0xE7, 0x5D: 0x65,
}

VK_HANGUL = 0x15
VK_HANJA = 0x19
VK_PAUSE = 0x13
VK_NUMLOCK = 0x90

HID_SPACE = 0x2C
HID_LSHIFT = 0xE1
HID_LANG1 = 0x90
HID_LANG2 = 0x91


def vk_scan_to_hid(vk, scan, extended):
    if vk == VK_HANGUL:
        return HID_LANG1
    if vk == VK_HANJA:
        return HID_LANG2
    if vk == VK_PAUSE:
        return 0x48
    if vk == VK_NUMLOCK:
        return 0x53
    if extended:
        return _SC_EXT.get(scan)
    return _SC.get(scan)


# ---- hook thread ----
class InputHook:
    """Runs global LL mouse/keyboard hooks plus a transparent cursor-hiding window on one thread.

    mouse_cb(msg, x, y, mouse_data, injected) and key_cb(vk, scan, extended, down, injected)
    return True to swallow the event.
    """

    def __init__(self, mouse_cb, key_cb):
        self.mouse_cb = mouse_cb
        self.key_cb = key_cb
        self.thread_id = None
        self.hwnd = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        self._ready.wait(5)

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    # called from hook thread only (inside callbacks)
    def show_blocker(self, x, y, size=48):
        if self.hwnd:
            user32.SetWindowPos(self.hwnd, wt.HWND(-1), int(x - size // 2), int(y - size // 2),
                                size, size, 0x0010 | 0x0040)  # NOACTIVATE | SHOWWINDOW

    def hide_blocker(self):
        if self.hwnd:
            user32.ShowWindow(self.hwnd, 0)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_SETCURSOR:
            user32.SetCursor(None)
            return 1
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _mouse_proc(self, code, wparam, lparam):
        if code == 0:
            s = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            try:
                if self.mouse_cb(wparam, s.pt.x, s.pt.y, s.mouseData, bool(s.flags & LLMHF_INJECTED)):
                    return 1
            except Exception as e:  # never let an exception kill input
                print("mouse hook error:", e)
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _key_proc(self, code, wparam, lparam):
        if code == 0:
            s = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            try:
                if self.key_cb(s.vkCode, s.scanCode, bool(s.flags & LLKHF_EXTENDED), down, bool(s.flags & 0x10)):
                    return 1
            except Exception as e:
                print("key hook error:", e)
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wndproc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = "TabLinkCursorBlocker"
        user32.RegisterClassExW(ctypes.byref(wc))
        ex = 0x8 | 0x80 | 0x80000 | 0x08000000  # TOPMOST | TOOLWINDOW | LAYERED | NOACTIVATE
        self.hwnd = user32.CreateWindowExW(ex, wc.lpszClassName, "TabLink cursor blocker", 0x80000000,
                                           0, 0, 48, 48, None, None, hinst, None)
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 1, 2)  # alpha 1/255
        self._mouse_ref = HOOKPROC(self._mouse_proc)
        self._key_ref = HOOKPROC(self._key_proc)
        mh = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_ref, hinst, 0)
        kh = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._key_ref, hinst, 0)
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(mh)
        user32.UnhookWindowsHookEx(kh)
        user32.DestroyWindow(self.hwnd)
