const $ = (s) => document.querySelector(s),
  api = window.tablink;
let state,
  layoutKey = '',
  targetRect = null,
  speedTimer;
const svg = $('#diagram'),
  ns = 'http://www.w3.org/2000/svg';
function el(tag, attrs, text) {
  const n = document.createElementNS(ns, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text) n.textContent = text;
  return n;
}
function draw(s) {
  const mons = s.monitors.length
      ? s.monitors
      : [{ left: 0, top: 0, right: 1920, bottom: 1080, primary: true }],
    t = mons[s.target] || mons[0],
    w = t.right - t.left,
    h = t.bottom - t.top,
    side = s.config.side,
    ratio = s.info.width / Math.max(s.info.height, 1);
  let th = h * 0.75,
    tw = th * ratio;
  if (side === 'top' || side === 'bottom') {
    tw = w * 0.55;
    th = tw / ratio;
  }
  const gap = 0.04 * Math.max(w, h),
    cx = (t.left + t.right) / 2,
    cy = (t.top + t.bottom) / 2,
    tab = {
      right: [t.right + gap, cy - th / 2, t.right + gap + tw, cy + th / 2],
      left: [t.left - gap - tw, cy - th / 2, t.left - gap, cy + th / 2],
      top: [cx - tw / 2, t.top - gap - th, cx + tw / 2, t.top - gap],
      bottom: [cx - tw / 2, t.bottom + gap, cx + tw / 2, t.bottom + gap + th],
    }[side];
  const xs = mons.flatMap((m) => [m.left, m.right]).concat([tab[0], tab[2]]),
    ys = mons.flatMap((m) => [m.top, m.bottom]).concat([tab[1], tab[3]]),
    minx = Math.min(...xs),
    maxx = Math.max(...xs),
    miny = Math.min(...ys),
    maxy = Math.max(...ys),
    scale = Math.min(474 / (maxx - minx), 94 / (maxy - miny)),
    ox = (510 - (maxx - minx) * scale) / 2 - minx * scale,
    oy = (130 - (maxy - miny) * scale) / 2 - miny * scale,
    tr = (r) => [ox + r[0] * scale, oy + r[1] * scale, (r[2] - r[0]) * scale, (r[3] - r[1]) * scale];
  svg.replaceChildren();
  mons.forEach((m, i) => {
    const [x, y, w1, h1] = tr([m.left, m.top, m.right, m.bottom]);
    if (m === t) targetRect = [x, y, w1, h1];
    svg.append(
      el('rect', {
        x,
        y,
        width: w1,
        height: h1,
        rx: 7,
        fill: 'var(--card)',
        stroke: m === t ? 'var(--accent)' : 'var(--line)',
        'stroke-width': m === t ? 2 : 1,
      }),
      el(
        'text',
        { x: x + w1 / 2, y: y + h1 / 2, 'text-anchor': 'middle', fill: 'var(--text)', 'font-size': 16 },
        String(i + 1),
      ),
      el(
        'text',
        { x: x + w1 / 2, y: y + h1 / 2 + 15, 'text-anchor': 'middle', fill: 'var(--muted)', 'font-size': 9 },
        `${m.right - m.left}×${m.bottom - m.top}`,
      ),
    );
  });
  const [x, y, wt, ht] = tr(tab);
  svg.append(
    el('rect', {
      id: 'tablet',
      x,
      y,
      width: wt,
      height: ht,
      rx: 7,
      fill: s.active ? 'var(--accent)' : 'var(--card)',
      stroke: s.config.mc ? 'var(--accent)' : 'var(--line)',
      'stroke-width': 2,
    }),
    el(
      'text',
      { x: x + wt / 2, y: y + ht / 2, 'text-anchor': 'middle', fill: 'var(--text)', 'font-size': 12 },
      'Tab',
    ),
  );
}
function update(s) {
  state = s;
  const c = s.config;
  $('#pill').textContent =
    s.selection === 'choose' ? '● 기기 선택 필요' : s.session ? `● ${s.session.kind} 연결됨` : '● 연결 안 됨';
  $('#pill').style.color =
    s.selection === 'choose' ? 'var(--amber)' : s.session ? 'var(--green)' : 'var(--muted)';
  document.querySelectorAll('[data-key]').forEach((n) => {
    const v = c[n.dataset.key];
    if (n.type === 'checkbox') n.checked = v;
    else if (n.id !== 'monitor') n.value = v;
  });
  document.querySelector(`[name=side][value=${c.side}]`).checked = true;
  document.querySelector(`[name=transport][value=${c.transport}]`).checked = true;
  // don't fight the user while a slider is being dragged
  if (document.activeElement !== $('#speed')) {
    $('#speed').value = c.speed;
    $('#speedValue').textContent = Number(c.speed).toFixed(1) + 'x';
  }
  if (document.activeElement !== $('#buffer')) {
    $('#buffer').value = c.audio_buffer;
    $('#bufferValue').textContent = c.audio_buffer + ' ms';
  }
  $('[data-key=audio_dup]').disabled = c.audio_source === 'output';
  $('#dupHint').textContent = c.audio_source === 'output' ? '전체 출력 캡처에서는 사용할 수 없습니다' : '';
  $('#transportHint').textContent = {
    auto: 'USB 우선, 케이블이 빠지면 Wi-Fi로 자동 전환',
    usb: 'USB 케이블로만 연결',
    wifi: '무선 디버깅으로만 연결',
  }[c.transport];
  $('#mcstate').textContent = !c.mc
    ? '꺼짐'
    : s.ctrl !== 'alive'
      ? '태블릿 연결을 기다리는 중…'
      : s.active
        ? '지금 태블릿을 조작하고 있어요 — 반대로 밀거나 Ctrl+Alt+M으로 복귀'
        : `마우스를 ${{ right: '오른쪽', left: '왼쪽', top: '위', bottom: '아래' }[c.side]} 가장자리로 밀면 태블릿으로 넘어가요`;
  const key = JSON.stringify([s.monitors, s.target, s.info.width, s.info.height, c.side, c.mc]);
  if (key !== layoutKey) {
    layoutKey = key;
    draw(s);
  } else if ($('#tablet')) $('#tablet').setAttribute('fill', s.active ? 'var(--accent)' : 'var(--card)');
  const select = $('#monitor'),
    opts = [
      '자동 (태블릿 방향의 가장 바깥 모니터)',
      ...s.monitors.map(
        (m, i) =>
          `${i + 1}: ${m.right - m.left}×${m.bottom - m.top} @(${m.left},${m.top})${m.primary ? ' · 주 모니터' : ''}`,
      ),
    ];
  if (select.dataset.options !== JSON.stringify(opts)) {
    select.replaceChildren(
      ...opts.map((v, i) => {
        const o = document.createElement('option');
        o.value = i - 1;
        o.textContent = v;
        return o;
      }),
    );
    select.dataset.options = JSON.stringify(opts);
  }
  select.value = String(c.monitor);
  const list = $('#deviceList'),
    devKey = JSON.stringify([s.devices, s.selectedId, s.session?.deviceId]);
  if (list.dataset.key !== devKey) {
    list.dataset.key = devKey;
    list.replaceChildren(
      ...s.devices.map((d) => {
        const b = document.createElement('button');
        b.className = 'device' + (d.id === s.selectedId ? ' selected' : '');
        const radio = document.createElement('span');
        radio.textContent = d.id === s.selectedId ? '◉' : '○';
        const name = document.createElement('span');
        name.className = 'name';
        name.textContent = `${d.model || '승인 대기 중인 기기'} · ${d.id.slice(0, 12)}${s.session?.deviceId === d.id ? ' · 사용 중' : ''}`;
        b.append(radio, name);
        for (const t of d.transports) {
          const chip = document.createElement('span');
          chip.className = 'chip' + (t.state === 'device' ? '' : ' off');
          chip.textContent =
            t.kind +
            (t.state === 'device'
              ? ''
              : ` ${t.state === 'unauthorized' ? '승인 필요' : t.state === 'offline' ? '오프라인' : t.state}`);
          b.append(chip);
        }
        b.onclick = () => api.selectDevice(d.id);
        return b;
      }),
    );
  }
  $('#deviceHint').textContent =
    s.selection === 'choose'
      ? '여러 기기가 연결됨 — 사용할 기기를 선택하세요'
      : s.selection === 'missing'
        ? '저장된 기기가 연결되지 않음 — 다른 기기를 선택할 수 있어요'
        : s.devices.some((d) => d.transports.some((t) => t.state === 'unauthorized'))
          ? '태블릿에서 USB 디버깅 허용을 눌러주세요'
          : !s.devices.length
            ? 'USB를 연결하거나 태블릿에서 무선 디버깅을 켜세요'
            : '';
  $('#deviceHint').style.color = ['choose', 'missing'].includes(s.selection)
    ? 'var(--amber)'
    : 'var(--muted)';
}
function log(l) {
  const box = $('#log'),
    bottom = box.scrollHeight - box.scrollTop - box.clientHeight < 12;
  const row = document.createElement('div');
  row.textContent = `${l.time}  ${l.msg}`;
  box.append(row);
  while (box.children.length > 200) box.firstChild.remove();
  if (bottom) box.scrollTop = box.scrollHeight;
}
document.querySelectorAll('[data-key]').forEach((n) =>
  n.addEventListener('change', () =>
    api.setConfig({
      [n.dataset.key]: n.type === 'checkbox' ? n.checked : n.id === 'monitor' ? Number(n.value) : n.value,
    }),
  ),
);
document
  .querySelectorAll('[name=side],[name=transport]')
  .forEach((n) => n.addEventListener('change', () => api.setConfig({ [n.name]: n.value })));
