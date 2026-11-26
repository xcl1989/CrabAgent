// Run headless (no visible window, isolated profile):
//   CRAB_APP_USER_DATA_DIR=/tmp/crab-regress-profile src/crabagent/electron/node_modules/.bin/electron src/crabagent/electron/test/computer-stale-regression.js
// Regression for the "observe the page again" loop on heavy SPA sites: background
// title/hash/subresource activity must not invalidate an observation, while a real
// navigation still must.
// Headless-ish regression: SPA background activity must not invalidate observations.
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs'); const path = require('node:path'); const vm = require('node:vm'); const http = require('node:http');
const assert = require('node:assert/strict');
const html = `<!doctype html><meta charset="utf-8"><input id="from" placeholder="出发机场"><div style="height:2000px"></div>`;
async function run() {
  const server = http.createServer((req, res) => {
    if (req.url.startsWith('/pixel.gif')) { res.writeHead(200, {'Content-Type':'image/gif'}); res.end(Buffer.from('R0lGODlhAQABAAAAACw=','base64')); return; }
    res.setHeader('Content-Type', 'text/html'); res.end(html);
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const main = fs.readFileSync(path.join(__dirname, '../main.js'), 'utf8');
  const prelude = main.slice(0, main.indexOf('// ── Window state persistence ──'))
    .replace("const COLLABORATION_START_URL = 'https://www.google.com/';", `const COLLABORATION_START_URL = '${url}';`);
  const mainRequire = (n) => n.startsWith('./') ? require(path.join(__dirname, '..', n)) : require(n);
  process.env.CRAB_APP_DIAG = '1';
  const logs = [];
  const sandbox = { require: mainRequire, process, console, Buffer, URL, AbortController, performance, setTimeout, clearTimeout,
    __dirname: path.join(__dirname, '..'), log: (m) => logs.push(String(m)), window: null };
  vm.createContext(sandbox);
  vm.runInContext(prelude + `\nlocalPreviewPolicy.grant('${url}');` + '\nthis.bridge = handleCollaborationBridge; this.setWindow = (v) => { win = v; };', sandbox);
  const window = new BrowserWindow({ width: 1200, height: 900, show: false, webPreferences: { sandbox: true, backgroundThrottling: false, paintWhenInitiallyHidden: true } });
  sandbox.setWindow(window);
  const bridge = sandbox.bridge;
  const view = sandbox.ensureCollaborationView();
  await sandbox.ensureCollaborationNetworkProxy(view.webContents.session);
  await view.webContents.loadURL(url);
  await new Promise((r) => setTimeout(r, 400));
  const out = {};
  // 1. text-only observe must work even without a screenshot surface
  const o1 = await bridge('observe', {});
  const idx = o1.elements.find((e) => e.text === '出发机场').index;
  // 2. background SPA noise (title, replaceState, image fetches) must not bump page_version
  const vBefore = (await bridge('status', {})).page_version;
  await view.webContents.executeJavaScript(`new Promise((res) => { let n = 0; const tick = () => { document.title = 't' + (++n); history.replaceState(null, '', '#/s' + n); new Image().src = '/pixel.gif?' + n; if (n < 3) setTimeout(tick, 40); else setTimeout(res, 200); }; tick(); })`, true);
  const vAfter = (await bridge('status', {})).page_version;
  out.spaNoiseBumpedVersion = vAfter - vBefore;
  // 3. acting on the pre-noise observation must succeed
  try {
    await bridge('type', { page_version: o1.page_version, observation_id: o1.observation_id, index: idx, text: '北京' });
    out.typeAfterNoise = 'ok';
  } catch (e) { out.typeAfterNoise = e.message; }
  // 4. a real navigation must still invalidate
  const o2 = await bridge('observe', {});
  await view.webContents.loadURL(url + '?nav=1');
  await new Promise((r) => setTimeout(r, 300));
  try {
    await bridge('type', { page_version: o2.page_version, observation_id: o2.observation_id, index: idx, text: 'x' });
    out.realNavigation = 'NOT-STALE (bug)';
  } catch (e) { out.realNavigation = e.message.includes('STALE') ? 'stale-ok' : e.message; }
  out.invalidates = logs.filter((l) => l.includes('invalidate reason=')).map((l) => l.replace(/.*reason=/, 'reason='));
  console.log(JSON.stringify(out, null, 2));
  assert.equal(out.spaNoiseBumpedVersion, 0, 'SPA background noise must not bump page_version');
  assert.equal(out.typeAfterNoise, 'ok');
  assert.equal(out.realNavigation, 'stale-ok');
  console.log('PASS stale-regression');
  app.exit(0);
}
app.whenReady().then(run).catch((e) => { console.error(e); app.exit(1); });
