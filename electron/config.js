const fs = require('fs'),
  path = require('path'),
  { execFile } = require('child_process');
const defaults = {
  device_id: '',
  transport: 'auto',
  auto_wifi: true,
  known_endpoints: {},
  audio: true,
  audio_dup: false,
  audio_buffer: 50,
  mc: true,
  side: 'right',
  monitor: -1,
  speed: 1,
  clipboard: true,
  hangul: 'shift_space',
  autostart: false,
  close_to_tray: true,
  audio_source: 'playback',
};
const dir = path.join(process.env.APPDATA || process.cwd(), 'TabLink'),
  file = path.join(dir, 'config.json');
function load() {
  try {
    return { ...defaults, ...JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')) };
  } catch {
    return { ...defaults, known_endpoints: {} };
  }
}
function save(c) {
  fs.mkdirSync(dir, { recursive: true });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(c, null, 2));
  fs.renameSync(tmp, file);
}
function helper(packaged) {
  return packaged
    ? path.join(process.resourcesPath, 'helper', 'TabLinkHelper.exe')
    : path.join(__dirname, '..', 'build', 'helper', 'TabLinkHelper.exe');
}
function scrcpyDir(packaged = false) {
  const candidates = [process.env.SCRCPY_DIR, packaged && path.join(process.resourcesPath, 'scrcpy')].filter(
    Boolean,
  );
  const root = path.join(process.env.LOCALAPPDATA || '', 'Microsoft', 'WinGet', 'Packages');
  try {
    for (const p of fs
      .readdirSync(root)
      .filter((x) => x.startsWith('Genymobile.scrcpy'))
      .sort()
      .reverse()) {
      const base = path.join(root, p);
      candidates.push(
        base,
        ...fs
          .readdirSync(base)
          .sort()
          .reverse()
          .map((x) => path.join(base, x)),
      );
    }
  } catch {}
  return (
    candidates.find(
      (p) => fs.existsSync(path.join(p, 'adb.exe')) && fs.existsSync(path.join(p, 'scrcpy-server')),
    ) || null
  );
}
function version(dir) {
  return new Promise((resolve) => {
    if (!dir) return resolve('5.0.1');
    execFile(path.join(dir, 'scrcpy.exe'), ['--version'], { windowsHide: true, timeout: 5000 }, (e, out) =>
      resolve((out || '').match(/scrcpy (\S+)/)?.[1] || '5.0.1'),
    );
  });
}
module.exports = { defaults, dir, load, save, helper, scrcpyDir, version };
