"""Edge-crossing state machine: routes PC mouse/keyboard to the tablet like an extra monitor."""
import threading

import winio
from scrcpy_ctrl import TabletInfo

VK_CTRL = {0x11, 0xA2, 0xA3}
VK_ALT = {0x12, 0xA4, 0xA5}
VK_M = 0x4D

BTN_BITS = {
    winio.WM_LBUTTONDOWN: 1, winio.WM_LBUTTONUP: 1,
    winio.WM_RBUTTONDOWN: 2, winio.WM_RBUTTONUP: 2,
    winio.WM_MBUTTONDOWN: 4, winio.WM_MBUTTONUP: 4,
}
BTN_DOWN = {winio.WM_LBUTTONDOWN, winio.WM_RBUTTONDOWN, winio.WM_MBUTTONDOWN, winio.WM_XBUTTONDOWN}


def _signed16(v):
    v = (v >> 16) & 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class MultiControl:
    def __init__(self, on_state=None, on_enter=None):
        self.on_state = on_state      # callback(active: bool)
        self.on_enter = on_enter      # callback() when the tablet gains input (clipboard push)
        self.ctrl = None
        self.info = TabletInfo()
        self.enabled = True
        self.side = "right"           # where the tablet sits relative to the monitor
        self.monitor_index = -1       # -1: auto
        self.speed = 1.0              # tablet px per PC px
        self.edge_push = 2            # consecutive edge events needed to cross
        self.hangul_mode = "shift_space"
        self.lock = threading.RLock()

        self.active = False
        self.mon = None
        self.park = self.exit_point = (0, 0)
        self.tx = self.ty = 0.0
        self.rx = self.ry = 0.0
        self.buttons = 0
        self.wheel_acc = self.hwheel_acc = 0
        self.pc_buttons = 0
        self.edge_hits = 0
        self.mods = 0
        self.keys = []                # HID usages held on tablet (max 6)
        self.tablet_vks = set()       # vks whose down went to the tablet
        self.pc_vks = set()           # vks whose down went to the PC
        self.swallow_up = set()       # vks whose up must not reach the PC
        self.held_ctrl = set()
        self.held_alt = set()
        self.hook = winio.InputHook(self._mouse_cb, self._key_cb)

    def start(self):
        self.hook.start()

    def stop(self):
        with self.lock:
            if self.active:
                self._leave(None)
        self.hook.stop()

    def set_ctrl(self, ctrl):
        with self.lock:
            if ctrl is None and self.active:
                self._leave(None)
            self.ctrl = ctrl

    def _ready(self):
        return self.enabled and self.ctrl is not None and self.ctrl.alive

    def refresh_monitors(self):
        self._mons = winio.monitors()

    def _monitors(self):
        return getattr(self, "_mons", None) or winio.monitors()

    def _monitor(self):
        mons = self._monitors()
        if 0 <= self.monitor_index < len(mons):
            return mons[self.monitor_index]
        # auto: the outermost monitor in the tablet's direction
        key = {"right": lambda m: -m.right, "left": lambda m: m.left,
               "top": lambda m: m.top, "bottom": lambda m: -m.bottom}[self.side]
        return min(mons, key=key)

    def _covered(self, x, y):
        return any(m.left <= x < m.right and m.top <= y < m.bottom for m in self._monitors())

    # ---------- mouse ----------
    def _mouse_cb(self, msg, x, y, data, injected):
        with self.lock:
            if self.active and not self._ready():
                self._leave(None)
            if not self.active:
                if not injected:
                    self._track_pc_buttons(msg, data)
                if msg == winio.WM_MOUSEMOVE and not injected and self._ready() and self.pc_buttons == 0:
                    if self._at_edge(x, y):
                        self.edge_hits += 1
                        if self.edge_hits >= self.edge_push:
                            self.edge_hits = 0
                            self._enter(x, y)
                            return True
                    else:
                        self.edge_hits = 0
                return False
            # ---- tablet mode: everything is swallowed ----
            if msg == winio.WM_MOUSEMOVE:
                if not injected:
                    dx, dy = x - self.park[0], y - self.park[1]
                    if dx or dy:
                        self._move(dx, dy)
            elif msg in BTN_BITS:
                bit = BTN_BITS[msg]
                self.buttons = self.buttons | bit if msg in BTN_DOWN else self.buttons & ~bit
                self.ctrl.mouse(buttons=self.buttons)
            elif msg in (winio.WM_XBUTTONDOWN, winio.WM_XBUTTONUP):
                bit = 8 if (data >> 16) & 0xFFFF == 1 else 16
                self.buttons = self.buttons | bit if msg in BTN_DOWN else self.buttons & ~bit
                self.ctrl.mouse(buttons=self.buttons)
            elif msg == winio.WM_MOUSEWHEEL:
                self.wheel_acc += _signed16(data)
                n = int(self.wheel_acc / 120)
                if n:
                    self.wheel_acc -= n * 120
                    self.ctrl.mouse(buttons=self.buttons, wheel=n)
            elif msg == winio.WM_MOUSEHWHEEL:
                self.hwheel_acc += _signed16(data)
                n = int(self.hwheel_acc / 120)
                if n:
                    self.hwheel_acc -= n * 120
                    self.ctrl.mouse(buttons=self.buttons, hwheel=n)
            return True

    def _track_pc_buttons(self, msg, data):
        if msg in BTN_BITS:
            bit = BTN_BITS[msg]
        elif msg in (winio.WM_XBUTTONDOWN, winio.WM_XBUTTONUP):
            bit = 8 if (data >> 16) & 0xFFFF == 1 else 16
        else:
            return
        self.pc_buttons = self.pc_buttons | bit if msg in BTN_DOWN else self.pc_buttons & ~bit

    def _at_edge(self, x, y):
        # an edge shared with another monitor never leads to the tablet
        m = self.mon = self._monitor()
        if self.side == "right":
            return x >= m.right - 1 and m.top <= y < m.bottom and not self._covered(m.right, y)
        if self.side == "left":
            return x <= m.left and m.top <= y < m.bottom and not self._covered(m.left - 1, y)
        if self.side == "top":
            return y <= m.top and m.left <= x < m.right and not self._covered(x, m.top - 1)
        return y >= m.bottom - 1 and m.left <= x < m.right and not self._covered(x, m.bottom)

    def _enter(self, x, y, center=False):
        m = self.mon or self._monitor()
        W, H = self.info.width, self.info.height
        fx = min(max((x - m.left) / m.width, 0), 1)
        fy = min(max((y - m.top) / m.height, 0), 1)
        if center:
            tx, ty = W / 2, H / 2
            px, py = x, y
        elif self.side == "right":
            tx, ty, px, py = 0, fy * (H - 1), m.right - 1, y
        elif self.side == "left":
            tx, ty, px, py = W - 1, fy * (H - 1), m.left, y
        elif self.side == "top":
            tx, ty, px, py = fx * (W - 1), H - 1, x, m.top
        else:
            tx, ty, px, py = fx * (W - 1), 0, x, m.bottom - 1
        # slam to the top-left corner, then move to the target: pointer has no acceleration
        self.ctrl.mouse(-32767, -32767)
        ix, iy = round(tx / self.info.gain_x), round(ty / self.info.gain_y)
        self.ctrl.mouse(ix, iy)
        self.tx = min(ix * self.info.gain_x, W - 1)
        self.ty = min(iy * self.info.gain_y, H - 1)
        self.rx = self.ry = 0.0
        self.buttons = 0
        self.wheel_acc = self.hwheel_acc = 0
        # park at the monitor centre: hook coordinates are clipped to the desktop, so an edge
        # park point would lose motion towards the outside
        self.park = ((m.left + m.right) // 2, (m.top + m.bottom) // 2)
        self.exit_point = (int(px), int(py))
        self.active = True
        self.hook.show_blocker(*self.park)
        winio.set_cursor_pos(*self.park)
        if self.on_state:
            self.on_state(True)
        if self.on_enter:
            self.on_enter()

    def _move(self, dx, dy):
        W, H = self.info.width, self.info.height
        nx = self.tx + dx * self.speed
        ny = self.ty + dy * self.speed
        side = self.side
        if (side == "right" and nx < 0) or (side == "left" and nx > W - 1) \
                or (side == "top" and ny > H - 1) or (side == "bottom" and ny < 0):
            self._leave((nx, ny))
            return
        nx = min(max(nx, 0), W - 1)
        ny = min(max(ny, 0), H - 1)
        cx = (nx - self.tx) / self.info.gain_x + self.rx
        cy = (ny - self.ty) / self.info.gain_y + self.ry
        ix, iy = round(cx), round(cy)
        self.rx, self.ry = cx - ix, cy - iy
        if ix or iy:
            self.ctrl.mouse(ix, iy, buttons=self.buttons)
        self.tx = min(max(self.tx + ix * self.info.gain_x, 0), W - 1)
        self.ty = min(max(self.ty + iy * self.info.gain_y, 0), H - 1)

    def _leave(self, tablet_pos):
        """tablet_pos: where the pointer exited, or None to go back where it entered."""
        self.active = False
        ctrl = self.ctrl
        if ctrl and ctrl.alive:
            ctrl.keyboard(0, [])
            ctrl.mouse(buttons=0)
        self.swallow_up |= self.tablet_vks
        self.tablet_vks.clear()
        self.keys = []
        self.mods = 0
        self.buttons = 0
        self.edge_hits = 0
        self.hook.hide_blocker()
        m = self.mon or self._monitor()
        if tablet_pos is None:
            x, y = self.exit_point
            if self._at_edge(x, y):  # don't bounce straight back into the tablet
                x += {"right": -3, "left": 2}.get(self.side, 0)
                y += {"bottom": -3, "top": 2}.get(self.side, 0)
        else:
            W, H = self.info.width, self.info.height
            fx = min(max(tablet_pos[0] / max(W - 1, 1), 0), 1)
            fy = min(max(tablet_pos[1] / max(H - 1, 1), 0), 1)
            if self.side == "right":
                x, y = m.right - 3, m.top + fy * (m.height - 1)
            elif self.side == "left":
                x, y = m.left + 2, m.top + fy * (m.height - 1)
            elif self.side == "top":
                x, y = m.left + fx * (m.width - 1), m.top + 2
            else:
                x, y = m.left + fx * (m.width - 1), m.bottom - 3
        winio.set_cursor_pos(x, y)
        if self.on_state:
            self.on_state(False)

    # ---------- keyboard ----------
    def _key_cb(self, vk, scan, extended, down, injected):
        if injected:
            return False
        with self.lock:
            held = self.held_ctrl if vk in VK_CTRL else self.held_alt if vk in VK_ALT else None
            if held is not None:
                (held.add if down else held.discard)(vk)
            if vk == VK_M and self.held_ctrl and self.held_alt and self._ready():
                if down:
                    if self.active:
                        self._leave(None)
                    else:
                        x, y = winio.get_cursor_pos()
                        self.mon = self._monitor()
                        self._enter(x, y, center=True)
                    self.swallow_up.add(vk)
                return True
            if not self.active:
                if down:
                    self.pc_vks.add(vk)
                    return False
                if vk in self.swallow_up:
                    self.swallow_up.discard(vk)
                    return True
                self.pc_vks.discard(vk)
                return False
            # ---- tablet mode ----
            if not down and vk in self.pc_vks and vk not in self.tablet_vks:
                self.pc_vks.discard(vk)  # PC saw the down, let it see the up
                return False
            if down and vk in self.pc_vks:
                return True              # autorepeat of a key held before crossing
            self._send_key(vk, scan, extended, down)
            return True

    def _send_key(self, vk, scan, extended, down):
        if vk == winio.VK_HANGUL and self.hangul_mode == "shift_space":
            if down and vk not in self.tablet_vks:
                self.tablet_vks.add(vk)
                self.ctrl.keyboard(self.mods | 0x02, self.keys + [winio.HID_SPACE])
                self.ctrl.keyboard(self.mods, self.keys)
            elif not down:
                self.tablet_vks.discard(vk)
            return
        usage = winio.vk_scan_to_hid(vk, scan, extended)
        if usage is None:
            return
        if down:
            self.tablet_vks.add(vk)
        else:
            self.tablet_vks.discard(vk)
        if 0xE0 <= usage <= 0xE7:
            bit = 1 << (usage - 0xE0)
            new = self.mods | bit if down else self.mods & ~bit
            if new == self.mods:
                return
            self.mods = new
        elif down:
            if usage in self.keys:
                return  # autorepeat: Android repeats on its own
            self.keys = (self.keys + [usage])[-6:]
        else:
            if usage not in self.keys:
                return
            self.keys.remove(usage)
        self.ctrl.keyboard(self.mods, self.keys)