$('#speed').oninput = (e) => {
  const v = Number(e.target.value);
  $('#speedValue').textContent = v.toFixed(1) + 'x';
  clearTimeout(speedTimer);
  speedTimer = setTimeout(() => api.setConfig({ speed: v }), 100);
};
$('#buffer').oninput = (e) => ($('#bufferValue').textContent = e.target.value + ' ms');
$('#buffer').onchange = (e) => api.setConfig({ audio_buffer: Number(e.target.value) });
svg.onclick = (e) => {
  if (!targetRect) return;
  const p = svg.createSVGPoint();
  p.x = e.clientX;
  p.y = e.clientY;
  const q = p.matrixTransform(svg.getScreenCTM().inverse()),
    [x, y, w, h] = targetRect,
    dx = (q.x - x - w / 2) / w,
    dy = (q.y - y - h / 2) / h;
  api.setConfig({
    side: Math.abs(dx) >= Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : dy > 0 ? 'bottom' : 'top',
  });
};
$('#hide').onclick = () => api.hide();
$('#quit').onclick = () => api.quit();
let pairing = false;
function modal(p) {
  pairing = p;
  $('#modalTitle').textContent = p ? '무선 페어링' : 'IP로 연결';
  $('#codeLabel').classList.toggle('inactive', !p);
  $('#endpoint').value = '';
  $('#code').value = '';
  $('#result').textContent = '';
  $('#modal').showModal();
}
$('#connect').onclick = () => modal(false);
$('#pair').onclick = () => modal(true);
$('#submit').onclick = async () => {
  try {
    const r = pairing
      ? await api.pair($('#endpoint').value, $('#code').value)
      : await api.connectIp($('#endpoint').value);
    $('#result').textContent = r.out || '결과가 없습니다';
  } catch (e) {
    $('#result').textContent = e.message;
  }
};
api.onState(update);
api.onLog(log);
Promise.all([api.getState(), api.getLogs()]).then(([s, logs]) => {
  update(s);
  logs.forEach(log);
});
