# TabLink v0.2 rewrite — implementation contract

The current Python app (`*.py` in the repo root) is the **reference implementation**. Read it for behaviour
you must preserve (scrcpy control protocol, UHID descriptors, keyboard scancode→HID tables, adb discovery,
config keys). Do **not** modify or delete the Python files; the new app lives beside them.

New architecture:

```
Electron main (Node)            C# helper (TabLinkHelper.exe, .NET 10, NativeAOT)
  electron/main.js   ──stdin JSON lines──▶  Program.cs (command loop)
  electron/manager.js ◀─stdout JSON lines──  hooks + multi-control state machine,
  electron/devices.js                         scrcpy control socket, clipboard, audio process
renderer/ (HTML/CSS/JS UI)  ◀─IPC (preload)─▶ main
```

Why: low-level mouse/keyboard hooks in Python made the whole PC's mouse feel sluggish (GIL), CustomTkinter
was slow and re-laid-out the window on every state change. All latency-critical work now runs in native code;
the UI is a fixed-size web page.

---------------------------------------------------------------------------------------------------------
## Part A — C# helper  (`helper/`)

Files: `helper/TabLinkHelper.csproj`, `helper/app.manifest`, `helper/*.cs`. Target `net10.0-windows`,
`<OutputType>WinExe</OutputType>` (no console window; stdin/stdout still work through pipes),
`<PublishAot>true</PublishAot>`, `<InvariantGlobalization>true</InvariantGlobalization>`, `<Nullable>enable</Nullable>`,
`<AllowUnsafeBlocks>true</AllowUnsafeBlocks>`. Manifest: `PerMonitorV2` dpiAwareness (also call
`SetProcessDpiAwarenessContext(-4)` at startup). Use `[LibraryImport]`/`[DllImport]` P/Invoke only — **no WinForms/WPF**,
no reflection-based JSON: use `System.Text.Json` with a source-generated `JsonSerializerContext`, or parse with
`JsonDocument` and write with `Utf8JsonWriter` (must be AOT/trim-safe, zero warnings). Must build with
`dotnet publish helper -c Release -r win-x64` (AOT). Must also run with `dotnet run --project helper`.

### Threads
1. **Hook thread** — creates the blocker window, installs `WH_MOUSE_LL` + `WH_KEYBOARD_LL`, runs a `GetMessage` loop.
   The multi-control state machine runs **synchronously inside the hook callbacks** and must never block:
   no I/O, no locks held by slow code, no allocations in the mouse-move hot path where avoidable.
   Commands from other threads that must touch hook-thread state are marshalled with `PostThreadMessage(WM_APP+n)`
   or done under the single state lock (`lock (mc)`), whose holders are all fast.
2. **Sender thread** — owns writes to the control socket. Hook code enqueues packets (lock-free queue / Channel).
   The sender drains everything pending and **coalesces** consecutive mouse reports that have the same button
   byte and zero wheel/hwheel (sum dx/dy, clamp to ±32767) before writing — keeps Wi-Fi from lagging.
   Keyboard and button-change packets are never merged or reordered.
3. **Device reader thread** — reads device messages from the control socket (clipboard, ack, uhid output) exactly like
   `ScrcpyControl._reader` in `scrcpy_ctrl.py`. On EOF/error → control state `dead`.
4. **stdin reader thread** — reads JSON-line commands. EOF on stdin ⇒ clean shutdown (parent died).
5. **Info poller** — while attached, every 3 s runs `adb -s <serial> shell dumpsys input` and parses it exactly like
   `TabletInfo.query` (logicalFrame of displayId=0 → width/height; "Multi Control Mouse" XScale/YScale × first
   acceleration-curve gain → gainX/gainY; `linear` = single curve segment). Emits `info` only when values change.
6. **Audio watcher** — see `audio` command.

All child processes (adb shell for the server, scrcpy audio) are assigned to a Job object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, started with `CreateNoWindow`, so they die with the helper.

