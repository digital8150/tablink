"""Minimal client for the scrcpy server control channel (UHID mouse/keyboard + clipboard)."""
import os
import random
import re
import socket
import struct
import subprocess
import sys
import threading
import time


def _find_scrcpy_dir():
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    candidates = [os.environ.get("SCRCPY_DIR"), os.path.join(here, "scrcpy")]
    pkgs = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\WinGet\Packages")
    if os.path.isdir(pkgs):
        for d in sorted(os.listdir(pkgs), reverse=True):
            if d.startswith("Genymobile.scrcpy"):
                for sub in sorted(os.listdir(os.path.join(pkgs, d)), reverse=True):
                    candidates.append(os.path.join(pkgs, d, sub))
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "scrcpy-server")) and os.path.isfile(os.path.join(c, "adb.exe")):
            return c
    raise FileNotFoundError("scrcpy 폴더를 찾을 수 없습니다 (scrcpy-server, adb.exe 필요)")


SCRCPY_DIR = _find_scrcpy_dir()
ADB = os.path.join(SCRCPY_DIR, "adb.exe")
SCRCPY = os.path.join(SCRCPY_DIR, "scrcpy.exe")
SERVER = os.path.join(SCRCPY_DIR, "scrcpy-server")
DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server-tablink.jar"
NO_WINDOW = subprocess.CREATE_NO_WINDOW


def _server_version():
    r = subprocess.run([SCRCPY, "--version"], capture_output=True, text=True, creationflags=NO_WINDOW)
    m = re.search(r"scrcpy (\S+)", r.stdout)
    return m.group(1) if m else "5.0.1"


SERVER_VERSION = _server_version()

MSG_SET_CLIPBOARD = 9
MSG_UHID_CREATE = 12
MSG_UHID_INPUT = 13
MSG_UHID_DESTROY = 14

DEV_MSG_CLIPBOARD = 0
DEV_MSG_ACK_CLIPBOARD = 1
DEV_MSG_UHID_OUTPUT = 2

MOUSE_ID = 2
KEYBOARD_ID = 1

# 5 buttons, X/Y 16-bit relative, wheel, AC pan
MOUSE_DESC = bytes([
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x09, 0x01, 0xA1, 0x00,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x05, 0x15, 0x00, 0x25, 0x01,
    0x95, 0x05, 0x75, 0x01, 0x81, 0x02,
    0x95, 0x01, 0x75, 0x03, 0x81, 0x01,
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31,
    0x16, 0x01, 0x80, 0x26, 0xFF, 0x7F, 0x75, 0x10, 0x95, 0x02, 0x81, 0x06,
    0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,
    0x05, 0x0C, 0x0A, 0x38, 0x02, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,
    0xC0, 0xC0,
])

# boot-style keyboard: modifiers, reserved, 6 keys (usages 0x00-0xE7), 5 LEDs out
KEYBOARD_DESC = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01,
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    0x75, 0x08, 0x95, 0x01, 0x81, 0x01,
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05, 0x75, 0x01, 0x95, 0x05, 0x91, 0x02,
    0x75, 0x03, 0x95, 0x01, 0x91, 0x01,
    0x05, 0x07, 0x19, 0x00, 0x29, 0xE7, 0x15, 0x00, 0x26, 0xE7, 0x00, 0x75, 0x08, 0x95, 0x06, 0x81, 0x00,
    0xC0,
])


