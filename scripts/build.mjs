import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { packager } = require('@electron/packager');
const config = require('../electron/config.js');
const root = path.resolve(import.meta.dirname, '..');
process.chdir(root);
execFileSync(
  'dotnet',
  ['publish', 'helper', '-c', 'Release', '-r', 'win-x64', '-o', 'build/helper-release'],
  {
    stdio: 'inherit',
  },
);
const scrcpy = config.scrcpyDir(false);
if (!scrcpy) throw Error('scrcpy directory not found');
fs.mkdirSync('dist', { recursive: true });
const [out] = await packager({
  dir: root,
  out: path.join(root, 'dist'),
  overwrite: true,
  platform: 'win32',
  arch: 'x64',
  name: 'TabLink',
  icon: path.join(root, 'assets/icon.ico'),
  asar: true,
  ignore: (p) => p && !/^\/(electron|renderer|assets)(\/|$)/.test(p) && p !== '/package.json',
});
fs.mkdirSync(path.join(out, 'resources/helper'), { recursive: true });
fs.copyFileSync(
  'build/helper-release/TabLinkHelper.exe',
  path.join(out, 'resources/helper/TabLinkHelper.exe'),
);
fs.cpSync(scrcpy, path.join(out, 'resources/scrcpy'), { recursive: true });
for (const f of ['README.md', 'LICENSE']) fs.copyFileSync(f, path.join(out, f));
// ship the folder as dist/TabLink, zipped with Windows' own bsdtar (Git's tar can't write zip)
const final = path.join(root, 'dist', 'TabLink');
fs.rmSync(final, { recursive: true, force: true });
fs.renameSync(out, final);
const zip = path.join(root, 'dist', 'TabLink-win64.zip');
fs.rmSync(zip, { force: true });
execFileSync(
  path.join(process.env.SystemRoot, 'System32', 'tar.exe'),
  ['-a', '-c', '-f', zip, '-C', path.dirname(final), 'TabLink'],
  {
    stdio: 'inherit',
  },
);
console.log('built', zip);
