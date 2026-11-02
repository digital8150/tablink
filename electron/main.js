const { app, BrowserWindow, Tray, Menu, ipcMain, nativeTheme } = require('electron'),
  path = require('path'),
  fs = require('fs');
const config = require('./config'),
  Helper = require('./helper'),
  Devices = require('./devices'),
  Manager = require('./manager');
const isMac = process.platform === 'darwin';
app.setName('TabLink');
if (process.platform === 'win32') app.setAppUserModelId('TabLink');
const locked = app.requestSingleInstanceLock();
if (!locked) {
  app.quit();
  process.exit(0);
}
let win,
  tray,
  manager,
  helper,
  quitting = false,
  menuKey = '';
const smoke = process.env.TABLINK_SMOKE === '1';
function show() {
  if (win) {
    win.show();
    win.focus();
  }
}
app.on('second-instance', show);
if (isMac) app.on('activate', show);
function overlay() {
  return {
    color: nativeTheme.shouldUseDarkColors ? '#111214' : '#F2F4F7',
    symbolColor: nativeTheme.shouldUseDarkColors ? '#E5E7EB' : '#20242A',
    height: 44,
  };
}
function validate(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) throw Error('잘못된 설정');
  const checks = {
    device_id: (v) => typeof v === 'string',
    transport: (v) => ['auto', 'usb', 'wifi'].includes(v),
    auto_wifi: (v) => typeof v === 'boolean',
    audio: (v) => typeof v === 'boolean',
    audio_dup: (v) => typeof v === 'boolean',
    audio_buffer: (v) => Number.isInteger(v) && v >= 20 && v <= 300 && v % 10 === 0,
    mc: (v) => typeof v === 'boolean',
    side: (v) => ['right', 'left', 'top', 'bottom'].includes(v),
    monitor: (v) => Number.isInteger(v) && v >= -1,
    speed: (v) => typeof v === 'number' && v >= 0.3 && v <= 3,
    clipboard: (v) => typeof v === 'boolean',
    hangul: (v) => ['shift_space', 'lang1'].includes(v),
    autostart: (v) => typeof v === 'boolean',
    close_to_tray: (v) => typeof v === 'boolean',
    audio_source: (v) => ['playback', 'output'].includes(v),
  };
  for (const [k, v] of Object.entries(p)) if (!checks[k] || !checks[k](v)) throw Error('잘못된 설정: ' + k);
}
function autostart() {
  if (app.isPackaged)
    app.setLoginItemSettings({
      openAtLogin: manager.cfg.autostart,
      name: 'TabLink',
      path: process.execPath,
      args: ['--tray'],
    });
  else manager.log('개발 모드에서는 자동 실행을 설정할 수 없습니다');
}
function updateTray(s) {
  if (!tray) return;
  tray.setToolTip(s.session ? `TabLink — ${s.session.model} (${s.session.kind})` : 'TabLink — 연결 안 됨');
  const key = JSON.stringify([s.devices, s.selectedId, s.config.audio, s.config.mc]);
  if (key === menuKey) return;
  menuKey = key;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '열기', click: show },
      {
        label: '기기',
        submenu: s.devices.map((d) => ({
          label: `${d.model || '승인 대기 중인 기기'} (${d.transports.map((t) => t.kind).join(', ')})`,
          type: 'radio',
          checked: d.id === s.selectedId,
          click: () => manager.select(d.id),
        })),
      },
      {
        label: '소리를 PC로',
        type: 'checkbox',
        checked: s.config.audio,
        click: (i) => manager.apply({ audio: i.checked }),
      },
      {
        label: '멀티 컨트롤',
        type: 'checkbox',
        checked: s.config.mc,
        click: (i) => manager.apply({ mc: i.checked }),
      },
      { type: 'separator' },
      { label: '종료', click: quit },
    ]),
  );
}
async function quit() {
  if (quitting) return;
  quitting = true;
  manager?.stop();
  await helper?.stop();
  app.quit();
}
app.whenReady().then(async () => {
  const cfg = config.load(),
    dir = config.scrcpyDir(app.isPackaged),
    paths = {
      adb: config.adbPath(dir, app.isPackaged),
      scrcpy: config.scrcpyPath(dir, app.isPackaged),
      server: config.serverPath(dir),
    },
    version = await config.version(dir, app.isPackaged);
  helper = new Helper(config.helper(app.isPackaged), (msg) => manager.log(msg));
  manager = new Manager(cfg, helper, new Devices(paths.adb), dir, version, smoke, paths);
  const windowOptions = {
    width: 960,
    height: 660,
    resizable: false,
    maximizable: false,
    show: false,
    backgroundColor: overlay().color,
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    autoHideMenuBar: true,
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  };
  if (!isMac) windowOptions.titleBarOverlay = overlay();
  win = new BrowserWindow(windowOptions);
  win.setMenu(null);
  win.on('ready-to-show', () => {
    if (!process.argv.includes('--tray') || smoke) show();
  });
  win.on('close', (e) => {
    if (!quitting) {
      e.preventDefault();
      if (manager.cfg.close_to_tray) win.hide();
      else quit();
    }
  });
  if (!isMac) nativeTheme.on('updated', () => win.setTitleBarOverlay(overlay()));
  win.webContents.on('console-message', (_e, level, message) => {
    if (level >= 2) console.error('renderer:', message);
  });
  tray = new Tray(path.join(__dirname, '..', 'assets', isMac ? 'icon.png' : 'icon.ico'));
  tray.on('click', show);
  manager.on('state', (s) => {
    if (!win.isDestroyed()) win.webContents.send('state', s);
    updateTray(s);
  });
  manager.on('log', (l) => {
    if (!win.isDestroyed()) win.webContents.send('log', l);
  });
  ipcMain.handle('getState', () => manager.state);
  ipcMain.handle('getLogs', () => manager.logs);
  ipcMain.handle('setConfig', (_e, p) => {
    validate(p);
    const c = manager.apply(p);
    if ('autostart' in p) autostart();
    return c;
  });
  ipcMain.handle('selectDevice', (_e, id) => manager.select(id));
  ipcMain.handle('forgetDevice', () => manager.forget());
  ipcMain.handle('connectIp', async (_e, ep) => {
    if (typeof ep !== 'string' || !ep.trim()) throw Error('주소를 입력하세요');
    const r = await manager.devices.connect(ep.trim());
    manager.log((r.ok ? '연결 성공: ' : '연결 실패: ') + r.out);
    manager.wake();
    return r;
  });
  ipcMain.handle('pair', async (_e, ep, code) => {
    if (typeof ep !== 'string' || !ep.trim() || !/^\d{6}$/.test(code))
      throw Error('주소와 6자리 코드를 입력하세요');
    const r = await manager.devices.pair(ep.trim(), code);
    manager.log((r.ok ? '페어링 성공: ' : '페어링 실패: ') + r.out);
    manager.lastMdns = 0;
    manager.wake();
    return r;
  });
  ipcMain.handle('hide', () => win.hide());
  ipcMain.handle('quit', () => quit());
  helper.start();
  manager.start();
  updateTray(manager.state);
  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  if (smoke)
    setTimeout(async () => {
      try {
        fs.mkdirSync(path.join(__dirname, '..', 'build'), { recursive: true });
        fs.writeFileSync(
          path.join(__dirname, '..', 'build', 'smoke.png'),
          (await win.webContents.capturePage()).toPNG(),
        );
      } catch (e) {
        console.error(e);
      }
      await quit();
    }, 4000);
});
app.on('window-all-closed', () => {});
// Cmd+Q (and any other app-level quit) must run the full shutdown: the window's close
// handler only hides to the tray, so without this the app never really exits on macOS.
app.on('before-quit', (e) => {
  if (!quitting) {
    e.preventDefault();
    quit();
  }
});
