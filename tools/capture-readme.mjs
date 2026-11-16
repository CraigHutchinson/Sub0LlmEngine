// Screen captures of the tuning page for the README: headless Edge/Chrome over the DevTools protocol, no packages.
//
//   node tools/capture-readme.mjs [--url http://127.0.0.1:8781/] [--out docs/images] [--dark]
//
// Needs the tuning server running (python -m sub0llmengine serve). Everything stays on this machine.
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, mkdtempSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt; };
const URL_ = arg('--url', 'http://127.0.0.1:8781/'), OUT = arg('--out', 'docs/images'), DARK = process.argv.includes('--dark');
const PORT = 9333, W = 1440, H = 1000, SCALE = 2;
const BROWSERS = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/microsoft-edge'];
const exe = BROWSERS.find(existsSync);
if (!exe) throw new Error('no Edge or Chrome found');

const browser = spawn(exe, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'cap-'))}`,
  `--window-size=${W},${H}`, '--no-first-run', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));

let target;
for (let i = 0; i < 50 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find(t => t.type === 'page'); } catch { await sleep(200); }
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let id = 0; const pending = new Map();
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, m => m.error ? rej(new Error(method + ': ' + m.error.message)) : res(m.result)); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async expr => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result.value;

await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: SCALE, mobile: false });
await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: DARK ? 'dark' : 'light' }] });
await send('Page.enable');
await send('Page.navigate', { url: URL_ });
for (let i = 0; i < 60; i++) {  // wait for history, config and the axes definition to arrive and render
  if (await js(`!!document.querySelector('#preferenceTriangle .region-label') && !/reading/.test(document.querySelector('#axesSummary').textContent)`)) break;
  await sleep(500);
}
await sleep(800);
mkdirSync(OUT, { recursive: true });

// Capture the union of the given elements' boxes (page coordinates), with a margin.
async function shot(name, selectors, setup = '', pad = 12) {
  if (setup) { await js(`(async () => { ${setup} })()`); await sleep(900); }
  const box = await js(`(() => { const rs = ${JSON.stringify(selectors)}.map(s => document.querySelector(s)).filter(Boolean).map(e => e.getBoundingClientRect());
    if (!rs.length) return null; const x = Math.min(...rs.map(r => r.left)), y = Math.min(...rs.map(r => r.top)), r = Math.max(...rs.map(r => r.right)), b = Math.max(...rs.map(r => r.bottom));
    return {x: x + scrollX, y: y + scrollY, w: r - x, h: b - y}; })()`);
  if (!box) { console.log('skipped', name, '(not found)'); return; }
  const clip = { x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: box.w + 2 * pad, height: box.h + 2 * pad, scale: 1 };
  const { data } = await send('Page.captureScreenshot', { format: 'png', clip, captureBeyondViewport: true });
  writeFileSync(join(OUT, name + '.png'), Buffer.from(data, 'base64'));
  console.log('wrote', join(OUT, name + '.png'), Math.round(clip.width * SCALE) + 'x' + Math.round(clip.height * SCALE));
}

await shot('runtime-explorer', ['header', '.statusbar', '[data-view="runtime"] h2', '.hero']);
await shot('decision-pyramid', ['.tri-stage', '#triangleLegend']);
await shot('controls', ['.tri-controls']);
await shot('pyramid-face-on', ['.tri-stage'], `setFace(2); await new Promise(r => setTimeout(r, 500)); document.querySelector('[data-cam=flat]').click();`);
await shot('engine-knobs', ['#engineAxes'], `setFace(3); document.querySelector('[data-cam=tilt]').click(); document.querySelector('#engineAxes').open = true;`);
await shot('frontier', ['.frontier .controls', '#frontierPlot', '#frontierLegend'], `document.querySelector('#engineAxes').open = false;`);
await shot('benchmark-map', ['[data-view="map"].panel'], `document.querySelector('[data-tab="map"]').click();`);
await shot('run-history', ['[data-view="history"].panel'], `document.querySelector('[data-tab="history"]').click();`);

ws.close(); browser.kill();
