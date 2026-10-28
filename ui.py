"""TabLink window (CustomTkinter) and tray icon."""
import os
import queue
import threading
import time

import customtkinter as ctk

import devices
import winio
from core import APP_NAME, CONFIG_DIR, HANGUL, Manager, save_config, load_config, set_autostart
from multicontrol import MultiControl

ACCENT = "#3B82F6"
ACCENT_HOVER = "#2563EB"
BG = ("#F2F4F7", "#111214")
CARD = ("#FFFFFF", "#1B1D21")
CARD_2 = ("#EEF1F5", "#24272D")
TEXT = ("#111827", "#F3F4F6")
MUTED = ("#6B7280", "#9CA3AF")
GREEN = "#22C55E"
AMBER = "#F59E0B"
GRAY = "#6B7280"

SIDE_BUTTONS = [("left", "← 왼쪽"), ("top", "↑ 위"), ("bottom", "↓ 아래"), ("right", "오른쪽 →")]
TRANSPORT_BUTTONS = [("auto", "자동"), ("usb", "USB"), ("wifi", "Wi-Fi")]
SIDE_WORD = {"right": "오른쪽", "left": "왼쪽", "top": "위쪽", "bottom": "아래쪽"}


def _mode_color(c):
    return c[1] if ctk.get_appearance_mode() == "Dark" else c[0] if isinstance(c, tuple) else c


def make_icon_image(size=64):
    from PIL import Image, ImageDraw
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * s, 14 * s, 40 * s, 50 * s), 6 * s, fill=(59, 130, 246))
    d.rounded_rectangle((26 * s, 6 * s, 62 * s, 58 * s), 7 * s, fill=(24, 26, 30),
                        outline=(240, 242, 245), width=max(1, int(3 * s)))
    d.polygon([(10 * s, 25 * s), (22 * s, 32 * s), (10 * s, 39 * s)], fill="white")
    return img


