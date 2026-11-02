import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { packager } = require('@electron/packager');
const root = path.resolve(import.meta.dirname, '..');
const helper = path.join(root, 'helper-mac', '.build', 'release', 'TabLinkHelper');
const buildDir = path.join(root, 'build');
const iconset = path.join(buildDir, 'icon.iconset');
const icon = path.join(buildDir, 'icon.icns');

process.chdir(root);

execFileSync('swift', ['build', '-c', 'release', '--package-path', 'helper-mac'], {
  cwd: root,
  stdio: 'inherit',
});
if (!fs.existsSync(helper)) throw Error(`Swift helper was not built: ${helper}`);

fs.mkdirSync(buildDir, { recursive: true });
fs.rmSync(iconset, { recursive: true, force: true });
fs.mkdirSync(iconset, { recursive: true });
const iconSizes = [
  ['icon_16x16.png', 16],
  ['icon_16x16@2x.png', 32],
  ['icon_32x32.png', 32],
  ['icon_32x32@2x.png', 64],
  ['icon_128x128.png', 128],
  ['icon_128x128@2x.png', 256],
  ['icon_256x256.png', 256],
  ['icon_256x256@2x.png', 512],
  ['icon_512x512.png', 512],
  ['icon_512x512@2x.png', 1024],
];
for (const [name, size] of iconSizes)
  execFileSync(
    'sips',
    ['-z', String(size), String(size), 'assets/icon.png', '--out', path.join(iconset, name)],
    { cwd: root, stdio: 'inherit' },
  );
execFileSync('iconutil', ['-c', 'icns', iconset, '-o', icon], { cwd: root, stdio: 'inherit' });

fs.mkdirSync(path.join(root, 'dist'), { recursive: true });
const [out] = await packager({
  dir: root,
  out: path.join(root, 'dist'),
  overwrite: true,
  platform: 'darwin',
  arch: 'arm64',
  name: 'TabLink',
  icon: icon.replace(/\.icns$/, ''), // packager appends the .icns extension itself
  asar: true,
  ignore: (p) => p && !/^\/(electron|renderer|assets)(\/|$)/.test(p) && p !== '/package.json',
});

const appPath = out.endsWith('.app') ? out : path.join(out, 'TabLink.app');
if (!fs.existsSync(appPath)) throw Error(`Packaged app was not found: ${appPath}`);
const resources = path.join(appPath, 'Contents', 'Resources');
fs.mkdirSync(path.join(resources, 'helper'), { recursive: true });
const packagedHelper = path.join(resources, 'helper', 'TabLinkHelper');
fs.copyFileSync(helper, packagedHelper);
fs.chmodSync(packagedHelper, 0o755);

const appFolder = path.dirname(appPath);
for (const file of ['README.md', 'LICENSE']) fs.copyFileSync(file, path.join(appFolder, file));

const zip = path.join(root, 'dist', 'TabLink-macos-arm64.zip');
fs.rmSync(zip, { force: true });
execFileSync('ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', appPath, zip], {
  cwd: root,
  stdio: 'inherit',
});
console.log('built', zip);
