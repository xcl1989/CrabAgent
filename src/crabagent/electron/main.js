const { app, BrowserWindow, WebContentsView, Tray, Menu, nativeImage, ipcMain } = require('electron');
const { spawn, execSync, exec } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const PORT = 5210;
const BACKEND_URL = `http://127.0.0.1:${PORT}`;
const isMac = process.platform === 'darwin';
const isWin = process.platform === 'win32';

let python = null;
let win = null;
let petWin = null;
let petDrag = null;
let petDragTimer = null;
let petLastX = null;
let petStateSaveTimer = null;
let tray = null;
let forceQuit = false;
let petQuietUntil = 0;
let authToken = null;
let collaborationView = null;
let collaborationBridge = null;
let collaborationBridgePort = null;
let collaborationPageVersion = 0;
const collaborationBridgeToken = require('crypto').randomBytes(32).toString('hex');

const COLLABORATION_START_URL = 'https://www.google.com/';

function normalizeBrowserUrl(rawUrl) {
  const value = String(rawUrl || '').trim();
  if (!value) return COLLABORATION_START_URL;
  const candidate = /^[a-z][a-z\d+.-]*:/i.test(value) ? value : `https://${value}`;
  const parsed = new URL(candidate);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Only http and https websites can be opened here.');
  }
  return parsed.toString();
}

function sendCollaborationBrowserState() {
  if (!win || win.isDestroyed() || !collaborationView) return;
  const contents = collaborationView.webContents;
  win.webContents.send('collaboration-browser-state', {
    url: contents.getURL(),
    title: contents.getTitle(),
    canGoBack: contents.canGoBack(),
    canGoForward: contents.canGoForward(),
    loading: contents.isLoading(),
  });
}

