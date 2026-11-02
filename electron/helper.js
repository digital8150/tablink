const { EventEmitter } = require('events'),
  { spawn } = require('child_process'),
  readline = require('readline'),
  fs = require('fs');
class Helper extends EventEmitter {
  constructor(exe, log) {
    super();
    this.exe = exe;
    this.log = log;
    this.stopping = false;
    this.lastConfig = null;
    this.proc = null;
    this.timer = null;
  }
  start() {
    if (this.stopping) return;
    if (!fs.existsSync(this.exe)) {
      this.log(`도우미를 찾을 수 없습니다: ${this.exe}`);
      return;
    }
    const p = (this.proc = spawn(this.exe, [], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] }));
    readline.createInterface({ input: p.stdout }).on('line', (line) => {
      try {
        this.emit('event', JSON.parse(line));
      } catch {
        this.log('잘못된 도우미 응답: ' + line);
      }
    });
    readline.createInterface({ input: p.stderr }).on('line', (line) => this.log('도우미: ' + line));
    p.on('error', (e) => this.log('도우미 오류: ' + e.message));
    p.on('exit', () => {
      if (this.proc === p) this.proc = null;
      if (!this.stopping) {
        this.log('도우미가 종료되어 다시 시작합니다');
        this.timer = setTimeout(() => {
          this.start();
          if (this.lastConfig) this.send(this.lastConfig);
          this.emit('restart');
        }, 1000);
      }
    });
  }
  send(o) {
    if (o.cmd === 'config') this.lastConfig = o;
    if (this.proc?.stdin.writable) this.proc.stdin.write(JSON.stringify(o) + '\n');
  }
  async stop() {
    this.stopping = true;
    clearTimeout(this.timer);
    const p = this.proc;
    if (!p) return;
    this.send({ cmd: 'quit' });
    await Promise.race([new Promise((r) => p.once('exit', r)), new Promise((r) => setTimeout(r, 2000))]);
    if (this.proc) p.kill();
  }
}
module.exports = Helper;
