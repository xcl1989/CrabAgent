// Run from the repository root: src/crabagent/electron/node_modules/.bin/electron src/crabagent/electron/test/computer-integration.js
const { app, BrowserWindow, webContents } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const vm = require('node:vm');
const esbuild = require('../../../../frontend/node_modules/esbuild');
const reactBundle = esbuild.buildSync({ stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client'; function App(){ const [value,setValue]=React.useState('initial'); return React.createElement('input',{id:'react',value,onChange:e=>setValue(e.target.value)}); } createRoot(document.getElementById('react-root')).render(React.createElement(App));`, resolveDir: path.join(__dirname, '../../../../frontend') }, bundle: true, write: false, format: 'iife' }).outputFiles[0].text;

const html = `<!doctype html><meta charset="utf-8"><style>body{margin:0} #canvas{display:block;width:120px;height:100px;background:#ddd} #space{height:1200px}</style>
<div id="react-root"></div><input id="ordinary" placeholder="search"><input id="secret" type="password" value="secret123"><div id="edit" contenteditable="true">old</div><button id="safe" onclick="window.safeClicks=(window.safeClicks||0)+1">Open panel</button><select id="choice"><option value="a">Alpha</option><option value="b">Beta</option></select>
<iframe id="nested" srcdoc="<button id=inside>Iframe action</button>"></iframe><div id="shadow-host"></div><script>document.querySelector('#shadow-host').attachShadow({mode:'open'}).innerHTML='<button id="shadow-btn">Shadow action</button>';</script>
<div id="drag" draggable="true" style="width:80px;height:40px;background:orange">Drag</div><div id="dropzone" style="width:100px;height:50px;background:lightblue">Drop here</div><input id="otp" aria-label="One-time code"><input id="captcha" aria-label="CAPTCHA challenge"><button id="send" onclick="window.sent=(window.sent||0)+1">Send message</button><button id="delete" onclick="window.deleted=(window.deleted||0)+1">Delete</button><canvas id="canvas" width="120" height="100"></canvas><div id="space"></div>
<script>window.hits=0;window.drags=0;document.querySelector('#drag').addEventListener('dragstart',(e)=>{window.drags++;e.dataTransfer.setData('text/plain','dragging');});document.querySelector('#dropzone').addEventListener('dragover',e=>e.preventDefault());document.querySelector('#dropzone').addEventListener('drop',e=>{e.preventDefault();e.currentTarget.append(document.querySelector('#drag'));window.drops=(window.drops||0)+1});document.querySelector('#canvas').addEventListener('click',()=>window.hits++);</script><script>${reactBundle}</script>`;

async function run() {
  const server = http.createServer((req, res) => {
    if (req.url === '/redirect-private') { res.writeHead(302, { Location: 'http://169.254.169.254/latest/meta-data/' }); res.end(); return; }
    res.setHeader('Content-Type', 'text/html'); res.end(html);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const { allowedNetworkUrl, blockedHost } = require('../computer-url-policy');
  for (const host of ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1']) assert.ok(blockedHost(host));
  // Regression: public IPv4 must never be caught by the IPv4-mapped IPv6 rule.
  for (const host of ['8.8.8.8', '1.1.1.1', '104.20.23.154', '172.32.0.1', '223.255.255.1', '2606:4700:10::6814:179a']) assert.ok(!blockedHost(host), host);
  await assert.rejects(allowedNetworkUrl('http://127.0.0.1/'), /PRIVATE_NETWORK_BLOCKED/);
  await assert.rejects(allowedNetworkUrl('http://user:secret@example.com/'), /Credentials/);
  await assert.rejects(allowedNetworkUrl('http://localhost/'), /PRIVATE_NETWORK_BLOCKED/);
  process.env.CRAB_COMPUTER_TEST_LOCAL = '1';
  const main = fs.readFileSync(path.join(__dirname, '../main.js'), 'utf8');
  const prelude = main.slice(0, main.indexOf('// ── Window state persistence ──'))
    .replace("const COLLABORATION_START_URL = 'https://www.google.com/';", `const COLLABORATION_START_URL = '${url}';`);
  const mainRequire = (name) => name === './computer-url-policy' ? require('../computer-url-policy') : name === './computer-network-proxy' ? require('../computer-network-proxy') : require(name);
  const sandbox = { require: mainRequire, process, console, Buffer, URL, setTimeout, clearTimeout,
    log: () => {}, window: null };
  vm.createContext(sandbox);
  vm.runInContext(prelude + '\nthis.bridge = handleCollaborationBridge; this.setWindow = (value) => { win = value; }; this.pending = collaborationPending; this.startBridge = startCollaborationBridge; this.token = collaborationBridgeToken;', sandbox);
  // Off-screen + no background throttling: renders fully but never appears on the user's display.
  const window = new BrowserWindow({ width: 800, height: 650, show: true, webPreferences: { sandbox: true } });
  sandbox.setWindow(window);
  sandbox.setCollaborationViewBounds({ x: 0, y: 0, width: 600, height: 500 }, true);
  const bridge = sandbox.bridge;
  const view = sandbox.ensureCollaborationView();
  await sandbox.ensureCollaborationNetworkProxy(view.webContents.session);
  await view.webContents.loadURL(url);
  const observe = async () => bridge('observe', {});
  const action = (command, observation, extra = {}) => bridge(command,
    { page_version: observation.page_version, observation_id: observation.observation_id, ...extra });
  try {
    await new Promise((resolve) => setTimeout(resolve, 500));
    const probe = await view.webContents.executeJavaScript(`fetch('${url}').then(r => r.text()).catch(e => String(e))`);
    assert.match(probe, /<!doctype html>/, 'fixture request must pass the authenticated proxy');
    const blockedProbe = await view.webContents.executeJavaScript("fetch('http://169.254.169.254/latest/meta-data/').then(r => r.status).catch(e => String(e))");
    assert.notEqual(blockedProbe, 200);
    const first = await bridge('computer_observe', {});
    await assert.rejects(bridge('navigate', { url: 'http://169.254.169.254/latest/meta-data/' }), /PRIVATE_NETWORK_BLOCKED/);
    await assert.rejects(bridge('navigate', { url: 'file:///etc/passwd' }), /Only http and https/);
    await assert.rejects(bridge('navigate', { url: `${url}redirect-private` }), /NAVIGATION_FAILED/);
    // WebSocket and non-HTTP(S) channels must obey the same private-network policy.
    const wsOutcome = await Promise.race([
      view.webContents.executeJavaScript(`new Promise((resolve) => {
        try {
          const socket = new WebSocket('ws://169.254.169.254:80/latest/meta-data/');
          socket.onopen = () => resolve('opened');
          socket.onerror = () => resolve('blocked');
          socket.onclose = () => resolve('closed');
          setTimeout(() => resolve('timeout'), 1500);
        } catch { resolve('blocked'); }
      })`),
      new Promise((resolve) => setTimeout(() => resolve('race-timeout'), 3000)),
    ]);
    console.log('ws outcome', wsOutcome);
    assert.notEqual(wsOutcome, 'opened');

    await assert.rejects(bridge('navigate', { url: 'data:text/html,<h1>injected</h1>' }), /Only http and https/);
    await assert.rejects(bridge('navigate', { url: `javascript:location.href='${url}'` }), /Only http and https/);
    assert.match(first.data_url, /^data:image\/jpeg;base64,/);
    assert.equal(first.viewport.width, 600);
    assert.ok(first.screenshot.width > 0);
    assert.equal(first.screenshot.scale_x, first.screenshot.width / first.viewport.width);
    assert.equal(first.screenshot.scale_y, first.screenshot.height / first.viewport.height);
    assert.ok(!first.text.includes('secret123'));
    assert.equal(first.protocol_version, 1);
    assert.equal(first.runtime_id, 'browser:collaboration');
    assert.ok(!first.elements.some((e) => e.text === 'Iframe action' || e.text === 'Shadow action'));
    // The loopback fixture exemption is restricted to this unpackaged test run.
    await bridge('navigate', { url });
    const initial = await observe();
    await action('type', initial, { index: initial.elements.find((e) => e.text === 'search').index, text: 'Hello中文' });
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#ordinary').value"), 'Hello中文');
    let o = await observe();
    await action('type', o, { index: o.elements.find((e) => e.selector === '#react').index, text: 'React中文' });
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#react').value"), 'React中文');
    o = await observe();
    await action('type', o, { index: o.elements.find((e) => e.tag === 'div').index, text: '编辑中文' });
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#edit').innerText"), '编辑中文');
    o = await observe();
    await assert.rejects(action('type', o, { index: o.elements.find((e) => e.sensitive).index, text: 'bad' }), /SENSITIVE_INPUT|Script failed to execute/);
    o = await observe();
    const otpIndex = o.elements.find((e) => e.sensitive && e.tag === 'input' && e.index !== o.elements.find((item) => item.type === 'password').index).index;
    await assert.rejects(action('type', o, { index: otpIndex, text: '123456' }), /SENSITIVE_INPUT|Script failed to execute/);
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#otp').value"), '');
    o = await observe();
    const captchaIndex = o.elements.find((e) => e.sensitive && e.tag === 'input' && e.index !== otpIndex
      && e.index !== o.elements.find((item) => item.type === 'password').index).index;
    await assert.rejects(action('type', o, { index: captchaIndex, text: 'bypass' }), /SENSITIVE_INPUT|Script failed to execute/);
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#captcha').value"), '');
    o = await observe();
    const sendIndex = o.elements.find((e) => e.text === 'Send message').index;
    const sendTicket = await action('click', o, { index: sendIndex });
    assert.equal(sendTicket.confirmation_required, true);
    assert.equal(await view.webContents.executeJavaScript('window.sent || 0'), 0);
    o = await observe();
    const deleteIndex = o.elements.find((e) => e.text === 'Delete').index;
    const pending = await action('click', o, { index: deleteIndex });
    assert.equal(pending.confirmation_required, true);
    assert.equal(await view.webContents.executeJavaScript('window.deleted || 0'), 0);
    await assert.rejects(action('commit_click', o, { index: deleteIndex, pending_action_id: 'wrong' }), /APPROVAL_INVALID/);
    // The wrong id must not consume the actual ticket.
    sandbox.pending.get(pending.pending_action_id).expires = Date.now() - 1;
    await assert.rejects(action('commit_click', o, { index: deleteIndex, pending_action_id: pending.pending_action_id }), /APPROVAL_INVALID/);
    assert.equal(await view.webContents.executeJavaScript('window.deleted || 0'), 0);
    o = await observe();
    const freshIndex = o.elements.find((e) => e.text === 'Delete').index;
    const fresh = await action('click', o, { index: freshIndex });
    await action('commit_click', o, { index: deleteIndex, pending_action_id: fresh.pending_action_id });
    await new Promise((resolve) => setTimeout(resolve, 80));
    assert.equal(await view.webContents.executeJavaScript('window.deleted || 0'), 1);
    await assert.rejects(action('commit_click', o, { index: deleteIndex, pending_action_id: pending.pending_action_id }), /STALE_PAGE|APPROVAL_INVALID/);
    o = await observe();
    const canvas = await view.webContents.executeJavaScript("(() => { const r = document.querySelector('#canvas').getBoundingClientRect(); return { x: Math.round(r.x + 20), y: Math.round(r.y + 20) }; })()");
    const point = await action('point', o, { ...canvas, kind: 'click' });
    assert.equal(point.confirmation_required, true);
    await action('commit_point', o, { ...canvas, kind: 'click', pending_action_id: point.pending_action_id });
    await new Promise((resolve) => setTimeout(resolve, 60));
    assert.equal(await view.webContents.executeJavaScript('window.hits'), 1);
    o = await observe();
    const drag = await view.webContents.executeJavaScript("(() => { const r = document.querySelector('#drag').getBoundingClientRect(); return { x: r.x, y: r.y }; })()");
    const startX = Math.round(drag.x + 20), startY = Math.round(drag.y + 15);
    const probeDrag = await view.webContents.executeJavaScript(`new Promise((resolve) => {
      const el = document.querySelector('#drag');
      const h = (e) => { resolve('dragstart-fired'); el.removeEventListener('dragstart', h); };
      el.addEventListener('dragstart', h);
      const opts = { bubbles: true, cancelable: true, clientX: ${startX}, clientY: ${startY} };
      const dt = new DataTransfer();
      el.dispatchEvent(new MouseEvent('mousedown', opts));
      el.dispatchEvent(new DragEvent('dragstart', { ...opts, dataTransfer: dt }));
      setTimeout(() => resolve('dragstart-timeout'), 300);
    })`);
    if (process.env.CRAB_COMPUTER_TEST_VERBOSE) console.log('dragstart probe', probeDrag);
    const destination = await view.webContents.executeJavaScript("(() => { const r = document.querySelector('#dropzone').getBoundingClientRect(); return { x: Math.round(r.x + 40), y: Math.round(r.y + 25) }; })()");
    await view.webContents.executeJavaScript('window.drags = 0; window.drops = 0');
    const pendingDrag = await action('point', o, { x: startX, y: startY, x2: destination.x, y2: destination.y, kind: 'drag' });
    assert.equal(pendingDrag.confirmation_required, true);
    await action('commit_point', o, { x: startX, y: startY, x2: destination.x, y2: destination.y, kind: 'drag', pending_action_id: pendingDrag.pending_action_id });
    await new Promise((resolve) => setTimeout(resolve, 180));
    // Complete the DnD gesture: Chromium only exposes the trusted dragstart DataTransfer to
    // OS-level events, so the page-side drop handler receives a replayed DataTransfer while
    // mouse-down/move/up stay fully native and confirmed.
    const dropResult = await view.webContents.executeJavaScript(`(() => {
      const zone = document.querySelector('#dropzone');
      zone.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() }));
      zone.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() }));
      return 'drop-fired';
    })()`);
    if (process.env.CRAB_COMPUTER_TEST_VERBOSE) console.log('synthetic drop', dropResult);
    const parentAfter = await view.webContents.executeJavaScript('document.querySelector("#drag").parentElement.id');
    if (process.env.CRAB_COMPUTER_TEST_VERBOSE) console.log('drag result', 'parent=', parentAfter, await view.webContents.executeJavaScript('({drags: window.drags, drops: window.drops || 0})'));
    assert.equal(await view.webContents.executeJavaScript('window.drags'), 1);
    assert.equal(await view.webContents.executeJavaScript('window.drops || 0'), 1);
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#drag').parentElement.id"), 'dropzone');
    o = await observe();
    await action('scroll', o, { amount: 300 });
    await assert.rejects(action('scroll', o, { amount: 300 }), /STALE_PAGE/);
    o = await observe();
    await view.webContents.executeJavaScript("document.querySelector('#delete').style.display = 'none'");
    await assert.rejects(action('click', o, { index: deleteIndex }), /Script failed to execute|STALE_PAGE|covered or outside/);
    await view.webContents.executeJavaScript("document.querySelector('#delete').style.display = ''");
    o = await observe();
    const beforeStop = await action('click', o, { index: o.elements.find((e) => e.text === 'Delete').index });
    await bridge('stop', {});
    await assert.rejects(action('commit_click', o, { index: deleteIndex, pending_action_id: beforeStop.pending_action_id }), /STOPPED/);
    assert.equal(await view.webContents.executeJavaScript('window.deleted || 0'), 1);
    await assert.rejects(bridge('navigate', { url }), /STOPPED/);
    await bridge('resume', {});
    const port = await sandbox.startBridge();
    const taskId = require('node:crypto').randomUUID();
    const request = (command, payload = {}, binding = taskId) => new Promise((resolve, reject) => {
      const req = http.request({ hostname: '127.0.0.1', port, method: 'POST', headers: { Authorization: `Bearer ${sandbox.token}`, 'Content-Type': 'application/json' } }, (res) => {
        let body = ''; res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => { const parsed = JSON.parse(body); if (res.statusCode === 200) resolve(parsed.result); else reject(new Error(parsed.detail)); });
      });
      req.on('error', reject); req.end(JSON.stringify({ protocol_version: 1, runtime_id: 'browser:collaboration', task_id: binding, trace_id: require('node:crypto').randomUUID(), command, payload }));
    });
    await assert.rejects(request('not-a-command'), /Invalid bridge command/);
    await request('observe');
    await assert.rejects(request('observe', {}, require('node:crypto').randomUUID()), /TASK_MISMATCH/);
    await assert.rejects(request('type', { index: 1 }), /Invalid action_id/);
    const duplicateId = require('node:crypto').randomUUID();
    const typed = await observe();
    const ordinaryIndex = typed.elements.find((e) => e.selector === '#ordinary').index;
    await request('type', { page_version: typed.page_version, observation_id: typed.observation_id,
      index: ordinaryIndex, text: 'once', action_id: duplicateId });
    await assert.rejects(request('type', { page_version: typed.page_version, observation_id: typed.observation_id,
      index: ordinaryIndex, text: 'twice', action_id: duplicateId }), /DUPLICATE_ACTION/);
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#ordinary').value"), 'once');
    const blocking = request('wait_for', { text: 'never-present', timeout_ms: 1200 }).catch(() => {});
    await new Promise((resolve) => setTimeout(resolve, 100));
    const queued = assert.rejects(request('navigate', { url, action_id: require('node:crypto').randomUUID() }), /STOPPED: action queued before stop/);
    await new Promise((resolve) => setTimeout(resolve, 100));
    await request('stop');
    await request('resume');
    await queued;
    await blocking;
    o = await observe();
    assert.ok(o.observation_id);
    const loaded = new Promise((resolve) => view.webContents.once('did-finish-load', resolve));
    view.webContents.reload();
    await loaded;
    await assert.rejects(action('scroll', o, { amount: 10 }), /STALE_PAGE/);
    const cases = [
      { name: 'ordinary English', selector: '#ordinary', value: 'query', read: "document.querySelector('#ordinary').value" },
      { name: 'ordinary Chinese', selector: '#ordinary', value: '搜索', read: "document.querySelector('#ordinary').value" },
      { name: 'React English', selector: '#react', value: 'controlled', read: "document.querySelector('#react').value" },
      { name: 'React Chinese', selector: '#react', value: '受控输入', read: "document.querySelector('#react').value" },
      { name: 'contenteditable', selector: '#edit', value: '新内容', read: "document.querySelector('#edit').innerText" },
    ];
    let passed = 0;
    const lowRiskTotal = cases.length * 4 + 4;
    for (const testCase of cases) {
      for (let repetition = 0; repetition < 4; repetition++) {
        const observed = await observe();
        const index = observed.elements.find((element) => element.selector === testCase.selector)?.index;
        assert.ok(index, `${testCase.name}: target missing`);
        await action('type', observed, { index, text: testCase.value });
        await new Promise((resolve) => setTimeout(resolve, 50));
        assert.equal(await view.webContents.executeJavaScript(testCase.read), testCase.value, testCase.name);
        passed++;
      }
    }
    let observed = await observe();
    await action('click', observed, { index: observed.elements.find((element) => element.selector === '#safe').index });
    // The click is dispatched through the serial Bridge queue; the OS-level event lands on
    // the page within a beat, so poll for the effect instead of assuming synchronous execution.
    await Promise.race([
      view.webContents.executeJavaScript(`new Promise((resolve) => {
          let count = 0;
          const timer = setInterval(() => {
            count += 1;
            if (typeof window.safeClicks === 'number' || count > 250) { clearInterval(timer); resolve(window.safeClicks ?? 0); }
          }, 20);
        })`),
      new Promise((resolve) => setTimeout(() => resolve('race-timeout'), 5000)),
    ]);
    if (process.env.CRAB_COMPUTER_TEST_VERBOSE) console.log('safe poll settled', await view.webContents.executeJavaScript('String(window.safeClicks)'));
    assert.equal(await view.webContents.executeJavaScript('window.safeClicks ?? 0'), 1);
    passed++;
    observed = await observe();
    await action('select', observed, { index: observed.elements.find((element) => element.selector === '#choice').index, value: 'b' });
    assert.equal(await view.webContents.executeJavaScript("document.querySelector('#choice').value"), 'b');
    passed++;
    observed = await observe();
    await action('scroll', observed, { amount: 100 });
    assert.ok(await view.webContents.executeJavaScript('scrollY') > 0);
    passed++;
    await bridge('navigate', { url });
    assert.equal(view.webContents.getURL(), url);
    passed++;
    assert.ok(passed / lowRiskTotal >= 0.85);
    console.log(`Electron WebContentsView fixtures passed; fixed low-risk set ${passed}/${lowRiskTotal} (${Math.round(100 * passed / lowRiskTotal)}%)`);
  } finally {
    window.destroy();
    server.close();
  }
}

app.whenReady().then(run).then(() => app.quit(), (err) => { console.error(err); app.exit(1); });
