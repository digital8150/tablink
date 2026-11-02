const { execFile } = require('child_process');
class Devices {
  constructor(adb) {
    this.adb = adb;
    this.cache = new Map();
  }
  run(args, timeout = 10000) {
    return new Promise((resolve) => {
      if (!this.adb) return resolve('');
      execFile(this.adb, args, { windowsHide: true, timeout, maxBuffer: 1024 * 1024 }, (e, out, err) =>
        resolve((out || '') + (err || '')),
      );
    });
  }
  async listTransports() {
    const out = await this.run(['devices', '-l']);
    const rows = out
      .split(/\r?\n/)
      .slice(1)
      .map((x) => x.trim().split(/\s+/))
      .filter((x) => x.length >= 2);
    return Promise.all(
      rows.map(async (p) => {
        const serial = p[0],
          state = p[1],
          wireless = /^\d+\.\d+\.\d+\.\d+:\d+$/.test(serial) || serial.includes('._adb-tls-connect.');
        let id = serial;
        if (state === 'device') {
          if (!this.cache.has(serial))
            this.cache.set(
              serial,
              (await this.run(['-s', serial, 'shell', 'getprop', 'ro.serialno'], 5000)).trim() || serial,
            );
          id = this.cache.get(serial);
        }
        return {
          serial,
          state,
          model: (p.find((x) => x.startsWith('model:')) || 'model:').slice(6).replace(/_/g, '-'),
          wireless,
          kind: wireless ? 'Wi-Fi' : 'USB',
          device_id: id,
        };
      }),
    );
  }
  async mdnsEndpoints() {
    const out = await this.run(['mdns', 'services'], 8000);
    return out
      .split(/\r?\n/)
      .map((x) => x.trim().match(/^adb-(\S+?)-\S*\s+_adb-tls-connect\._tcp\.?\s+(\d+\.\d+\.\d+\.\d+:\d+)/))
      .filter(Boolean)
      .map((m) => [m[1], m[2]]);
  }
  async connect(ep) {
    const out = (await this.run(['connect', ep])).trim();
    return { ok: out.includes('connected') && !/cannot|failed/.test(out), out };
  }
  async pair(ep, code) {
    const out = (await this.run(['pair', ep, code], 20000)).trim();
    return { ok: out.includes('Successfully paired'), out };
  }
}
module.exports = Devices;