class App:
    def __init__(self, start_hidden):
        self.cfg = load_config()
        self.q = queue.Queue()
        ctk.set_appearance_mode("system")
        self.root = ctk.CTk(fg_color=BG)
        self.root.title("TabLink")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._set_icon()
        self.f = lambda size=13, weight="normal": ctk.CTkFont(family="Malgun Gothic", size=size, weight=weight)

        self.mc = MultiControl(on_state=lambda a: self.post(lambda: self.show_mc_state(a)),
                               on_enter=lambda: threading.Thread(target=self.manager.push_clipboard,
                                                                 daemon=True).start())
        self.apply_mc_config()
        self.mc.refresh_monitors()
        self.session = None
        self.build_ui()
        self.mc.start()
        self.manager = Manager(self)
        self.manager.start()
        self.tray = None
        self.start_tray()
        if start_hidden:
            self.root.withdraw()
        self.root.after(50, self.pump)

    # ---------- plumbing ----------
    def post(self, fn):
        self.q.put(fn)

    def pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(50, self.pump)

    def log(self, msg):
        line = time.strftime("%H:%M:%S  ") + msg
        try:
            with open(os.path.join(CONFIG_DIR, "log.txt"), "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d ") + line + "\n")
        except OSError:
            pass
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def changed(self):
        save_config(self.cfg)
        self.apply_mc_config()
        self.manager.wake.set()
        self.update_tray()
        self.draw_layout()
        self.show_mc_state(self.mc.active)

    def apply_mc_config(self):
        mc = self.mc
        mc.enabled = self.cfg["mc"]
        mc.side = self.cfg["side"]
        mc.monitor_index = int(self.cfg["monitor"])
        mc.speed = float(self.cfg["speed"])
        mc.hangul_mode = self.cfg["hangul"]

    # ---------- widgets ----------
    def card(self, parent, title, subtitle=None):
        frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        head = ctk.CTkFrame(frame, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(head, text=title, font=self.f(15, "bold"), text_color=TEXT).pack(side="left")
        if subtitle:
            ctk.CTkLabel(head, text=subtitle, font=self.f(12), text_color=MUTED).pack(side="left", padx=8)
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        frame.head = head
        return frame, body

    def switch(self, parent, text, key, extra=None, sub=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        texts = ctk.CTkFrame(row, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(texts, text=text, font=self.f(13), text_color=TEXT, anchor="w").pack(fill="x")
        if sub:
            ctk.CTkLabel(texts, text=sub, font=self.f(11), text_color=MUTED, anchor="w").pack(fill="x")
        var = ctk.BooleanVar(value=self.cfg[key])

        def cb():
            self.cfg[key] = var.get()
            if extra:
                extra()
            self.changed()
        sw = ctk.CTkSwitch(row, text="", variable=var, command=cb, width=46, progress_color=ACCENT)
        sw.pack(side="right")
        setattr(self, f"var_{key}", var)
        return row

    def label_row(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(8, 2))
        ctk.CTkLabel(row, text=text, font=self.f(12), text_color=MUTED, anchor="w").pack(side="left")
        return row

    def build_ui(self):
        r = self.root
        outer = ctk.CTkFrame(r, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=18, pady=16)

        # header
        head = ctk.CTkFrame(outer, fg_color="transparent")
        head.pack(fill="x", pady=(0, 12))
        try:
            from PIL import Image
            ic = ctk.CTkImage(light_image=make_icon_image(128), dark_image=make_icon_image(128), size=(36, 36))
            ctk.CTkLabel(head, image=ic, text="").pack(side="left", padx=(2, 10))
        except Exception:
            pass
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="TabLink", font=self.f(22, "bold"), text_color=TEXT, anchor="w").pack(fill="x")
        self.device_lbl = ctk.CTkLabel(titles, text="태블릿을 찾는 중…", font=self.f(12), text_color=MUTED, anchor="w")
        self.device_lbl.pack(fill="x")
        self.pill = ctk.CTkLabel(head, text="●  연결 안 됨", font=self.f(12, "bold"), corner_radius=999,
                                 fg_color=CARD_2, text_color=GRAY, height=30, padx=14)
        self.pill.pack(side="right")

        cols = ctk.CTkFrame(outer, fg_color="transparent")
        cols.pack(fill="both", expand=True)
        left = ctk.CTkFrame(cols, fg_color="transparent", width=470)
        left.pack(side="left", fill="both", expand=True, padx=(0, 7))
        right = ctk.CTkFrame(cols, fg_color="transparent", width=360)
        right.pack(side="left", fill="both", padx=(7, 0))

        # ---- layout / multi control ----
        c, b = self.card(left, "멀티 컨트롤", "마우스를 화면 밖으로 밀면 태블릿으로")
        c.pack(fill="x")
        self.mc_switch_var = ctk.BooleanVar(value=self.cfg["mc"])
        self.var_mc = self.mc_switch_var

        def mc_cb():
            self.cfg["mc"] = self.mc_switch_var.get()
            self.changed()
        ctk.CTkSwitch(c.head, text="", variable=self.mc_switch_var, command=mc_cb, width=46,
                      progress_color=ACCENT).pack(side="right")
        self.canvas = ctk.CTkCanvas(b, height=165, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(fill="x", pady=(2, 6))
        self.canvas.bind("<Configure>", lambda e: self.draw_layout())
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.mc_state_lbl = ctk.CTkLabel(b, text="", font=self.f(12), text_color=MUTED, anchor="w", wraplength=440,
                                         justify="left")
        self.mc_state_lbl.pack(fill="x")

        self.label_row(b, "태블릿 위치  (그림을 클릭해도 바뀝니다)")
        side_labels = [l for _, l in SIDE_BUTTONS]
        self.side_seg = ctk.CTkSegmentedButton(b, values=side_labels, font=self.f(12), height=32,
                                               selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                               command=self.on_side)
        self.side_seg.pack(fill="x")
        self.side_seg.set(dict(SIDE_BUTTONS)[self.cfg["side"]])

        self.label_row(b, "기준 모니터")
        self.mon_menu = ctk.CTkOptionMenu(b, values=["자동"], font=self.f(12), dropdown_font=self.f(12),
                                          fg_color=CARD_2, button_color=CARD_2, button_hover_color=ACCENT,
                                          text_color=TEXT, command=self.on_monitor, height=32)
        self.mon_menu.pack(fill="x")
        self.refresh_monitor_list()

        row = self.label_row(b, "태블릿 커서 속도")
        self.speed_val = ctk.CTkLabel(row, text="", font=self.f(12, "bold"), text_color=TEXT)
        self.speed_val.pack(side="right")
        self.speed = ctk.CTkSlider(b, from_=0.3, to=3.0, number_of_steps=27, command=self.on_speed,
                                   button_color=ACCENT, button_hover_color=ACCENT_HOVER, progress_color=ACCENT)
        self.speed.set(self.cfg["speed"])
        self.speed.pack(fill="x", pady=(2, 4))
        self.speed_val.configure(text=f"{self.cfg['speed']:.1f}x")

        self.switch(b, "클립보드 공유", "clipboard", sub="태블릿으로 넘어갈 때 PC 복사 내용 전달, 태블릿 복사는 PC로")
        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="한/영 키", font=self.f(13), text_color=TEXT).pack(side="left")
        hl = [l for _, l in HANGUL]
        self.hangul_menu = ctk.CTkOptionMenu(row, values=hl, font=self.f(12), dropdown_font=self.f(12), width=210,
                                             fg_color=CARD_2, button_color=CARD_2, button_hover_color=ACCENT,
                                             text_color=TEXT, command=self.on_hangul, height=30)
        self.hangul_menu.set(dict(HANGUL)[self.cfg["hangul"]])
        self.hangul_menu.pack(side="right")
        ctk.CTkLabel(b, text="Ctrl + Alt + M   PC ↔ 태블릿 즉시 전환", font=self.f(11), text_color=MUTED,
                     anchor="w").pack(fill="x", pady=(6, 0))

        # ---- audio ----
        c, b = self.card(right, "소리")
        c.pack(fill="x")
        self.switch(b, "태블릿 소리를 PC에서 재생", "audio")
        self.switch(b, "태블릿 스피커에서도 재생", "audio_dup")
        row = self.label_row(b, "지연 버퍼")
        self.buf_val = ctk.CTkLabel(row, text=f"{self.cfg['audio_buffer']} ms", font=self.f(12, "bold"),
                                    text_color=TEXT)
        self.buf_val.pack(side="right")
        self.buf = ctk.CTkSlider(b, from_=20, to=300, number_of_steps=28, button_color=ACCENT,
                                 button_hover_color=ACCENT_HOVER, progress_color=ACCENT,
                                 command=lambda v: self.buf_val.configure(text=f"{int(v)} ms"))
        self.buf.set(self.cfg["audio_buffer"])
        self.buf.bind("<ButtonRelease-1>", self.on_buffer)
        self.buf.pack(fill="x", pady=(2, 0))

        # ---- connection ----
        c, b = self.card(right, "연결")
        c.pack(fill="x", pady=(14, 0))
        self.tr_seg = ctk.CTkSegmentedButton(b, values=[l for _, l in TRANSPORT_BUTTONS], font=self.f(12),
                                             height=32, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                             command=self.on_transport)
        self.tr_seg.set(dict(TRANSPORT_BUTTONS)[self.cfg["transport"]])
        self.tr_seg.pack(fill="x", pady=(0, 4))
        self.tr_hint = ctk.CTkLabel(b, text="", font=self.f(11), text_color=MUTED, anchor="w")
        self.tr_hint.pack(fill="x")
        self.chips = ctk.CTkFrame(b, fg_color="transparent")
        self.chips.pack(fill="x", pady=(4, 2))
        self.switch(b, "무선 디버깅 기기 자동 연결", "auto_wifi")
        btns = ctk.CTkFrame(b, fg_color="transparent")
        btns.pack(fill="x", pady=(6, 0))
        for text, cmd in (("IP로 연결", self.on_connect_ip), ("무선 페어링", self.on_pair)):
            ctk.CTkButton(btns, text=text, command=cmd, font=self.f(12), height=32, fg_color=CARD_2,
                          hover_color=ACCENT, text_color=TEXT).pack(side="left", expand=True, fill="x",
                                                                    padx=(0, 6) if text == "IP로 연결" else 0)
        self.on_transport(None)

        # ---- options ----
        c, b = self.card(right, "옵션")
        c.pack(fill="x", pady=(14, 0))
        self.switch(b, "Windows 시작 시 자동 실행", "autostart", extra=self.on_autostart)
        self.switch(b, "창을 닫으면 트레이로", "close_to_tray")

        # ---- activity ----
        c, b = self.card(left, "활동")
        c.pack(fill="both", expand=True, pady=(14, 0))
        self.logbox = ctk.CTkTextbox(b, height=60, font=ctk.CTkFont(family="Consolas", size=11), fg_color=CARD_2,
                                     text_color=MUTED, corner_radius=8, state="disabled", wrap="none")
        self.logbox.pack(fill="both", expand=True)

        foot = ctk.CTkFrame(right, fg_color="transparent")
        foot.pack(fill="x", side="bottom", pady=(14, 0))
        ctk.CTkButton(foot, text="종료", command=self.quit, font=self.f(12), height=34, width=90,
                      fg_color="transparent", border_width=1, border_color=MUTED, text_color=TEXT,
                      hover_color=CARD_2).pack(side="right")
        ctk.CTkButton(foot, text="트레이로 숨기기", command=self.root.withdraw, font=self.f(12), height=34,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="right", padx=8)
        self.show_mc_state(False)

    # ---------- layout diagram ----------
    def draw_layout(self):
        cv = self.canvas
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50:
            return
        bg = _mode_color(CARD_2)
        cv.configure(bg=bg)
        cv.delete("all")
        mons = winio.monitors()
        self.mc._mons = mons
        target = self.mc._monitor()
        side = self.cfg["side"]
        info = self.mc.info
        th = target.height * 0.75
        tw = th * info.width / max(info.height, 1)
        if side in ("top", "bottom"):
            tw = target.width * 0.55
            th = tw * info.height / max(info.width, 1)
        gap = 0.04 * max(target.width, target.height)
        cx, cy = (target.left + target.right) / 2, (target.top + target.bottom) / 2
        tab = {
            "right": (target.right + gap, cy - th / 2, target.right + gap + tw, cy + th / 2),
            "left": (target.left - gap - tw, cy - th / 2, target.left - gap, cy + th / 2),
            "top": (cx - tw / 2, target.top - gap - th, cx + tw / 2, target.top - gap),
            "bottom": (cx - tw / 2, target.bottom + gap, cx + tw / 2, target.bottom + gap + th),
        }[side]
        xs = [m.left for m in mons] + [m.right for m in mons] + [tab[0], tab[2]]
        ys = [m.top for m in mons] + [m.bottom for m in mons] + [tab[1], tab[3]]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        pad = 18
        scale = min((w - 2 * pad) / (maxx - minx), (h - 2 * pad) / (maxy - miny))
        ox = (w - (maxx - minx) * scale) / 2 - minx * scale
        oy = (h - (maxy - miny) * scale) / 2 - miny * scale

        def tr(x0, y0, x1, y1):
            return ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale

        dark = ctk.get_appearance_mode() == "Dark"
        mon_fill = "#2E323A" if dark else "#FFFFFF"
        mon_line = "#4B5563" if dark else "#CBD5E1"
        txt = "#E5E7EB" if dark else "#334155"
        active = self.mc.active
        self._layout_target = tr(target.left, target.top, target.right, target.bottom)
        for i, m in enumerate(mons):
            x0, y0, x1, y1 = tr(m.left + 6, m.top + 6, m.right - 6, m.bottom - 6)
            is_t = m is target
            self._round_rect(x0, y0, x1, y1, 8, fill=mon_fill, outline=ACCENT if is_t and not active else mon_line,
                             width=2 if is_t else 1)
            cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=f"{i + 1}", fill=txt, font=("Segoe UI", 16, "bold"))
            cv.create_text((x0 + x1) / 2, (y0 + y1) / 2 + 20, text=f"{m.width}×{m.height}", fill=MUTED[1 if dark else 0],
                           font=("Segoe UI", 8))
        x0, y0, x1, y1 = tr(*tab)
        enabled = self.cfg["mc"]
        fill = ACCENT if active else ("#1E293B" if dark else "#E0E7FF") if enabled else mon_fill
        self._round_rect(x0, y0, x1, y1, 10, fill=fill, outline=ACCENT if enabled else mon_line, width=2,
                         dash=() if enabled else (4, 3))
        cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="Tab", fill="white" if active else txt,
                       font=("Segoe UI", 13, "bold"))
        # crossing arrow
        ex = {"right": ((x0 - 3, (y0 + y1) / 2), -1, 0), "left": ((x1 + 3, (y0 + y1) / 2), 1, 0),
              "top": (((x0 + x1) / 2, y1 + 3), 0, 1), "bottom": (((x0 + x1) / 2, y0 - 3), 0, -1)}[side]
        (ax, ay), dx, dy = ex
        if enabled:
            cv.create_line(ax + dx * 14, ay + dy * 14, ax, ay, fill=ACCENT, width=2, arrow="last", arrowshape=(7, 8, 3))

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
               x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def on_canvas_click(self, e):
        t = getattr(self, "_layout_target", None)
        if not t:
            return
        cx, cy = (t[0] + t[2]) / 2, (t[1] + t[3]) / 2
        dx, dy = (e.x - cx) / max(t[2] - t[0], 1), (e.y - cy) / max(t[3] - t[1], 1)
        side = ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("bottom" if dy > 0 else "top")
        self.cfg["side"] = side
        self.side_seg.set(dict(SIDE_BUTTONS)[side])
        self.changed()

    # ---------- handlers ----------
    def on_side(self, label):
        self.cfg["side"] = next(k for k, l in SIDE_BUTTONS if l == label)
        self.changed()

    def refresh_monitor_list(self):
        mons = winio.monitors()
        self._mon_labels = ["자동 (태블릿 방향의 가장 바깥 모니터)"] + [m.label(i) for i, m in enumerate(mons)]
        self.mon_menu.configure(values=self._mon_labels)
        idx = int(self.cfg["monitor"]) + 1
        self.mon_menu.set(self._mon_labels[idx if 0 <= idx < len(self._mon_labels) else 0])

    def on_monitor(self, label):
        self.cfg["monitor"] = self._mon_labels.index(label) - 1
        self.changed()

    def on_speed(self, v):
        v = round(float(v), 1)
        self.speed_val.configure(text=f"{v:.1f}x")
        if v != self.cfg["speed"]:
            self.cfg["speed"] = v
            save_config(self.cfg)
            self.apply_mc_config()

    def on_buffer(self, _=None):
        v = int(self.buf.get())
        if v != self.cfg["audio_buffer"]:
            self.cfg["audio_buffer"] = v
            self.changed()

    def on_hangul(self, label):
        self.cfg["hangul"] = next(k for k, l in HANGUL if l == label)
        self.changed()

    def on_transport(self, label):
        if label:
            self.cfg["transport"] = next(k for k, l in TRANSPORT_BUTTONS if l == label)
            self.changed()
        self.tr_hint.configure(text={"auto": "USB 우선, 케이블이 빠지면 Wi-Fi로 자동 전환",
                                     "usb": "USB 케이블로만 연결", "wifi": "무선 디버깅으로만 연결"}[self.cfg["transport"]])

    def on_autostart(self):
        try:
            set_autostart(self.cfg["autostart"])
        except OSError as e:
            self.log(f"자동 실행 설정 실패: {e}")

    def ask(self, title, text):
        d = ctk.CTkInputDialog(title=title, text=text, font=self.f(12), button_fg_color=ACCENT,
                               button_hover_color=ACCENT_HOVER)
        v = d.get_input()
        return v.strip() if v else None

    def on_connect_ip(self):
        ep = self.ask("IP로 연결", "태블릿 무선 디버깅 화면의 'IP 주소 및 포트'\n예) 192.168.0.10:37000")
        if ep:
            def work():
                ok, out = devices.connect(ep)
                self.manager.log(("연결 성공: " if ok else "연결 실패: ") + out)
                self.manager.wake.set()
            threading.Thread(target=work, daemon=True).start()

    def on_pair(self):
        ep = self.ask("무선 페어링", "태블릿: 설정 › 개발자 옵션 › 무선 디버깅 ›\n'페어링 코드로 기기 페어링'에 표시된 IP 주소 및 포트")
        if not ep:
            return
        code = self.ask("무선 페어링", "6자리 Wi-Fi 페어링 코드")
        if not code:
            return

        def work():
            ok, out = devices.pair(ep, code)
            self.manager.log(("페어링 성공: " if ok else "페어링 실패: ") + out)
            self.manager.last_mdns = 0
            self.manager.wake.set()
        threading.Thread(target=work, daemon=True).start()

    # ---------- state display ----------
    def show_devices(self, ids, ts):
        for w in self.chips.winfo_children():
            w.destroy()
        mine = [t for t in ts if t.device_id == self.cfg["device_id"]]
        cur = self.manager.session.serial if self.manager.session else None
        for t in mine:
            on = t.state == "device"
            using = t.serial == cur
            ctk.CTkLabel(self.chips, text=("●  " if using else "") + t.kind + ("" if on else f" ({t.state})"),
                         font=self.f(11, "bold"), corner_radius=999, height=24, padx=10,
                         fg_color=ACCENT if using else CARD_2,
                         text_color="white" if using else (TEXT if on else MUTED)).pack(side="left", padx=(0, 6))
        if not mine:
            ctk.CTkLabel(self.chips, text="사용 가능한 연결 없음", font=self.f(11), text_color=MUTED).pack(side="left")
        self._ids = ids

    def show_status(self, session):
        self.session = session
        if not session:
            self.pill.configure(text="●  연결 안 됨", text_color=GRAY)
            self.device_lbl.configure(text="USB를 연결하거나 태블릿에서 무선 디버깅을 켜세요")
        else:
            t = session.transport
            self.pill.configure(text=f"●  {t.kind} 연결됨", text_color=GREEN)
            parts = []
            if session.audio and session.audio.poll() is None:
                parts.append("소리")
            if session.ctrl and session.ctrl.alive:
                parts.append("멀티 컨트롤")
            self.device_lbl.configure(text=f"{t.model}  ·  {t.device_id}" + (f"  ·  {' + '.join(parts)}" if parts else ""))
        if not self.mc.active:
            self.show_mc_state(False)
        self.update_tray()

    def show_mc_state(self, active):
        self.draw_layout()
        if not self.cfg["mc"]:
            self.mc_state_lbl.configure(text="꺼짐", text_color=MUTED)
        elif not (self.mc.ctrl and self.mc.ctrl.alive):
            self.mc_state_lbl.configure(text="태블릿 연결을 기다리는 중…", text_color=MUTED)
        elif active:
            self.mc_state_lbl.configure(text="▶  지금 태블릿을 조작하고 있어요 — 반대로 밀거나 Ctrl+Alt+M으로 복귀",
                                        text_color=ACCENT)
        else:
            self.mc_state_lbl.configure(
                text=f"마우스를 파란 테두리 모니터의 {SIDE_WORD[self.cfg['side']]} 끝으로 밀면 태블릿으로 넘어가요",
                text_color=MUTED)

    # ---------- tray ----------
    def _set_icon(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            path = os.path.join(CONFIG_DIR, "icon.ico")
            make_icon_image(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)])
            self.root.iconbitmap(path)
            self.root.after(300, lambda: self.root.iconbitmap(path))  # CTk resets the icon after startup
        except Exception:
            pass

    def start_tray(self):
        try:
            import pystray
        except ImportError:
            return
        item = pystray.MenuItem

        def toggle(key):
            return lambda icon, it: self.post(lambda: self._toggle(key))

        menu = pystray.Menu(
            item("열기", lambda i, it: self.post(self.show_window), default=True),
            item("소리를 PC로", toggle("audio"), checked=lambda it: self.cfg["audio"]),
            item("멀티 컨트롤", toggle("mc"), checked=lambda it: self.cfg["mc"]),
            pystray.Menu.SEPARATOR,
            item("종료", lambda i, it: self.post(self.quit)),
        )
        self.tray = pystray.Icon(APP_NAME, make_icon_image(64), "TabLink", menu)
        self.tray.run_detached()

    def _toggle(self, key):
        self.cfg[key] = not self.cfg[key]
        getattr(self, f"var_{key}").set(self.cfg[key])
        self.changed()

    def update_tray(self):
        if self.tray:
            s = self.session
            self.tray.title = f"TabLink — {s.transport.model} ({s.transport.kind})" if s else "TabLink — 연결 안 됨"
            self.tray.update_menu()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close(self):
        if self.cfg["close_to_tray"] and self.tray:
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        self.mc.stop()
        self.manager.stopping = True
        self.manager.wake.set()
        self.manager.join(5)
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