def adb(*args, check=True, timeout=15):
    r = subprocess.run([ADB, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=NO_WINDOW, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout


class TabletInfo:
    """Logical screen size and pointer gain (tablet px per HID count) of the UHID mouse."""

    def __init__(self, width=2960, height=1848, gain_x=1.786, gain_y=1.786, linear=True):
        self.width, self.height = width, height
        self.gain_x, self.gain_y = gain_x, gain_y
        self.linear = linear

    @classmethod
    def query(cls, serial):
        out = adb("-s", serial, "shell", "dumpsys", "input", timeout=10)
        info = cls()
        m = re.search(r"displayId=0,.*?logicalFrame=\[(-?\d+), (-?\d+), (\d+), (\d+)\]", out)
        if m:
            info.width = int(m.group(3)) - int(m.group(1))
            info.height = int(m.group(4)) - int(m.group(2))
        sec_start = out.find(": Multi Control Mouse\n", out.find("Input Reader State"))
        if sec_start >= 0:
            sec = out[sec_start:sec_start + 4000]
            sx = re.search(r"XScale: ([\d.]+)", sec)
            sy = re.search(r"YScale: ([\d.]+)", sec)
            curve = re.search(r"Acceleration Curve[^\n]*\n((?:\s+\{[^\n]*\n)+)", sec)
            base = 1.0
            if curve:
                segs = re.findall(r"\{([^,]+), ([\d.]+), ([-\d.]+)\}", curve.group(1))
                if segs:
                    base = float(segs[0][1])
                    info.linear = len(segs) == 1
            if sx and sy:
                info.gain_x = float(sx.group(1)) * base
                info.gain_y = float(sy.group(1)) * base
        return info


class ScrcpyControl:
    def __init__(self, serial, on_clipboard=None):
        self.serial = serial
        self.on_clipboard = on_clipboard
        self.sock = None
        self.proc = None
        self.port = None
        self.lock = threading.Lock()
        self.alive = False
        self._seq = 1

    def start(self):
        adb("-s", self.serial, "push", SERVER, DEVICE_SERVER_PATH, timeout=30)
        scid = random.randint(0, 0x7FFFFFFF)
        self.port = int(adb("-s", self.serial, "forward", "tcp:0",
                            f"localabstract:scrcpy_{scid:08x}").strip())
        self.proc = subprocess.Popen(
            [ADB, "-s", self.serial, "shell", f"CLASSPATH={DEVICE_SERVER_PATH}", "app_process", "/",
             "com.genymobile.scrcpy.Server", SERVER_VERSION, f"scid={scid:08x}", "log_level=warn",
             "video=false", "audio=false", "control=true", "tunnel_forward=true",
             "clipboard_autosync=true", "power_on=false", "cleanup=false"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW)
        deadline = time.time() + 10
        while True:
            try:
                s = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                # adb forward accepts eagerly; the dummy byte proves the server accepted
                if s.recv(1) == b"\x00":
                    break
                s.close()
            except OSError:
                pass
            if time.time() > deadline or self.proc.poll() is not None:
                self.stop()
                raise RuntimeError("scrcpy 서버 시작 실패")
            time.sleep(0.2)
        s.settimeout(None)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._recv_exact(s, 64)  # device name
        self.sock = s
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        self._uhid_create(MOUSE_ID, "Multi Control Mouse", MOUSE_DESC)
        self._uhid_create(KEYBOARD_ID, "Multi Control Keyboard", KEYBOARD_DESC)

    @staticmethod
    def _recv_exact(s, n):
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def _reader(self):
        try:
            while True:
                t = self._recv_exact(self.sock, 1)[0]
                if t == DEV_MSG_CLIPBOARD:
                    n = struct.unpack(">I", self._recv_exact(self.sock, 4))[0]
                    text = self._recv_exact(self.sock, n).decode("utf-8", "replace")
                    if self.on_clipboard:
                        self.on_clipboard(text)
                elif t == DEV_MSG_ACK_CLIPBOARD:
                    self._recv_exact(self.sock, 8)
                elif t == DEV_MSG_UHID_OUTPUT:
                    _, n = struct.unpack(">HH", self._recv_exact(self.sock, 4))
                    self._recv_exact(self.sock, n)
                else:
                    break
        except (OSError, ConnectionError):
            pass
        self.alive = False

    def _send(self, data):
        if not self.sock:
            return
        with self.lock:
            try:
                self.sock.sendall(data)
            except OSError:
                self.alive = False

    def _uhid_create(self, uid, name, desc):
        n = name.encode()
        self._send(struct.pack(">BHHHB", MSG_UHID_CREATE, uid, 0, 0, len(n)) + n
                   + struct.pack(">H", len(desc)) + desc)

    def _uhid_input(self, uid, data):
        self._send(struct.pack(">BHH", MSG_UHID_INPUT, uid, len(data)) + data)

    def mouse(self, dx=0, dy=0, buttons=0, wheel=0, hwheel=0):
        dx = max(-32767, min(32767, int(dx)))
        dy = max(-32767, min(32767, int(dy)))
        wheel = max(-127, min(127, int(wheel)))
        hwheel = max(-127, min(127, int(hwheel)))
        self._uhid_input(MOUSE_ID, struct.pack("<Bhhbb", buttons & 0x1F, dx, dy, wheel, hwheel))

    def keyboard(self, modifiers, keys):
        keys = list(keys)[:6]
        keys += [0] * (6 - len(keys))
        self._uhid_input(KEYBOARD_ID, bytes([modifiers & 0xFF, 0, *keys]))

    def set_clipboard(self, text):
        raw = text.encode("utf-8")[:(1 << 18) - 14]
        self._seq += 1
        self._send(struct.pack(">BQBI", MSG_SET_CLIPBOARD, self._seq, 0, len(raw)) + raw)

    def stop(self):
        self.alive = False
        if self.sock:
            try:
                self.keyboard(0, [])
                self.mouse()
                self._send(struct.pack(">BH", MSG_UHID_DESTROY, MOUSE_ID))
                self._send(struct.pack(">BH", MSG_UHID_DESTROY, KEYBOARD_ID))
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self.proc:
            self.proc.terminate()
            self.proc = None
        if self.port:
            adb("-s", self.serial, "forward", "--remove", f"tcp:{self.port}", check=False)
            self.port = None
