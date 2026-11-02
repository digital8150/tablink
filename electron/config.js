const fs = require('fs'),
  path = require('path'),
  os = require('os'),
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
const dir =
    process.platform === 'darwin'
      ? path.join(os.homedir(), 'Library', 'Application Support', 'TabLink')
      : path.join(process.env.APPDATA || process.cwd(), 'TabLink'),
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
  if (process.platform === 'darwin')
    return packaged
      ? path.join(process.resourcesPath, 'helper', 'TabLinkHelper')
      : path.join(__dirname, '..', 'helper-mac', '.build', 'release', 'TabLinkHelper');
  return packaged
    ? path.join(process.resourcesPath, 'helper', 'TabLinkHelper.exe')
    : path.join(__dirname, '..', 'build', 'helper', 'TabLinkHelper.exe');
}
function scrcpyDir(packaged = false) {
  if (process.platform === 'darwin') {
    const candidates = [process.env.SCRCPY_DIR, packaged && path.join(process.resourcesPath, 'scrcpy')].filter(
      Boolean,
    );
    candidates.push('/opt/homebrew/share/scrcpy', '/usr/local/share/scrcpy');
    return candidates.find((p) => fs.existsSync(path.join(p, 'scrcpy-server'))) || null;
  }
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
function adbPath(dir, packaged = false) {
  if (process.platform !== 'darwin') return dir ? path.join(dir, 'adb.exe') : null;
  const candidates = [
    dir && path.join(dir, 'adb'),
    process.env.SCRCPY_DIR && path.join(process.env.SCRCPY_DIR, 'adb'),
    packaged && path.join(process.resourcesPath, 'scrcpy', 'adb'),
    '/opt/homebrew/bin/adb',
    '/opt/homebrew/share/android-commandlinetools/platform-tools/adb',
    '/usr/local/bin/adb',
  ].filter(Boolean);
  return candidates.find((p) => fs.existsSync(p)) || null;
}
function scrcpyPath(dir, packaged = false) {
  if (process.platform !== 'darwin') return dir ? path.join(dir, 'scrcpy.exe') : null;
  const candidates = [
    dir && path.join(dir, 'scrcpy'),
    process.env.SCRCPY_DIR && path.join(process.env.SCRCPY_DIR, 'scrcpy'),
    packaged && path.join(process.resourcesPath, 'scrcpy', 'scrcpy'),
    '/opt/homebrew/bin/scrcpy',
    '/usr/local/bin/scrcpy',
  ].filter(Boolean);
  return candidates.find((p) => fs.existsSync(p)) || null;
}
function serverPath(dir) {
  return dir ? path.join(dir, 'scrcpy-server') : null;
}
function version(dir, packaged = false) {
  return new Promise((resolve) => {
    const binary = scrcpyPath(dir, packaged);
    if (!binary) return resolve('5.0.1');
    execFile(binary, ['--version'], { windowsHide: true, timeout: 5000 }, (e, out) =>
      resolve((out || '').match(/scrcpy (\S+)/)?.[1] || '5.0.1'),
    );
  });
}
module.exports = { defaults, dir, load, save, helper, scrcpyDir, adbPath, scrcpyPath, serverPath, version };