### stdin commands (one JSON object per line, field `cmd`)
| cmd | fields | effect |
|---|---|---|
| `config` | `enabled` bool, `side` "right\|left\|top\|bottom", `monitor` int (-1 = auto), `speed` float, `hangul` "shift_space\|lang1", `clipboard` bool | update multi-control settings; re-emit `monitors` (target may change). If `enabled` becomes false while active → leave. |
| `attach` | `serial`, `adb` (path to adb.exe), `server` (path to scrcpy-server), `version` (scrcpy version string) | detach any current control, then start the control channel exactly like `ScrcpyControl.start` (push server to `/data/local/tmp/scrcpy-server-tablink.jar`, `adb forward tcp:0 localabstract:scrcpy_<scid>`, launch `app_process` with the same arguments, wait for the dummy byte, read 64-byte device name, TCP_NODELAY, create UHID mouse id 2 "Multi Control Mouse" + keyboard id 1 "Multi Control Keyboard" with the same descriptors). Emit `ctrl` starting → alive / error. After alive, wait 300 ms, query info once, start the poller. Do the blocking work on a worker thread, not on the stdin thread. |
| `detach` | | leave tablet mode if active, stop control (same as `ScrcpyControl.stop`: release keys/buttons, UHID destroy, close socket, kill server process, remove forward). Emit `ctrl` state `off`. |
| `audio` | `serial` (null/absent = stop), `scrcpy` (path), `source` "playback\|output", `dup` bool, `buffer` int ms | stop any running audio process, then if serial given start `scrcpy -s <serial> --no-video --no-control --no-window --no-power-on --audio-buffer=<buffer> --audio-source=<source>` plus `--audio-dup` **only when source == playback and dup**. Pipe stdout+stderr; forward lines containing `ERROR` or `WARN` as `log` events (prefix `scrcpy: `). Emit `audio` state `running`; when it exits on its own emit `audio` state `stopped` with `code`. A stop requested by a command emits state `off`. |
| `toggle` | | same as the Ctrl+Alt+M hotkey (enter at cursor/centre or leave). |
| `monitors` | | re-emit `monitors`. |
| `quit` | | detach, stop audio, unhook, exit 0. |

