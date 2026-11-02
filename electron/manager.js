const { EventEmitter } = require('events'),
  fs = require('fs'),
  path = require('path'),
  cfgmod = require('./config');
class Manager extends EventEmitter {
  constructor(cfg, helper, devices, dir, version, smoke, paths) {
    super();
    Object.assign(this, {
      cfg,
      helper,
      devices,
      dir,
      version,
      smoke,
      paths: paths || {
        adb: dir && path.join(dir, process.platform === 'darwin' ? 'adb' : 'adb.exe'),
        scrcpy: dir && path.join(dir, process.platform === 'darwin' ? 'scrcpy' : 'scrcpy.exe'),
        server: dir && path.join(dir, 'scrcpy-server'),
      },
    });
    this.state = {
      devices: [],
      selectedId: cfg.device_id,
      selection: 'none',
      session: null,
      ctrl: 'off',
      audio: 'off',
      active: false,
      monitors: [],
      target: 0,
      info: { width: 2960, height: 1848, gainX: 1, gainY: 1, linear: true },
      config: cfg,
    };
    this.logs = [];
    this.lastMdns = 0;
    this.fail = { ctrl: 0, audio: 0 };
    this.retry = {};
    this.running = false;
    helper.on('event', (e) => this.event(e));
    helper.on('restart', () => {
      this.state.ctrl = 'off';
      this.state.audio = 'off';
      if (this.state.session) {
        this.attach();
        this.audio();
      }
      this.wake();
    });
  }
  log(msg) {
    const d = new Date(),
      stamp = (n) => String(n).padStart(2, '0'),
      time = `${stamp(d.getHours())}:${stamp(d.getMinutes())}:${stamp(d.getSeconds())}`,
      date = `${d.getFullYear()}-${stamp(d.getMonth() + 1)}-${stamp(d.getDate())}`;
    const item = { time, msg };
    this.logs.push(item);
    if (this.logs.length > 200) this.logs.shift();
    try {
      fs.mkdirSync(cfgmod.dir, { recursive: true });
      fs.appendFileSync(path.join(cfgmod.dir, 'log.txt'), `${date} ${time}  ${msg}\n`);
    } catch {}
    this.emit('log', item);
  }
  push() {
    if (this.pushTimer) return;
    this.pushTimer = setTimeout(() => {
      this.pushTimer = null;
      this.emit('state', this.state);
    }, 50);
  }
  config() {
    const c = this.cfg;
    this.helper.send({
      cmd: 'config',
      enabled: c.mc,
      side: c.side,
      monitor: c.monitor,
      speed: c.speed,
      hangul: c.hangul,
      clipboard: c.clipboard,
    });
  }
  apply(p) {
    const old = { ...this.cfg };
    Object.assign(this.cfg, p);
    cfgmod.save(this.cfg);
    this.state.selectedId = this.cfg.device_id;
    this.config();
    if (this.state.session) {
      if (old.mc !== this.cfg.mc) {
        if (this.cfg.mc) this.attach();
        else {
          this.helper.send({ cmd: 'detach' });
          this.state.ctrl = 'off';
        }
      }
      if (['audio', 'audio_source', 'audio_dup', 'audio_buffer'].some((k) => old[k] !== this.cfg[k]))
        this.audio();
    }
    this.push();
    this.wake();
    return this.cfg;
  }
  attach() {
    if (this.smoke || !this.state.session || !this.cfg.mc) return;
    this.helper.send({
      cmd: 'attach',
      serial: this.state.session.serial,
      adb: this.paths.adb,
      server: this.paths.server,
      version: this.version,
    });
    this.state.ctrl = 'starting';
  }
  audio() {
    if (this.smoke) return;
    const s = this.state.session,
      c = this.cfg;
    this.helper.send(
      s && c.audio
        ? {
            cmd: 'audio',
            serial: s.serial,
            scrcpy: this.paths.scrcpy,
            source: c.audio_source,
            dup: c.audio_dup,
            buffer: c.audio_buffer,
          }
        : { cmd: 'audio' },
    );
    if (!s || !c.audio) this.state.audio = 'off';
  }
  end() {
    if (this.state.session && !this.smoke) {
      this.helper.send({ cmd: 'detach' });
      this.helper.send({ cmd: 'audio' });
    }
    this.state.session = null;
    this.state.ctrl = 'off';
    this.state.audio = 'off';
    this.state.active = false;
    this.retry = {};
    this.fail = { ctrl: 0, audio: 0 };
  }
  select(id) {
    if (!this.state.devices.some((d) => d.id === id)) throw Error('기기를 찾을 수 없습니다');
    this.end();
    this.apply({ device_id: id });
  }
  forget() {
    this.end();
    this.apply({ device_id: '' });
  }
  event(e) {
    if (e.ev === 'log') return this.log(e.msg);
    if (e.ev === 'ready') {
      this.config();
      this.helper.send({ cmd: 'monitors' });
    }
    if (e.ev === 'monitors') {
      this.state.monitors = e.list;
      this.state.target = e.target;
    }
    if (e.ev === 'info')
      this.state.info = {
        width: e.width,
        height: e.height,
        gainX: e.gainX,
        gainY: e.gainY,
        linear: e.linear,
      };
    if (e.ev === 'active') this.state.active = e.value;
    if (e.ev === 'ctrl' || e.ev === 'audio') {
      const k = e.ev;
      this.state[k] = e.state;
      if (e.message) this.log(e.message);
      if (
        ((k === 'ctrl' && ['dead', 'error'].includes(e.state)) ||
          (k === 'audio' && ['stopped', 'error'].includes(e.state))) &&
        this.state.session &&
        (k === 'ctrl' ? this.cfg.mc : this.cfg.audio)
      ) {
        this.fail[k]++;
        if (this.fail[k] === 3) this.log(`${k} 재시도를 10초 간격으로 변경합니다`);
        this.retry[k] = Date.now() + (this.fail[k] >= 3 ? 10000 : 2000);
        this.wake();
      } else if (e.state === (k === 'ctrl' ? 'alive' : 'running')) {
        this.fail[k] = 0;
        delete this.retry[k];
      }
    }
    this.push();
  }
  wake() {
    if (this.waitResolve) {
      this.waitResolve();
      this.waitResolve = null;
    }
  }
  async start() {
    this.running = true;
    this.config();
    while (this.running) {
      try {
        await this.tick();
      } catch (e) {
        this.log('오류: ' + e.message);
      }
      await new Promise((r) => {
        const t = setTimeout(() => {
          this.waitResolve = null;
          r();
        }, 1500);
        this.waitResolve = () => {
          clearTimeout(t);
          r();
        };
      });
    }
    this.end();
  }
  stop() {
    this.running = false;
    this.wake();
  }
  async tick() {
    let ts = await this.devices.listTransports();
    let dirty = false;
    for (const t of ts)
      if (
        t.wireless &&
        t.state === 'device' &&
        t.serial.includes(':') &&
        this.cfg.known_endpoints[t.device_id] !== t.serial
      ) {
        this.cfg.known_endpoints[t.device_id] = t.serial;
        dirty = true;
      }
    const groups = new Map();
    for (const t of ts) {
      const id = t.device_id;
      if (!groups.has(id)) groups.set(id, { id, model: t.model, transports: [], usable: false });
      const g = groups.get(id);
      if (t.model) g.model = t.model;
      g.transports.push({ serial: t.serial, kind: t.kind, state: t.state });
      g.usable ||= t.state === 'device';
    }
    const ds = [...groups.values()],
      usable = ds.filter((d) => d.usable);
    if (!this.cfg.device_id && usable.length === 1) {
      this.cfg.device_id = usable[0].id;
      dirty = true;
    }
    if (dirty) cfgmod.save(this.cfg);
    this.state.devices = ds;
    this.state.selectedId = this.cfg.device_id;
    this.state.selection = this.cfg.device_id
      ? ds.some((d) => d.id === this.cfg.device_id)
        ? 'ok'
        : ds.length
          ? 'missing'
          : 'none'
      : usable.length > 1
        ? 'choose'
        : 'none';
    const allowed = (t) =>
      t.state === 'device' &&
      (this.cfg.transport === 'auto' || (this.cfg.transport === 'wifi') === t.wireless);
    const best = ts
      .filter((t) => t.device_id === this.cfg.device_id && allowed(t))
      .sort((a, b) => Number(a.wireless) - Number(b.wireless))[0];
    const cur = this.state.session;
    if (
      cur &&
      (!ts.some((t) => t.serial === cur.serial && allowed(t)) ||
        (best && cur.kind === 'Wi-Fi' && best.kind === 'USB' && !this.state.active))
    ) {
      this.log('연결을 전환합니다');
      this.end();
    }
    if (!this.state.session && best) {
      this.state.session = {
        serial: best.serial,
        kind: best.kind,
        model: best.model,
        deviceId: best.device_id,
      };
      this.log(`${best.kind}로 연결: ${best.model} (${best.serial})`);
      this.attach();
      this.audio();
    }
    for (const k of ['ctrl', 'audio'])
      if (this.retry[k] && Date.now() >= this.retry[k]) {
        delete this.retry[k];
        if (k === 'ctrl') this.attach();
        else this.audio();
      }
    this.push();
    await this.discoverWifi(ts);
  }
  async discoverWifi(ts) {
    if (this.cfg.auto_wifi && this.cfg.transport !== 'usb' && Date.now() - this.lastMdns >= 15000) {
      this.lastMdns = Date.now();
      const candidates = [
        ...(await this.devices.mdnsEndpoints()),
        ...Object.entries(this.cfg.known_endpoints),
      ];
      const have = new Set(ts.filter((t) => t.wireless && t.state === 'device').map((t) => t.device_id)),
        present = new Set(ts.filter((t) => t.state === 'device').map((t) => t.serial));
      let changed = false;
      for (const [id, ep] of candidates) {
        if (have.has(id) || present.has(ep)) continue;
        const r = await this.devices.connect(ep);
        if (r.ok) {
          have.add(id);
          changed = true;
          this.log('Wi-Fi 연결됨: ' + ep);
        }
      }
      if (changed) this.wake();
    }
  }
}
module.exports = Manager;