function ensureCollaborationView() {
  if (collaborationView && !collaborationView.webContents.isDestroyed()) return collaborationView;
  collaborationView = new WebContentsView({
    webPreferences: {
      partition: 'persist:crabagent-collaboration',
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  collaborationView.webContents.setWindowOpenHandler(({ url }) => {
    try {
      collaborationView.webContents.loadURL(normalizeBrowserUrl(url));
    } catch (error) {
      log(`Blocked collaboration popup: ${error.message}`);
    }
    return { action: 'deny' };
  });
  collaborationView.webContents.on('will-navigate', (event, url) => {
    try {
      normalizeBrowserUrl(url);
    } catch {
      event.preventDefault();
    }
  });
  for (const eventName of ['did-navigate', 'did-navigate-in-page', 'did-start-loading', 'did-stop-loading', 'page-title-updated']) {
    collaborationView.webContents.on(eventName, () => {
      collaborationPageVersion += 1;
      sendCollaborationBrowserState();
    });
  }
  collaborationView.webContents.loadURL(COLLABORATION_START_URL).catch((error) => {
    log(`Collaboration browser initial navigation failed: ${error.message}`);
  });
  return collaborationView;
}

function setCollaborationViewBounds(bounds, visible) {
  if (!win || win.isDestroyed()) {
    log('[CollabView] setBounds skipped: win not available');
    return false;
  }
  if (!visible) {
    log('[CollabView] hide requested');
    if (collaborationView) {
      try {
        if (win.contentView && win.contentView.children && win.contentView.children.includes(collaborationView)) {
          win.contentView.removeChildView(collaborationView);
          log('[CollabView] removed from contentView');
        }
      } catch (e) { log('[CollabView] hide error: ' + e.message); }
      try {
        if (typeof win.removeBrowserView === 'function') win.removeBrowserView(collaborationView);
      } catch {}
    }
    return false;
  }
  if (!bounds || ![bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite)) {
    log('[CollabView] invalid bounds: ' + JSON.stringify(bounds));
    return false;
  }

  const view = ensureCollaborationView();
  const nextBounds = {
    x: Math.max(0, Math.round(bounds.x)),
    y: Math.max(0, Math.round(bounds.y)),
    width: Math.max(1, Math.round(bounds.width)),
    height: Math.max(1, Math.round(bounds.height)),
  };
  log('[CollabView] show bounds=' + JSON.stringify(nextBounds));

  // Try contentView API (Electron 30+)
  let added = false;
  try {
    if (win.contentView && typeof win.contentView.addChildView === 'function') {
      const children = win.contentView.children || [];
      if (!children.includes(view)) {
        win.contentView.addChildView(view);
        const types = (win.contentView.children || []).map(function(c) { try { return c.constructor.name; } catch { return '?'; } });
        log('[CollabView] addChildView OK, children=' + (win.contentView.children || []).length + ', types=' + JSON.stringify(types));
      }
      added = true;
    }
  } catch (e) {
    log('[CollabView] addChildView error: ' + e.message);
  }

  // Fallback: setBrowserView
  if (!added) {
    try {
      win.setBrowserView(view);
      log('[CollabView] setBrowserView fallback OK');
      added = true;
    } catch (e) {
      log('[CollabView] setBrowserView error: ' + e.message);
    }
  }

  try {
    view.setBounds(nextBounds);
    log('[CollabView] setBounds OK, actual=' + JSON.stringify(view.getBounds()));
  } catch (e) {
    log('[CollabView] setBounds error: ' + e.message);
  }

  sendCollaborationBrowserState();
  return true;
}


function collaborationBridgeJson(res, status, payload) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(payload));
}

function collaborationSnapshotScript(pageVersion) {
  return `(() => {
    const nodes = document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"]');
    const elements = [];
    let index = 1;
    for (const el of nodes) {
      if (elements.length >= 80) break;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (!rect.width || !rect.height || style.display === 'none' || style.visibility === 'hidden' || el.disabled) continue;
      const type = (el.type || '').toLowerCase();
      const label = String(el.innerText || el.placeholder || el.getAttribute('aria-label') || el.name || '').slice(0, 100);
      const sensitive = el.tagName === 'INPUT' && ['password', 'hidden', 'file'].includes(type);
      const risk = /pay|payment|purchase|order|delete|remove|send|submit|transfer|checkout|付款|支付|下单|删除|发送|提交|转账/i.test(label);
      const selector = el.id ? '#' + CSS.escape(el.id) : '[data-crab-collab="' + index + '"]';
      el.setAttribute('data-crab-collab', String(index));
      elements.push({ index, tag: el.tagName.toLowerCase(), type, text: label, selector, sensitive, risk, fingerprint: [el.tagName, type, el.id, el.name, label].join('|').slice(0, 240) });
      index += 1;
    }
    const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 5000);
    return { page_version: ${pageVersion}, url: location.href, title: document.title, text: bodyText, viewport: { width: innerWidth, height: innerHeight, scrollY }, elements };
  })()`;
}

function requireCurrentPageVersion(payload) {
  const requested = Number(payload.page_version);
  if (!Number.isInteger(requested) || requested !== collaborationPageVersion) {
    const error = new Error('STALE_PAGE: observe the page again before acting');
    error.code = 'STALE_PAGE';
    throw error;
  }
}

function isSensitiveInput(type, label) {
  return ['password', 'hidden', 'file'].includes(type)
    || /password|passcode|otp|verification|cvv|card|银行卡|密码|验证码|校验码|支付/i.test(label);
}

async function handleCollaborationBridge(command, payload) {
  const view = ensureCollaborationView();
  const contents = view.webContents;
  if (command === 'status') return { page_version: collaborationPageVersion, url: contents.getURL(), title: contents.getTitle(), loading: contents.isLoading() };
  if (command === 'navigate') {
    await contents.loadURL(normalizeBrowserUrl(payload.url));
    return { page_version: collaborationPageVersion, url: contents.getURL(), title: contents.getTitle() };
  }
  if (command === 'observe') return contents.executeJavaScript(collaborationSnapshotScript(collaborationPageVersion), true);
  if (command === 'click') {
    requireCurrentPageVersion(payload);
    const index = Number(payload.index);
    if (!Number.isInteger(index) || index < 1 || index > 80) throw new Error('Invalid element index');
    const outcome = await contents.executeJavaScript(`(() => { const el = document.querySelector('[data-crab-collab="${index}"]'); if (!el) throw new Error('Element not found; observe again'); const label = String(el.innerText || el.getAttribute('aria-label') || el.value || '').slice(0, 100); if (/pay|payment|purchase|order|delete|remove|send|submit|transfer|checkout|付款|支付|下单|删除|发送|提交|转账/i.test(label)) return { confirmation_required: true, index: ${index}, label, url: location.href, title: document.title }; el.click(); return { clicked: ${index}, url: location.href, title: document.title }; })()`, true);
    return { ...outcome, page_version: collaborationPageVersion };
  }
  if (command === 'type') {
    requireCurrentPageVersion(payload);
    const index = Number(payload.index);
    const input = String(payload.text || '');
    if (!Number.isInteger(index) || index < 1 || index > 80 || input.length > 10000) throw new Error('Invalid type request');
    const outcome = await contents.executeJavaScript(`(() => { const el = document.querySelector('[data-crab-collab="${index}"]'); if (!el) throw new Error('Element not found; observe again'); const type = String(el.type || '').toLowerCase(); const label = String(el.placeholder || el.getAttribute('aria-label') || el.name || ''); if (${isSensitiveInput.toString()}(type, label)) throw new Error('SENSITIVE_INPUT: AI cannot type into this field'); el.focus(); el.value = ${JSON.stringify(input)}; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return { typed: ${index}, url: location.href, title: document.title }; })()`, true);
    return { ...outcome, page_version: collaborationPageVersion };
  }
  if (command === 'scroll') {
    requireCurrentPageVersion(payload);
    const amount = Math.max(-2000, Math.min(2000, Number(payload.amount) || 600));
    const outcome = await contents.executeJavaScript(`(() => { window.scrollBy(0, ${amount}); return { scrollY: window.scrollY, url: location.href }; })()`, true);
    return { ...outcome, page_version: collaborationPageVersion };
  }
  if (command === 'select') {
    requireCurrentPageVersion(payload);
    const index = Number(payload.index);
    const value = String(payload.value || '');
    if (!Number.isInteger(index) || index < 1 || index > 80 || value.length > 1000) throw new Error('Invalid select request');
    const outcome = await contents.executeJavaScript(`(() => { const el = document.querySelector('[data-crab-collab="${index}"]'); if (!el) throw new Error('Element not found; observe again'); if (el.tagName !== 'SELECT') throw new Error('Element is not a select control'); const option = Array.from(el.options).find((item) => item.value === ${JSON.stringify(value)} || item.text === ${JSON.stringify(value)}); if (!option) throw new Error('Option not found'); el.value = option.value; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return { selected: ${index}, value: option.value, url: location.href, title: document.title }; })()`, true);
    return { ...outcome, page_version: collaborationPageVersion };
  }
  if (command === 'press_key') {
    requireCurrentPageVersion(payload);
    const key = String(payload.key || '');
    if (!/^(Enter|Escape|Tab|ArrowUp|ArrowDown|ArrowLeft|ArrowRight)$/.test(key)) throw new Error('Unsupported key');
    const outcome = await contents.executeJavaScript(`(() => { const el = document.activeElement || document.body; const options = { key: ${JSON.stringify(key)}, bubbles: true, cancelable: true }; el.dispatchEvent(new KeyboardEvent('keydown', options)); el.dispatchEvent(new KeyboardEvent('keyup', options)); return { pressed: ${JSON.stringify(key)}, url: location.href, title: document.title }; })()`, true);
    return { ...outcome, page_version: collaborationPageVersion };
  }
  if (command === 'wait_for') {
    const timeout = Math.max(100, Math.min(30_000, Number(payload.timeout_ms) || 10_000));
    const text = String(payload.text || '').slice(0, 500);
    const urlIncludes = String(payload.url_includes || '').slice(0, 500);
    const started = Date.now();
    while (Date.now() - started < timeout) {
      const matched = await contents.executeJavaScript(`(() => ({ text: ${JSON.stringify(text)} ? document.body?.innerText?.includes(${JSON.stringify(text)}) : false, url: ${JSON.stringify(urlIncludes)} ? location.href.includes(${JSON.stringify(urlIncludes)}) : false, loading: document.readyState !== 'complete' }))()`, true);
      if ((!text || matched.text) && (!urlIncludes || matched.url) && !matched.loading) return { matched: true, page_version: collaborationPageVersion, url: contents.getURL(), title: contents.getTitle() };
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    throw new Error('WAIT_TIMEOUT: requested page condition was not met');
  }
  throw new Error('Unsupported collaboration browser command');
}

async function startCollaborationBridge() {
  if (collaborationBridge && collaborationBridgePort) return collaborationBridgePort;
  collaborationBridge = http.createServer(async (req, res) => {
    if (req.method !== 'POST' || req.headers.authorization !== `Bearer ${collaborationBridgeToken}`) {
      collaborationBridgeJson(res, 401, { detail: 'Unauthorized' });
      return;
    }
    let raw = '';
    req.on('data', (chunk) => { raw += chunk; if (raw.length > 100_000) req.destroy(); });
    req.on('end', async () => {
      try {
        const body = JSON.parse(raw || '{}');
        const result = await handleCollaborationBridge(String(body.command || ''), body.payload || {});
        collaborationBridgeJson(res, 200, { result });
      } catch (error) {
        collaborationBridgeJson(res, 400, { detail: error.message || 'Bridge request failed' });
      }
    });
  });
  await new Promise((resolve, reject) => {
    collaborationBridge.once('error', reject);
    collaborationBridge.listen(0, '127.0.0.1', () => {
      collaborationBridge.off('error', reject);
      resolve();
    });
  });
  const address = collaborationBridge.address();
  if (!address || typeof address === 'string') {
    throw new Error('Collaboration browser bridge failed to bind a local port');
  }
  collaborationBridgePort = address.port;
  log(`Collaboration browser bridge listening on 127.0.0.1:${collaborationBridgePort}`);
  return collaborationBridgePort;
}

// ── Window state persistence ──
const STATE_PATH = path.join(app.getPath('userData'), 'window-state.json');
const PET_STATE_PATH = path.join(app.getPath('userData'), 'pet-window-state.json');

function loadWindowState() {
  try { return JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8')); }
  catch { return {}; }
}

function saveWindowState() {
  if (!win) return;
  try {
    const bounds = win.getBounds();
    const state = { ...bounds, maximized: win.isMaximized() };
    fs.writeFileSync(STATE_PATH, JSON.stringify(state));
  } catch {}
}

function loadPetState() {
  try {
    const state = JSON.parse(fs.readFileSync(PET_STATE_PATH, 'utf-8'));
    if (!Number.isFinite(state.quietUntil) || state.quietUntil <= Date.now()) state.quietUntil = 0;
    return state;
  } catch { return {}; }
}

function savePetState() {
  try {
    const bounds = petWin && !petWin.isDestroyed() ? petWin.getBounds() : {};
    fs.writeFileSync(PET_STATE_PATH, JSON.stringify({ ...bounds, quietUntil: petQuietUntil }));
  } catch {}
}

function setPetQuietMode(minutes) {
  petQuietUntil = minutes ? Date.now() + minutes * 60_000 : 0;
  savePetState();
}

function schedulePetStateSave() {
  if (petStateSaveTimer) clearTimeout(petStateSaveTimer);
  petStateSaveTimer = setTimeout(() => {
    petStateSaveTimer = null;
    savePetState();
  }, 250);
}

// ── Logging ──
function log(msg) {
  console.log(`[CrabAgent] ${msg}`);
  try {
    const logPath = require('path').join(require('os').homedir(), '.crabagent', 'electron.log');
    const line = new Date().toISOString() + ' ' + msg + '\n';
    require('fs').appendFileSync(logPath, line);
  } catch {}
}

// ── Loading screen (shown while backend starts up) ──
const LOADING_HTML = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0d1117; color: #c9d1d9;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 100vh; user-select: none; -webkit-app-region: drag;
  }
  .logo { width: 48px; height: 48px; margin-bottom: 28px; }
  .spinner {
    width: 36px; height: 36px; margin-bottom: 20px;
    border: 3px solid rgba(88,166,255,0.15);
    border-top-color: #58a6ff; border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .title { font-size: 16px; font-weight: 600; color: #e6edf3; margin-bottom: 6px; }
  .subtitle { font-size: 13px; color: #6e7681; }
</style></head>
<body>
  <svg class="logo" viewBox="0 0 48 48" fill="none">
    <path d="M24 4L6 14v20l18 10 18-10V14L24 4z" stroke="#58a6ff" stroke-width="2" fill="rgba(88,166,255,0.08)"/>
    <circle cx="24" cy="24" r="7" fill="#58a6ff"/>
    <path d="M24 17v14M17 24h14" stroke="#0d1117" stroke-width="2"/>
  </svg>
  <div class="spinner"></div>
  <div class="title">CrabAgent</div>
  <div class="subtitle">正在启动，请稍候…</div>
</body></html>`;

// ── Kill existing process on port (cross-platform) ──
function killExistingBackend() {
  try {
    if (isWin) {
      // Windows: use netstat to find PID listening on PORT
      const result = execSync(
        `netstat -aon | findstr :${PORT} | findstr LISTENING`,
        { encoding: 'utf-8', shell: 'cmd.exe', stdio: ['pipe', 'pipe', 'ignore'] }
      );
      const pids = new Set();
      for (const line of result.trim().split('\n')) {
        const parts = line.trim().split(/\s+/);
        const pid = parts[parts.length - 1];
        if (pid && /^\d+$/.test(pid)) pids.add(pid);
      }
      for (const pid of pids) {
        try {
          execSync(`taskkill /PID ${pid} /T /F`, { shell: 'cmd.exe', stdio: 'ignore' });
          log(`Killed existing process ${pid}`);
        } catch {}
      }
      // Brief wait for port release
      if (pids.size > 0) {
        const deadline = Date.now() + 3000;
        while (Date.now() < deadline) {
          try {
            execSync(`netstat -aon | findstr :${PORT} | findstr LISTENING`,
              { shell: 'cmd.exe', stdio: 'ignore' });
          } catch { break; }
        }
      }
    } else {
      // macOS/Linux: use lsof
      const result = execSync(`lsof -ti:${PORT} 2>/dev/null || true`, { encoding: 'utf-8' });
      const pids = result.trim().split('\n').filter(Boolean);
      for (const pid of pids) {
        try { process.kill(Number(pid), 'SIGTERM'); log(`Killed existing process ${pid}`); } catch {}
      }
      if (pids.length > 0) {
        const deadline = Date.now() + 3000;
        while (Date.now() < deadline) {
          try { execSync(`lsof -ti:${PORT} 2>/dev/null`); } catch { break; }
        }
      }
    }
  } catch {}
}

// ── Resolve binary path (cross-platform) ──
function resolvePath(cmd) {
  try {
    if (isWin) {
      return execSync(`where ${cmd} 2>nul`, { encoding: 'utf-8', shell: 'cmd.exe' }).trim().split('\n')[0];
    }
    return execSync(`/bin/bash -l -c 'command -v ${cmd} 2>/dev/null'`, { encoding: 'utf-8' }).trim();
  } catch { return null; }
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, PYTHONUNBUFFERED: '1', CRAB_COLLAB_BROWSER_PORT: String(collaborationBridgePort || ''), CRAB_COLLAB_BROWSER_TOKEN: collaborationBridgeToken };

    // Priority 1: crabagent CLI from PATH (fastest, most reliable)
    const crabagentBin = resolvePath('crabagent');
    if (crabagentBin) {
      log(`Starting system crabagent: ${crabagentBin}`);
      python = spawn(crabagentBin, ['--serve'], { stdio: 'pipe', env });
      python.on('error', (e) => { log(`System crabagent error: ${e.message}`); reject(e); });
      python.on('exit', (c) => log(`System crabagent exited (${c})`));
      python.stdout.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
      python.stderr.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
      return setTimeout(resolve, 500);
    }

    // Priority 2: bundled crabagent-backend binary (self-contained app)
    const backendName = isWin ? 'crabagent-backend.exe' : 'crabagent-backend';

    // onedir mode: binary is inside a directory
    const bundledDir = path.join(process.resourcesPath, 'crabagent-backend');
    const bundledBin = path.join(bundledDir, backendName);
    const bundledBinFlat = path.join(process.resourcesPath, backendName);

    // Check onedir first, then flat onefile
    const actualBin = fs.existsSync(bundledBin) ? bundledBin
                    : fs.existsSync(bundledBinFlat) ? bundledBinFlat
                    : null;

    if (actualBin) {
      log(`Starting bundled backend: ${actualBin}`);
      const spawnOpts = {
        stdio: 'pipe',
        env,
        ...(isWin ? { windowsHide: true } : {}),
      };
      python = spawn(actualBin, ['--serve'], spawnOpts);
      python.on('error', (e) => { log(`Bundled backend error: ${e.message}`); reject(e); });
      python.on('exit', (c) => log(`Bundled backend exited (${c})`));
      python.stdout.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
      python.stderr.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
      return setTimeout(resolve, 500);
    }

    // Priority 3: python3 -m crabagent.cli
    const pythonBin = resolvePath(isWin ? 'python' : 'python3') || (isWin ? 'python' : 'python3');
    log(`Fallback to python3: ${pythonBin}`);
    python = spawn(pythonBin, ['-m', 'crabagent.cli', '--serve'], { stdio: 'pipe', env });
    python.on('error', (e) => { log(`Python backend error: ${e.message}`); reject(e); });
    python.on('exit', (c) => log(`Python backend exited (${c})`));
    python.stdout.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
    python.stderr.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
    setTimeout(resolve, 500);
  });
}

function waitForServer(maxWait = 60000) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    function check() {
      http.get(`${BACKEND_URL}/health`, (r) => { if (r.statusCode === 200) resolve(); else retry(); })
        .on('error', retry);
      function retry() { if (Date.now() - t0 > maxWait) reject(new Error('Timeout')); else setTimeout(check, 500); }
    }
    check();
  });
}

// ── Kill backend process (cross-platform) ──
function killBackend() {
  if (!python) return;
  try {
    if (isWin) {
      // Windows: SIGTERM/SIGKILL don't work, use taskkill on the process tree
      execSync(`taskkill /PID ${python.pid} /T /F`, { shell: 'cmd.exe', stdio: 'ignore' });
      log('Backend killed via taskkill');
    } else {
      python.kill('SIGTERM');
      setTimeout(() => { if (python && !python.killed) python.kill('SIGKILL'); }, 3000);
    }
  } catch (e) {
    log(`Backend kill error: ${e.message}`);
  }
}

// ── Create tray ──
function createTray() {
  // macOS menu bars require a transparent template image, not the opaque app icon.
  const trayFile = isMac ? 'trayTemplate.png' : 'icon.png';
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, trayFile)
    : path.join(__dirname, 'build', trayFile);
  let trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 22, height: 22 });

  if (trayIcon.isEmpty() && !isMac) {
    trayIcon = nativeImage.createFromPath(path.join(__dirname, 'build', 'icon.png')).resize({ width: 22, height: 22 });
  }
  if (isMac && !trayIcon.isEmpty()) trayIcon.setTemplateImage(true);

  tray = new Tray(trayIcon);
  tray.setToolTip('CrabAgent');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示窗口',
      click: () => showWindow(),
      accelerator: 'CmdOrCtrl+Shift+C',
    },
    {
      label: '显示桌宠',
      click: () => showPet(),
    },
    {
      label: '隐藏桌宠',
      click: () => petWin?.hide(),
    },
    { type: 'separator' },
    {
      label: '打开工作目录',
      click: () => {
        const crabagentDir = path.join(app.getPath('home'), '.crabagent');
        if (isWin) {
          exec(`explorer "${crabagentDir}"`);
        } else {
          exec(`open "${crabagentDir}"`);
        }
      },
    },
    { type: 'separator' },
    {
      label: '设置',
      click: () => {
        showWindow();
        win?.webContents.executeJavaScript(
          `window.location.hash = '#/settings'`
        );
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        forceQuit = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);

  // Double-click tray icon to show window
  tray.on('double-click', () => showWindow());
}

// ── Create application menu ──
function createAppMenu() {
  const template = [
    {
      label: 'CrabAgent',
      submenu: [
        {
          label: '关于 CrabAgent',
          click: () => {
            const { dialog } = require('electron');
            dialog.showMessageBox(win, {
              type: 'info',
              title: '关于 CrabAgent',
              message: `CrabAgent v${app.getVersion()}`,
              detail: 'AI 知识工作平台\n需要答案时对话，需要成果时工作。',
            });
          },
        },
        { type: 'separator' },
        {
          label: '设置...',
          accelerator: 'CmdOrCtrl+,',
          click: () => {
            showWindow();
            win?.webContents.executeJavaScript(`window.location.hash = '#/settings'`);
          },
        },
        {
          label: '显示桌宠',
          click: () => showPet(),
        },
        { type: 'separator' },
        {
          label: '退出 CrabAgent',
          accelerator: isMac ? 'Cmd+Q' : 'Ctrl+Q',
          click: () => { forceQuit = true; app.quit(); },
        },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectAll', label: '全选' },
      ],
    },
    {
      label: '窗口',
      submenu: [
        { role: 'minimize', label: '最小化' },
        { role: 'zoom', label: '缩放' },
        { type: 'separator' },
        {
          label: '显示主窗口',
          accelerator: 'CmdOrCtrl+Shift+C',
          click: () => showWindow(),
        },
        {
          label: '显示桌宠',
          click: () => showPet(),
        },
        { type: 'separator' },
        { role: 'front', label: '全部置于顶层' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '开发者工具',
          accelerator: 'CmdOrCtrl+Alt+I',
          click: () => win?.webContents.toggleDevTools(),
        },
        { type: 'separator' },
        {
          label: 'CrabAgent 文档',
          click: () => { require('electron').shell.openExternal('https://github.com/xcl1989/crabagent'); },
        },
      ],
    },
  ];

  // macOS 需要把第一个菜单作为应用菜单
  if (isMac) {
    template.unshift({
      label: app.getName(),
      submenu: [
        { role: 'about', label: '关于 CrabAgent' },
        { type: 'separator' },
        { role: 'services', label: '服务' },
        { type: 'separator' },
        { role: 'hide', label: '隐藏 CrabAgent' },
        { role: 'hideOthers', label: '隐藏其他' },
        { role: 'unhide', label: '显示全部' },
        { type: 'separator' },
        { role: 'quit', label: '退出 CrabAgent' },
      ],
    });
  }

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ── Create main window ──
function createWindow() {
  const saved = loadWindowState();

  win = new BrowserWindow({
    width: saved.width || 1200,
    height: saved.height || 800,
    x: saved.x,
    y: saved.y,
    minWidth: 800,
    minHeight: 600,
    title: 'CrabAgent',
    show: false,  // show after ready
    // On Windows, use a consistent icon
    ...(isWin ? { icon: path.join(__dirname, 'build', 'icon.png') } : {}),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  if (saved.maximized) win.maximize();

  // Load a local loading screen first (instant — no network needed)
  win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(LOADING_HTML));

  // Show window immediately
  win.once('ready-to-show', () => {
    win.show();
  });

  // ── External link handling ─────────────────────────────────────
  // Open external links (http/https) in the system default browser,
  // not in a new Electron window. This prevents the main window from
  // being replaced by external pages.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      require('electron').shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  // Prevent navigation to external URLs in the main window
  win.webContents.on('will-navigate', (event, url) => {
    // Allow only navigation to the local backend
    const allowedPrefixes = ['http://localhost', 'http://127.0.0.1', 'data:text/html', 'file://'];
    if (!allowedPrefixes.some(p => url.startsWith(p))) {
      event.preventDefault();
      require('electron').shell.openExternal(url);
    }
  });

  // A native BrowserView sits above the renderer. Hide it whenever the SPA
  // leaves the collaboration route so it cannot cover another CrabAgent page.
  win.webContents.on('did-navigate-in-page', (_event, url) => {
    if (!url.includes('#/browser')) setCollaborationViewBounds(null, false);
  });

  // Save window state on resize/move
  win.on('resize', saveWindowState);
  win.on('move', saveWindowState);

  // Minimize to tray instead of closing
  win.on('close', (event) => {
    if (!forceQuit) {
      event.preventDefault();
      win.hide();
      return;
    }
    // Clean up
    saveWindowState();
    killBackend();
  });

  win.on('closed', () => {
    collaborationView = null;
    win = null;
  });
}

// ── Desktop pet ──
// It shares the main window's local origin and session, so its React surface can
// consume the existing authenticated global SSE stream without extra credentials.
function primeRendererAuth(target) {
  if (!target || target.isDestroyed() || !authToken) return;
  target.webContents.once('did-finish-load', () => {
    if (!target.webContents.getURL().startsWith(BACKEND_URL)) return;
    const token = JSON.stringify(authToken);
    target.webContents.executeJavaScript(`window.localStorage.setItem('crab_token', ${token})`);
  });
}

function createPetWindow() {
  if (petWin && !petWin.isDestroyed()) return petWin;

  const saved = loadPetState();
  petQuietUntil = saved.quietUntil || 0;
  const display = require('electron').screen.getPrimaryDisplay();
  const workArea = display.workArea;
  const width = 228;
  const height = 320;
  const x = Number.isFinite(saved.x) ? saved.x : workArea.x + workArea.width - width - 24;
  const y = Number.isFinite(saved.y) ? saved.y : workArea.y + workArea.height - height - 36;

  petWin = new BrowserWindow({
    width,
    height,
    x,
    y,
    minWidth: width,
    minHeight: height,
    maxWidth: width,
    maxHeight: 520,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    visibleOnAllWorkspaces: true,
    hasShadow: false,
    // Let the first click through even though this non-activating window is on top.
    acceptFirstMouse: true,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  petWin.setAlwaysOnTop(true, 'floating');
  petWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: false });
  petWin.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  petWin.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(BACKEND_URL)) event.preventDefault();
  });
  primeRendererAuth(petWin);
  petWin.loadURL(`${BACKEND_URL}/?surface=pet`);
  petWin.once('ready-to-show', () => petWin?.showInactive());
  // Window moves can fire at frame rate while dragging; debounce disk persistence.
  petWin.on('move', schedulePetStateSave);
  petWin.on('close', (event) => {
    if (!forceQuit) {
      event.preventDefault();
      petWin?.hide();
    }
  });
  petWin.on('closed', () => {
    petWin = null;
    petDrag = null;
    if (petDragTimer) clearInterval(petDragTimer);
    if (petStateSaveTimer) clearTimeout(petStateSaveTimer);
    petDragTimer = null;
    petStateSaveTimer = null;
  });
  return petWin;
}

function showPet() {
  const pet = createPetWindow();
  if (pet.isMinimized()) pet.restore();
  pet.showInactive();
}

function movePetToCursor() {
  if (!petWin || petWin.isDestroyed() || !petDrag) return;

  try {
    const { screen } = require('electron');
    const point = screen.getCursorScreenPoint();
    const offsetX = Number(petDrag.offsetX);
    const offsetY = Number(petDrag.offsetY);
    if (![point.x, point.y, offsetX, offsetY].every(Number.isFinite)) return;

    const display = screen.getDisplayNearestPoint(point);
    const bounds = display.workArea;
    const [width, height] = petWin.getSize();
    // Keep the whole pet on the active display and avoid invalid coordinates
    // while macOS moves the cursor through a screen edge or a display gap.
    const x = Math.max(bounds.x, Math.min(bounds.x + bounds.width - width, Math.trunc(point.x - offsetX)));
    const y = Math.max(bounds.y, Math.min(bounds.y + bounds.height - height, Math.trunc(point.y - offsetY)));
    if (!Number.isSafeInteger(x) || !Number.isSafeInteger(y)) return;

    // Detect drag direction and notify the renderer for directional animation.
    if (petLastX !== null) {
      const dx = x - petLastX;
      if (Math.abs(dx) > 2) {
        const direction = dx > 0 ? 'running-right' : 'running-left';
        petWin.webContents.send('pet-drag-direction', { direction });
      }
    }
    petLastX = x;

    petWin.setPosition(x, y);
  } catch (error) {
    log(`Pet drag skipped: ${error.message}`);
  }
}

// ── IPC handlers for window control ──
ipcMain.on('window-minimize', () => win?.minimize());
ipcMain.on('window-maximize', () => {
  if (win?.isMaximized()) win.unmaximize(); else win?.maximize();
});
ipcMain.on('window-close', () => win?.close());
ipcMain.handle('window-is-maximized', () => win?.isMaximized() ?? false);
ipcMain.handle('collaboration-browser-layout', (event, bounds, visible) => {
  if (event.sender !== win?.webContents) return false;
  return setCollaborationViewBounds(bounds, Boolean(visible));
});
ipcMain.handle('collaboration-browser-navigate', (event, url) => {
  if (event.sender !== win?.webContents) throw new Error('Unauthorized browser request');
  const target = normalizeBrowserUrl(url);
  const view = ensureCollaborationView();
  log('[CollabView] navigate to ' + target + ' current=' + view.webContents.getURL());
  void view.webContents.loadURL(target).then(() => {
    log('[CollabView] navigate OK, url now=' + view.webContents.getURL());
    view.webContents.focus();
    sendCollaborationBrowserState();
  }).catch((error) => {
    log('[CollabView] navigate FAILED: ' + error.message);
    sendCollaborationBrowserState();
  });
  return { url: target };
});
ipcMain.handle('collaboration-browser-action', async (event, action) => {
  if (event.sender !== win?.webContents) throw new Error('Unauthorized browser request');
  const contents = ensureCollaborationView().webContents;
  if (action === 'back' && contents.canGoBack()) contents.goBack();
  if (action === 'forward' && contents.canGoForward()) contents.goForward();
  if (action === 'reload') contents.reload();
  if (action === 'stop') contents.stop();
  sendCollaborationBrowserState();
});
ipcMain.on('pet-resize', (_event, requestedHeight) => {
  if (!petWin || petWin.isDestroyed() || !Number.isFinite(requestedHeight)) return;

  const [width, currentHeight] = petWin.getSize();
  const nextHeight = Math.max(320, Math.min(Math.ceil(requestedHeight), 520));
  if (nextHeight === currentHeight) return;

  // Preserve the character's screen position while the status bubble grows upward.
  const [x, y] = petWin.getPosition();
  petWin.setBounds({ x, y: y - (nextHeight - currentHeight), width, height: nextHeight });
});
ipcMain.on('pet-drag-start', (_event, { offsetX, offsetY }) => {
  petDrag = { offsetX, offsetY };
  petLastX = null;
  // Render immediate drag feedback; subsequent cursor movement corrects it.
  petWin?.webContents.send('pet-drag-direction', { direction: 'running-right' });
  if (petDragTimer) clearInterval(petDragTimer);
  petDragTimer = setInterval(movePetToCursor, 33);
});
ipcMain.on('pet-drag-move', () => movePetToCursor());
ipcMain.on('pet-drag-end', () => {
  petDrag = null;
  petLastX = null;
  if (petDragTimer) clearInterval(petDragTimer);
  petDragTimer = null;
  savePetState();
  // Notify renderer to restore idle/agent animation after drag.
  petWin?.webContents.send('pet-drag-direction', { direction: null });
});
ipcMain.handle('pet-auth-token', (event) => (
  event.sender === petWin?.webContents ? authToken : null
));
ipcMain.handle('pet-action', (_event, action, sessionId) => {
  if (action === 'open-main') {
    showWindow();
    if (sessionId && win) {
      win.webContents.send('open-session', sessionId);
    }
  }
  if (action === 'hide') petWin?.hide();
  if (action === 'toggle-always-on-top' && petWin) {
    petWin.setAlwaysOnTop(!petWin.isAlwaysOnTop(), 'floating');
    return petWin.isAlwaysOnTop();
  }
  return false;
});

ipcMain.handle('pet-quiet-mode', (_event, minutes) => {
  const duration = Number(minutes);
  if (!Number.isFinite(duration) || duration < 0 || duration > 24 * 60) return false;
  setPetQuietMode(duration);
  return true;
});

ipcMain.handle('pet-quiet-status', () => {
  const remainingMs = Math.max(0, petQuietUntil - Date.now());
  if (!remainingMs && petQuietUntil) setPetQuietMode(0);
  return { active: remainingMs > 0, remainingMs };
});

ipcMain.on('pet-menu', (event) => {
  const menu = Menu.buildFromTemplate([
    { label: '打开 CrabAgent', click: () => showWindow() },
    petQuietUntil > Date.now()
      ? { label: '关闭安静模式', click: () => setPetQuietMode(0) }
      : { label: '安静 1 小时', click: () => setPetQuietMode(60) },
    { type: 'separator' },
    { label: '隐藏桌宠', click: () => petWin?.hide() },
    { label: '退出 CrabAgent', click: () => { forceQuit = true; app.quit(); } },
  ]);
  menu.popup({ window: BrowserWindow.fromWebContents(event.sender) || petWin });
});

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  if (!win.isVisible()) win.show();
  win.focus();
}

// ── Single instance lock ──
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  // Another instance is already running, focus its window
  app.quit();
} else {
  app.on('second-instance', () => {
    showWindow();
  });
}

// ── Helper: auto-login via admin credentials ──
async function autoLogin() {
  try {
    const body = JSON.stringify({ username: 'admin', password: 'xcl1989' });
    const token = await new Promise((resolve, reject) => {
      const req = http.request(`${BACKEND_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      }, (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          try { resolve(JSON.parse(data).access_token); } catch (e) { reject(e); }
        });
      });
      req.on('error', reject);
      req.write(body);
      req.end();
    });
    authToken = String(token);
    primeRendererAuth(win);
    log('Auto-login done');
  } catch (e) {
    log(`Auto-login: ${e.message}`);
  }
}