### stdout events (one JSON object per line, field `ev`; flush after every line; stdout is UTF-8 without BOM)
- `{"ev":"ready"}` once hooks are installed.
- `{"ev":"monitors","list":[{"left":0,"top":0,"right":1920,"bottom":1080,"primary":true,"name":"\\\\.\\DISPLAY1"}],"target":0}` —
  physical pixels, ordered like `winio.monitors()` (primary first, then by left, top). `target` = index of the
  monitor the tablet is attached to (explicit index or the auto rule from `MultiControl._monitor`).
  Re-emitted on `WM_DISPLAYCHANGE` (handle it in the blocker window's wndproc) and on `config`.
- `{"ev":"ctrl","state":"starting|alive|dead|error|off","serial":"...","message":"..."}`
- `{"ev":"info","width":2960,"height":1848,"gainX":1.786,"gainY":1.786,"linear":true}`
- `{"ev":"active","value":true}` whenever tablet mode is entered/left.
- `{"ev":"audio","state":"running|stopped|off|error","code":0,"message":"..."}`
- `{"ev":"log","msg":"..."}` — human-readable Korean messages are fine.

Never write anything else to stdout (no Console.WriteLine debugging). Exceptions inside hook callbacks are caught,
logged as `log`, and the event passed through.

### Multi-control state machine
Port `multicontrol.py` + `winio.py` faithfully (edge detection with `edge_push = 2`, `_covered` shared-edge rule,
PC buttons held ⇒ no crossing, park at monitor centre with the 48×48 alpha-1 topmost NOACTIVATE TOOLWINDOW blocker
window that hides the cursor via `WM_SETCURSOR`, enter/leave positions, wheel accumulation, X buttons,
keyboard routing incl. `pc_vks`/`tablet_vks`/`swallow_up`, Ctrl+Alt+M, Hangul shift_space mode, 6-key rollover,
clipboard push on enter when the Windows clipboard sequence number changed, device clipboard → Windows clipboard
when `clipboard` is on). Also leave tablet mode if control becomes not alive.

**Required fixes vs. the Python version:**

1. *Cursor stuck before the real tablet edge.* Python computes HID counts from the **clamped** target, so once the
   tracked position reaches the edge it stops sending motion; if the gain estimate is slightly high the real Android
   cursor is still short of the edge and can never get there. New `Move(dx,dy)`:
   ```
   nx = tx + dx*speed; ny = ty + dy*speed
   if crossing back towards the PC (side==right && nx<0, left && nx>W-1, top && ny>H-1, bottom && ny<0) → Leave(nx,ny); return
   cx = (nx - tx)/gainX + rx;  cy = (ny - ty)/gainY + ry      // UNclamped: pushing into an edge keeps sending counts
   ix = round(cx); iy = round(cy); rx = cx-ix; ry = cy-iy
   send mouse(ix, iy, buttons) if ix||iy
   tx = tx + ix*gainX; ty = ty + iy*gainY
   if tx < 0 or tx > W-1 → clamp tx, rx = 0      // Android clamps the same way, so both are now in sync
   if ty < 0 or ty > H-1 → clamp ty, ry = 0
   ```
2. *Rotation / resolution change while active.* When the poller reports a different width/height while in tablet
   mode, resync: keep the fractional position (fx = tx/(oldW-1), fy = ty/(oldH-1)), slam the pointer to the top-left
   (`mouse(-32767,-32767)` twice) and move to `(fx*(W-1), fy*(H-1))` in counts, set tx/ty from the counts sent
   (same as enter). Gain changes are applied immediately.
3. On enter, slam with `mouse(-32767,-32767)` **twice** (one report may not reach the corner on a 2960-px screen at
   low gain), then move to the target.

---------------------------------------------------------------------------------------------------------
## Part B — Electron app

Files: `package.json`, `electron/main.js`, `electron/preload.js`, `electron/manager.js`, `electron/devices.js`,
`electron/helper.js`, `electron/config.js`, `renderer/index.html`, `renderer/styles.css`, `renderer/app.js`,
`scripts/build.mjs`, `assets/icon.ico` + `assets/icon.png` (already provided — do not regenerate).
CommonJS in main, plain ES modules / vanilla JS in the renderer, **no UI framework, no bundler, no TypeScript**.
devDependencies only: `electron` (exact version `45.2.1`), `@electron/packager` (`20.3.0`). No runtime dependencies.
`contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, a strict CSP meta tag in index.html.

### package.json scripts
- `"helper": "dotnet publish helper -c Release -r win-x64 -o build/helper"`
- `"start": "electron ."` (dev: expects `build/helper/TabLinkHelper.exe`)
- `"build": "node scripts/build.mjs"` → runs the helper publish, `@electron/packager` (`--platform=win32 --arch=x64`,
  name `TabLink`, icon `assets/icon.ico`, `asar: true`, ignore everything except `electron/`, `renderer/`, `assets/`,
  `package.json`), copies `build/helper/TabLinkHelper.exe` to `<out>/resources/helper/` and the scrcpy folder
  (resolved like below) to `<out>/resources/scrcpy/`, copies README.md + LICENSE, then zips the folder to
  `dist/TabLink-win64.zip` using `tar.exe -a -c -f` (built into Windows).

### Paths (`electron/config.js`)
- Config dir: `path.join(process.env.APPDATA, 'TabLink')` (same as Python — reuse `config.json`, `log.txt`).
  Defaults = Python `DEFAULTS` plus `"audio_source": "playback"`. Unknown keys preserved. Write atomically (tmp + rename).
- Helper exe: packaged → `process.resourcesPath/helper/TabLinkHelper.exe`; dev → `<repo>/build/helper/TabLinkHelper.exe`.
- scrcpy dir: env `SCRCPY_DIR`, packaged `process.resourcesPath/scrcpy`, then `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Genymobile.scrcpy*\*` newest
  first — first that contains both `scrcpy-server` and `adb.exe` (same as `_find_scrcpy_dir`). scrcpy version from
  `scrcpy.exe --version` (`/scrcpy (\S+)/`), fallback `5.0.1`.

### `electron/helper.js`
Spawns the helper (`windowsHide: true`, stdio pipes), line-splits stdout, emits parsed events (EventEmitter),
`send(obj)` writes a JSON line. If the helper exits unexpectedly: log it, restart after 1 s, re-send last `config`,
and let the manager re-attach (emit `restart`).

### `electron/devices.js` (port of `devices.py`, all **async** via `execFile`, never `execSync`)
`listTransports()`, `mdnsEndpoints()`, `connect(ep)`, `pair(ep, code)`. Same parsing. Transports in states other than
`device` (`unauthorized`, `offline`, `authorizing`, `connecting`) must still be returned.

### `electron/manager.js` (port of `core.Manager`, async loop: tick, then wait 1.5 s or until woken)
Same rules as Python for transport preference (USB first; `transport` = auto/usb/wifi), Wi-Fi auto-discovery
(mDNS every 15 s, `known_endpoints`), switching Wi-Fi→USB only when not in tablet mode, reconnect on loss.
Instead of Python's per-session `ScrcpyControl` and audio `Popen`, it sends helper commands:
- session start ⇒ `attach` (if `mc`) and `audio` (if `audio`); session end ⇒ `detach` + `audio` with no serial.
- `mc` toggled ⇒ attach/detach. `audio`, `audio_source`, `audio_dup`, `audio_buffer` changed ⇒ re-send `audio`.
- `ctrl` event `dead`/`error` while the session is up ⇒ re-attach after 2 s (back off to 10 s after 3 failures, log once).
- `audio` event `stopped` while audio wanted ⇒ restart after 2 s (same back-off).
- Any MC setting changed ⇒ send `config`.

**Multiple devices (new UX).** Group transports into devices by `device_id` (`ro.serialno`):
`{id, model, transports:[{serial, kind:'USB'|'Wi-Fi', state}]}`; unauthorized/offline transports whose id can't be read
appear as their own device with `model` = '' and state shown. Selection rules:
- `cfg.device_id` set and that device present → use it.
- No remembered device, exactly one usable device → pick it and remember it.
- No remembered device and several usable devices → do **not** guess; status `choose` until the user picks.
- Remembered device absent but others present → stay disconnected, status `missing` (UI offers the others).
- `selectDevice(id)` from UI/tray → remember, end current session, wake the loop.
- `forgetDevice()` → clear `device_id`.

State pushed to the renderer (`state` IPC, throttled to ≤ 20/s, also sent on request):
```
{ devices:[{id, model, transports:[...], usable:bool}], selectedId, selection:'ok'|'choose'|'missing'|'none',
  session: null | {serial, kind, model, deviceId},
  ctrl: 'off'|'starting'|'alive'|'dead'|'error', audio: 'off'|'running'|'stopped'|'error',
  active: bool, monitors:[...], target: int, info:{width,height,gainX,gainY,linear},
  config: {...} }
```
Logs go through a separate `log` IPC (`{time:'HH:MM:SS', msg}`) and are appended to `log.txt` (`YYYY-MM-DD HH:MM:SS  msg`).
Keep the last 200 in memory so a newly opened window gets history (`getLogs`).

### `electron/main.js`
- `app.setName('TabLink')`, `app.setAppUserModelId('TabLink')`, `requestSingleInstanceLock()` (second instance ⇒ show window).
- BrowserWindow **fixed size** 960×660, `resizable:false`, `maximizable:false`, `show:false` (show on
  `ready-to-show` unless started with `--tray`), `backgroundColor` from `nativeTheme.shouldUseDarkColors`
  (`#111214` / `#F2F4F7`), `titleBarStyle:'hidden'` + `titleBarOverlay` `{color, symbolColor, height:44}` updated on
  `nativeTheme` `updated`. `autoHideMenuBar`, no menu.
- Close button ⇒ hide to tray if `close_to_tray`, else quit. Quit ⇒ manager stop → helper `quit` (wait ≤ 2 s) → exit.
- Tray (`assets/icon.ico`): tooltip `TabLink — <model> (<kind>)` or `TabLink — 연결 안 됨`; click ⇒ show window;
  menu: 열기 / 기기 ▸ (radio item per device, model + transports) / ☑ 소리를 PC로 / ☑ 멀티 컨트롤 / 종료.
  Rebuild the menu only when devices/flags change.
- Autostart: `app.setLoginItemSettings({openAtLogin, name:'TabLink', path:process.execPath, args:['--tray']})`
  (packaged only; in dev just log that it's unsupported). Same `name` as the Python Run key so it replaces it.
- IPC (`ipcMain.handle`): `getState`, `getLogs`, `setConfig(patch)` (validate keys/types, save, apply, return config),
  `selectDevice(id)`, `forgetDevice()`, `connectIp(ep)`, `pair(ep, code)`, `hide()`, `quit()`.
  Push channels: `state`, `log`.
- preload exposes exactly `window.tablink = {getState, getLogs, setConfig, selectDevice, forgetDevice, connectIp, pair, hide, quit, onState(cb), onLog(cb)}`.

### Renderer UI  (`renderer/`)
Modern, calm, native-feeling Windows 11 look. Font stack `"Segoe UI Variable Text", "Segoe UI", "Malgun Gothic", sans-serif`.
Colours as CSS custom properties with light + dark (`prefers-color-scheme`) — reuse the Python palette
(ACCENT `#3B82F6`, BG `#F2F4F7`/`#111214`, CARD `#FFFFFF`/`#1B1D21`, CARD_2 `#EEF1F5`/`#24272D`, TEXT, MUTED, GREEN `#22C55E`, AMBER `#F59E0B`).
All Korean text as in the Python UI.

**Hard rule — the layout must never move.** Every region has a fixed size (CSS grid with fixed rows/columns, fixed
heights); status lines are single-line with `white-space:nowrap; overflow:hidden; text-overflow:ellipsis`; state changes
only change colours/text/opacity, never `display`, never insert/remove elements outside scrollable lists; disabled
controls stay in place (greyed). The body never scrolls (`overflow:hidden`); only the log and device list scroll internally.
No layout or SVG redraw is triggered by `active` changes except recolouring the tablet shape.

Layout (960×660, 44 px custom title bar with `-webkit-app-region: drag`, buttons inside it `no-drag`, leave ~140 px on the
right for the overlay buttons):
- Title bar: icon, "TabLink", status pill (`● USB 연결됨` green / `● Wi-Fi 연결됨` / `● 연결 안 됨` grey / `● 기기 선택 필요` amber).
- Left column (≈ 560 px):
  - **멀티 컨트롤** card: header switch; SVG diagram (monitors from `monitors`, physical coords scaled to fit, target
    monitor outlined in accent, tablet rectangle with aspect from `info`, placed per `side` exactly like
    `App.draw_layout`; clicking the diagram picks the side like `on_canvas_click`; tablet fill = accent while active);
    one fixed-height status line (texts from `show_mc_state`); segmented control for side; monitor `<select>`
    (자동 + monitor labels like `Monitor.label`); speed slider 0.3–3.0 step 0.1 with value label (send on `input`, debounce 100 ms);
    클립보드 공유 switch; 한/영 키 select; hint `Ctrl + Alt + M   PC ↔ 태블릿 즉시 전환`.
  - **활동** card filling the rest: monospace log, newest at bottom, auto-scroll only if already at bottom.
- Right column (≈ 360 px):
  - **기기** card (fixed height, internal scroll): one row per device — radio-style selectable row with model (or "승인 대기 중인 기기"),
    short id, and transport chips (`USB`, `Wi-Fi`, greyed with state text like `승인 필요`/`오프라인`); the selected row is
    highlighted and shows `사용 중` when the session is up. When `selection` is `choose`: a one-line amber hint
    `여러 기기가 연결됨 — 사용할 기기를 선택하세요`; `missing`: `저장된 기기가 연결되지 않음 — 다른 기기를 선택할 수 있어요`;
    an unauthorized transport: `태블릿에서 USB 디버깅 허용을 눌러주세요`. Empty: `USB를 연결하거나 태블릿에서 무선 디버깅을 켜세요`.
    The hint line always exists (empty text when nothing to say). Below: transport segmented (자동/USB/Wi-Fi) with its hint text,
    "무선 디버깅 기기 자동 연결" switch, buttons `IP로 연결` / `무선 페어링` (open an in-page modal dialog with inputs —
    pairing asks for IP:port and the 6-digit code in one dialog; show the result text in the dialog).
  - **소리** card: 태블릿 소리를 PC에서 재생 (switch); 캡처 방식 select:
    `playback` = "앱 소리만 캡처 (권장 · 마이크/음성인식 정상)", `output` = "전체 출력 캡처 (마이크·음성인식이 안 될 수 있음)";
    태블릿 스피커에서도 재생 (switch, disabled with note when source = output); 지연 버퍼 slider 20–300 ms step 10 (send on `change`).
  - **옵션** card: Windows 시작 시 자동 실행, 창을 닫으면 트레이로.
  - Footer: `트레이로 숨기기` (accent) and `종료` (outline).
Switches, segmented controls, sliders and selects are custom-styled native inputs (keyboard accessible, visible focus ring).
Transitions ≤ 150 ms on colour only.
