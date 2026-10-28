"""TabLink core: config, child-process lifetime and the device/session manager."""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import winreg

import winio

import devices
from scrcpy_ctrl import NO_WINDOW, SCRCPY, ScrcpyControl, TabletInfo

APP_NAME = "TabLink"
CONFIG_DIR = os.path.join(os.environ["APPDATA"], APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DEFAULTS = {
    "device_id": "", "transport": "auto", "auto_wifi": True, "known_endpoints": {},
    "audio": True, "audio_dup": False, "audio_buffer": 50,
    "mc": True, "side": "right", "monitor": -1, "speed": 1.0, "clipboard": True, "hangul": "shift_space",
    "autostart": False, "close_to_tray": True,
}
SIDES = [("right", "오른쪽"), ("left", "왼쪽"), ("top", "위"), ("bottom", "아래")]
TRANSPORTS = [("auto", "자동 (USB 우선, 끊기면 Wi-Fi)"), ("usb", "USB만"), ("wifi", "Wi-Fi만")]
HANGUL = [("shift_space", "Shift+Space (삼성 키보드)"), ("lang1", "한/영 키 그대로")]


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---- child processes die with us (Job object, kill on close) ----
class _JobLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _JobExtLimit(ctypes.Structure):
    _fields_ = [("Basic", _JobLimit), ("Io", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateJobObjectW.restype = ctypes.c_void_p
_k32.OpenProcess.restype = ctypes.c_void_p
_k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
_k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_JOB = _k32.CreateJobObjectW(None, None)
_lim = _JobExtLimit()
_lim.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
_k32.SetInformationJobObject(_JOB, 9, ctypes.byref(_lim), ctypes.sizeof(_lim))


def bind_to_job(proc):
    h = _k32.OpenProcess(0x0101, False, proc.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
    if h:
        _k32.AssignProcessToJobObject(_JOB, h)
        _k32.CloseHandle(h)


def set_autostart(enabled):
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    with key:
        if enabled:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}" --tray'
            else:
                pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                cmd = f'"{pyw}" "{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')}" --tray'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


class Session:
    """Everything running against one adb transport of the tablet."""

    def __init__(self, transport):
        self.transport = transport
        self.ctrl = None
        self.audio = None
        self.audio_sig = None

    @property
    def serial(self):
        return self.transport.serial

    def stop(self):
        if self.ctrl:
            self.ctrl.stop()
            self.ctrl = None
        self.stop_audio()

    def stop_audio(self):
        if self.audio:
            self.audio.terminate()
            try:
                self.audio.wait(3)
            except subprocess.TimeoutExpired:
                self.audio.kill()
            self.audio = None
            self.audio_sig = None


class Manager(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.cfg = app.cfg
        self.wake = threading.Event()
        self.stopping = False
        self.session = None
        self.last_mdns = 0
        self.last_clip_seq = None

    def log(self, msg):
        self.app.post(lambda: self.app.log(msg))

    def run(self):
        while not self.stopping:
            try:
                self.tick()
            except Exception as e:
                self.log(f"오류: {e}")
            self.wake.wait(1.0)
            self.wake.clear()
        if self.session:
            self.app.mc.set_ctrl(None)
            self.session.stop()

    # ---------------------------------------------------------------
    def _allowed(self, t):
        mode = self.cfg["transport"]
        return t.state == "device" and (mode == "auto" or (mode == "wifi") == t.wireless)

    def _best(self, ts):
        ok = [t for t in ts if t.device_id == self.cfg["device_id"] and self._allowed(t)]
        ok.sort(key=lambda t: t.wireless)  # USB first
        return ok[0] if ok else None

    def _discover_wifi(self, ts, force=False):
        if not self.cfg["auto_wifi"] or self.cfg["transport"] == "usb":
            return False
        if not force and time.time() - self.last_mdns < 15:
            return False
        self.last_mdns = time.time()
        present = {t.serial for t in ts if t.state == "device"}
        have_wifi = {t.device_id for t in ts if t.wireless and t.state == "device"}
        changed = False
        candidates = devices.mdns_endpoints()
        known = self.cfg["known_endpoints"]
        candidates += [(d, ep) for d, ep in known.items() if (d, ep) not in candidates]
        for did, ep in candidates:
            if ep in present or did in have_wifi:
                continue
            ok, out = devices.connect(ep)
            if ok:
                self.log(f"Wi-Fi 연결됨: {ep}")
                have_wifi.add(did)
                changed = True
        return changed

    def tick(self):
        ts = devices.list_transports()
        cur = self.session
        cur_ok = cur and any(t.serial == cur.serial and self._allowed(t) for t in ts)
        if self._discover_wifi(ts, force=not cur_ok):
            ts = devices.list_transports()

        for t in ts:
            if t.wireless and t.state == "device" and ":" in t.serial and t.device_id:
                if self.cfg["known_endpoints"].get(t.device_id) != t.serial:
                    self.cfg["known_endpoints"][t.device_id] = t.serial
                    save_config(self.cfg)
        ids = {}
        for t in ts:
            if t.state == "device":
                ids.setdefault(t.device_id, t.model)
        if self.cfg["device_id"] not in ids and ids:
            self.cfg["device_id"] = next(iter(ids))
            save_config(self.cfg)
        self.app.post(lambda: self.app.show_devices(ids, ts))

        best = self._best(ts)
        cur = self.session
        if cur and not cur_ok:
            self.log(f"{cur.transport.kind} 연결 끊김 ({cur.serial})")
            self._end_session()
            cur = None
        elif cur and best and cur.transport.wireless and not best.wireless and not self.app.mc.active:
            self.log("USB가 연결되어 USB로 전환합니다")
            self._end_session()
            cur = None
        if not cur:
            if not best:
                self.app.post(lambda: self.app.show_status(None))
                return
            cur = self.session = Session(best)
            self.log(f"{best.kind}로 연결: {best.model} ({best.serial})")

        # ---- multi control ----
        if self.cfg["mc"]:
            if not (cur.ctrl and cur.ctrl.alive):
                if cur.ctrl:
                    self.app.mc.set_ctrl(None)
                    cur.ctrl.stop()
                    self.log("제어 채널 재시작")
                ctrl = ScrcpyControl(cur.serial, on_clipboard=self._on_device_clipboard)
                ctrl.start()
                cur.ctrl = ctrl
                time.sleep(0.3)  # let the UHID mouse register before reading its parameters
            try:
                info = TabletInfo.query(cur.serial)
                if not info.linear:
                    self.log("주의: 태블릿 마우스 가속이 켜져 있어 커서 추적이 부정확할 수 있습니다")
                self.app.mc.info = info
            except Exception:
                pass
            self.app.mc.set_ctrl(cur.ctrl)
        elif cur.ctrl:
            self.app.mc.set_ctrl(None)
            cur.ctrl.stop()
            cur.ctrl = None
        self.app.mc.refresh_monitors()

        # ---- audio ----
        sig = (self.cfg["audio_dup"], int(self.cfg["audio_buffer"]))
        if self.cfg["audio"]:
            if cur.audio and (cur.audio.poll() is not None or cur.audio_sig != sig):
                if cur.audio.poll() is not None:
                    self.log("소리 전송이 종료되어 다시 시작합니다")
                cur.stop_audio()
            if not cur.audio:
                self._start_audio(cur, sig)
        elif cur.audio:
            cur.stop_audio()

        self.app.post(lambda: self.app.show_status(cur))

    def _end_session(self):
        self.app.mc.set_ctrl(None)
        self.session.stop()
        self.session = None

    def _start_audio(self, cur, sig):
        dup, buf = sig
        cmd = [SCRCPY, "-s", cur.serial, "--no-video", "--no-control", "--no-window",
               f"--audio-buffer={buf}", "--no-power-on"]
        if dup:
            cmd.append("--audio-dup")
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
        bind_to_job(p)
        cur.audio = p
        cur.audio_sig = sig
        self.log("소리 전송 시작")

        def pump():
            for line in p.stdout:
                line = line.strip()
                if line and ("ERROR" in line or "WARN" in line):
                    self.log("scrcpy: " + line)
        threading.Thread(target=pump, daemon=True).start()

    # ---- clipboard ----
    def _on_device_clipboard(self, text):
        if self.cfg["clipboard"] and text:
            winio.set_clipboard_text(text)
            self.last_clip_seq = winio.clipboard_seq()

    def push_clipboard(self):
        if not self.cfg["clipboard"]:
            return
        seq = winio.clipboard_seq()
        if seq == self.last_clip_seq:
            return
        self.last_clip_seq = seq
        text = winio.get_clipboard_text()
        s = self.session
        if text and s and s.ctrl and s.ctrl.alive:
            s.ctrl.set_clipboard(text)