// ── Clear browser cache to prevent stale assets after update ──
function clearBrowserCache() {
  const dataPath = app.getPath('userData');
  const cacheDirs = ['Cache', 'Code Cache', 'GPUCache'];
  for (const dir of cacheDirs) {
    const p = path.join(dataPath, dir);
    if (fs.existsSync(p)) {
      try { fs.rmSync(p, { recursive: true, force: true }); log(`Cleared cache: ${dir}`); } catch {}
    }
  }
}

// ── App lifecycle ──
app.whenReady().then(async () => {
  killExistingBackend();
  await startCollaborationBridge();

  // Clear browser cache on each launch (prevents stale JS/CSS after updates)
  clearBrowserCache();

  // Show window immediately (blank until backend is ready)
  createAppMenu();
  createWindow();
  createTray();

  // Start backend in background
  await startBackend();
  log('Waiting for backend...');
  await waitForServer();
  log('Backend ready!');

  // Auto-login, then load the real SPA (replaces loading screen)
  await autoLogin();
  if (win) {
    primeRendererAuth(win);
    win.loadURL(BACKEND_URL);
  }
  createPetWindow();

  // macOS: re-show window on dock click
  app.on('activate', () => {
    if (win === null) {
      createWindow();
    } else {
      showWindow();
    }
  });
}).catch((e) => {
  log(`Error: ${e.message}`);
  // Don't quit — window is already visible
});

app.on('window-all-closed', () => {
  // Don't quit on window close (we hide to tray)
  // Only quit when forceQuit is set
});

app.on('before-quit', () => {
  forceQuit = true;
  collaborationBridge?.close();
});
