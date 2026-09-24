const { app, BrowserWindow, WebContentsView, Tray, Menu, nativeImage, ipcMain, session } = require('electron');
const { spawn, execSync, exec } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const crypto = require('crypto');
const { parseBrowserUrl, allowedNetworkUrl } = require('./computer-url-policy');
const { createComputerNetworkProxy, parseProxyResolution } = require('./computer-network-proxy');

const PORT = Number(process.env.CRAB_APP_PORT) || 5210;
const DIAG = process.env.CRAB_APP_DIAG === '1';
if (DIAG) console.log(`[CrabAgent] DIAG BUILD MARKER netproxy-v5 proxychain`);
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
let collaborationNetworkProxy = null;
let collaborationNetworkProxyReady = null;
let collaborationNetworkProxySecret = null;
let collaborationPageVersion = 0;
let collaborationObservation = null;
let collaborationTaskId = null;
let collaborationStopped = false;
let collaborationStopEpoch = 0;
let collaborationActionQueue = Promise.resolve();
const collaborationPending = new Map();
const collaborationActionIds = new Map();
const CONFIRM_TTL_MS = 120_000;
const ACTION_ID_TTL_MS = 15 * 60_000;

function invalidateCollaborationObservation(reason) {
  if (DIAG) log(`invalidate reason=${reason || 'unspecified'} -> page_version=${collaborationPageVersion + 1}`);
  collaborationPageVersion += 1;
  collaborationObservation = null;
  collaborationPending.clear();
}

const collaborationBridgeToken = require('crypto').randomBytes(32).toString('hex');

const COLLABORATION_START_URL = 'https://www.google.com/';

function normalizeBrowserUrl(rawUrl) {
  return parseBrowserUrl(rawUrl || COLLABORATION_START_URL).toString();
}

// Only the local, source-based integration fixture may visit its loopback HTTP server.
const allowLocalFixture = process.env.CRAB_COMPUTER_TEST_LOCAL === '1' && !app.isPackaged;
async function checkedBrowserUrl(rawUrl) {
  return allowedNetworkUrl(normalizeBrowserUrl(rawUrl), { allowLocalFixture });
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
    paused: collaborationStopped,
  });
}

async function ensureCollaborationNetworkProxy(browserSession) {
  if (!collaborationNetworkProxyReady) {
    collaborationNetworkProxyReady = (async () => {
      // Honor the user's system proxy (Clash, V2Ray, corporate proxies, ...). Electron's
      // default session still follows OS settings because only the collaboration session
      // is overridden below. resolveProxy returns e.g. "PROXY 127.0.0.1:7897; DIRECT".
      const systemProxy = async (url) => {
        try {
          const result = await session.defaultSession.resolveProxy(url);
          if (DIAG) log(`resolveProxy(${url}) -> ${JSON.stringify(result)}`);
          const entry = String(result).split(';').map((item) => item.trim()).find((item) => item && !/^DIRECT$/i.test(item));
          if (!entry) return { kind: 'direct' };
          return parseProxyResolution(entry);
        } catch (error) {
          if (DIAG) log(`resolveProxy failed: ${error.message}`);
          return { kind: 'direct' };
        }
      };
      const proxy = createComputerNetworkProxy({ allowLocalFixture, upstreamResolver: systemProxy, debug: DIAG ? (msg) => log(`[netproxy] ${msg}`) : null });
      collaborationNetworkProxy = proxy.server;
      collaborationNetworkProxySecret = proxy.proxySecret;
      await new Promise((resolve, reject) => {
        collaborationNetworkProxy.once('error', reject);
        collaborationNetworkProxy.listen(0, '127.0.0.1', resolve);
      });
      const port = collaborationNetworkProxy.address().port;
      await browserSession.setProxy({ proxyRules: `http=127.0.0.1:${port};https=127.0.0.1:${port}`, proxyBypassRules: '<-loopback>' });
      await browserSession.closeAllConnections();
      collaborationView.webContents.on('login', (event, details, authInfo, callback) => {
        if (!authInfo.isProxy) return;
        event.preventDefault();
        callback('crab', collaborationNetworkProxySecret);
      });
      browserSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    })().catch((error) => {
      collaborationNetworkProxy?.close();
      collaborationNetworkProxyReady = null;
      throw error;
    });
  }
  return collaborationNetworkProxyReady;
}

function ensureCollaborationView() {
  if (collaborationView && !collaborationView.webContents.isDestroyed()) return collaborationView;
  invalidateCollaborationObservation('view-create');
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
      invalidateCollaborationObservation('window-open');
      checkedBrowserUrl(url).then((target) => collaborationView.webContents.loadURL(target)).catch((error) => {
        log(`Blocked collaboration popup: ${error.message}`);
      });
    } catch (error) {
      log(`Blocked collaboration popup: ${error.message}`);
    }
    return { action: 'deny' };
  });
  collaborationView.webContents.on('render-process-gone', () => invalidateCollaborationObservation('render-process-gone'));
  collaborationView.webContents.on('before-input-event', () => invalidateCollaborationObservation('before-input-event'));
  collaborationView.webContents.on('will-navigate', (event, url) => {
    try {
      normalizeBrowserUrl(url);
      invalidateCollaborationObservation('will-navigate');
    } catch {
      event.preventDefault();
    }
  });
  for (const eventName of ['did-navigate', 'did-navigate-in-page', 'did-start-loading', 'did-stop-loading', 'page-title-updated']) {
    collaborationView.webContents.on(eventName, () => {
      if (eventName === 'did-navigate' || eventName === 'did-navigate-in-page') {
        invalidateCollaborationObservation(eventName);
      }
      sendCollaborationBrowserState();
    });
  }
  const browserSession = collaborationView.webContents.session;
  browserSession.webRequest.onBeforeRequest((details, callback) => {
    // Deny network access before Chromium follows redirects or loads subresources.
    if (['data:', 'blob:'].some((scheme) => details.url.startsWith(scheme)) && details.resourceType !== 'mainFrame') {
      callback({ cancel: false });
      return;
    }
    checkedBrowserUrl(details.url).then(() => callback({ cancel: false }), () => callback({ cancel: true }));
  });
  browserSession.on('will-download', (event) => event.preventDefault());
  ensureCollaborationNetworkProxy(browserSession).then(() => collaborationView.webContents.loadURL(COLLABORATION_START_URL)).catch((error) => {
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
    collaborationStopped = true;
    collaborationStopEpoch += 1;
    collaborationTaskId = null;
    invalidateCollaborationObservation();
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

  invalidateCollaborationObservation();
  sendCollaborationBrowserState();
  return true;
}


function collaborationBridgeJson(res, status, payload) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(payload));
}

function collaborationSnapshotScript(pageVersion) {
  return `(() => {
    const nodes = document.querySelectorAll('a, button, input, select, textarea, [contenteditable], [role="button"], [role="link"]');
    const elements = [];
    let index = 1;
    for (const el of nodes) {
      if (elements.length >= 80) break;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      if (!rect.width || !rect.height || style.display === 'none' || style.visibility === 'hidden' || el.disabled) continue;
      const type = (el.type || '').toLowerCase();
      const rawLabel = String(el.innerText || el.placeholder || el.getAttribute('aria-label') || el.name || '').slice(0, 100);
      const sensitive = ${isSensitiveInput.toString()}(type, [rawLabel, el.name, el.id, el.autocomplete, el.getAttribute('aria-label')].join(' '));
      const label = sensitive ? '[sensitive field]' : rawLabel;
      const risk = /pay|payment|purchase|order|delete|remove|send|submit|transfer|checkout|付款|支付|下单|删除|发送|提交|转账/i.test(label);
      const selector = sensitive ? '' : el.id ? '#' + CSS.escape(el.id) : '[data-crab-collab="' + index + '"]';
      el.setAttribute('data-crab-collab', String(index));
      elements.push({ index, bounds: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }, tag: el.tagName.toLowerCase(), type, text: label, selector, sensitive, risk, fingerprint: [el.tagName, type, el.id, el.name, rawLabel].join('|').slice(0, 240) });
      index += 1;
    }
    const clone = document.body?.cloneNode(true);
    clone?.querySelectorAll('input, textarea, select, [contenteditable], [data-sensitive], [aria-live], script, style')
      .forEach((node) => node.replaceWith(document.createTextNode('[redacted]')));
    const bodyText = String(clone?.textContent || '').replace(/\s+/g, ' ').slice(0, 5000);
    return { page_version: ${pageVersion}, url: location.href, title: document.title, text: bodyText, viewport: { width: innerWidth, height: innerHeight, scrollY }, elements };
  })()`;
}

function requireCurrentPageVersion(payload) {
  const requested = Number(payload.page_version);
  if (!Number.isInteger(requested) || requested !== collaborationPageVersion
      || !collaborationObservation || collaborationObservation.page_version !== requested
      || collaborationObservation.url !== collaborationView.webContents.getURL()
      || payload.observation_id !== collaborationObservation.id
      || Date.now() - collaborationObservation.capturedAt > 30_000
      || collaborationObservation.viewport.width !== collaborationView.getBounds().width
      || collaborationObservation.viewport.height !== collaborationView.getBounds().height) {
    const error = new Error('STALE_PAGE: observe the page again before acting');
    error.code = 'STALE_PAGE';
    throw error;
  }
}

function isSensitiveInput(type, label) {
  return ['password', 'hidden', 'file'].includes(type)
    || /password|passcode|otp|one.time|verification|captcha|recaptcha|hcaptcha|human.challenge|cvv|card|credit|bank|iban|security|ssn|passport|id.card|银行卡|密码|验证码|校验码|支付|身份证|人机验证/i.test(label);
}

async function handleCollaborationBridge(command, payload) {
  const view = ensureCollaborationView();
  const contents = view.webContents;
  if (command === 'stop') {
    collaborationStopEpoch += 1;
    collaborationStopped = true;
    collaborationTaskId = null;
    invalidateCollaborationObservation();
    return { stopped: true };
  }
  if (command === 'resume') {
    collaborationStopped = false;
    collaborationTaskId = null;
    invalidateCollaborationObservation();
    return { resumed: true };
  }
  if (collaborationStopped && !['status', 'observe', 'computer_observe', 'screenshot'].includes(command)) {
    throw new Error('STOPPED: browser actions are paused');
  }
  if (command === 'status') return { page_version: collaborationPageVersion, url: contents.getURL(), title: contents.getTitle(), loading: contents.isLoading() };
  if (command === 'navigate') {
    const target = await checkedBrowserUrl(payload.url);
    await ensureCollaborationNetworkProxy(contents.session);
    invalidateCollaborationObservation();
    try {
      await contents.loadURL(target);
    } catch (loadError) {
      invalidateCollaborationObservation();
      throw new Error(`NAVIGATION_FAILED: ${loadError.message}`);
    }
    return { page_version: collaborationPageVersion, url: contents.getURL(), title: contents.getTitle() };
  }
  if (command === 'observe') {
    // Observe can race a transient navigation burst (start-page retries, layout settling).
    // Retry once after a short delay before giving up, per the design's retry-once rule.
    let snapshot = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      snapshot = await contents.executeJavaScript(collaborationSnapshotScript(collaborationPageVersion), true);
      if (snapshot.page_version === collaborationPageVersion && snapshot.url === contents.getURL()) break;
      if (attempt === 0) {
        log(`Observation stale: expected=${collaborationPageVersion} got=${snapshot.page_version} snapshotUrl=${snapshot.url} liveUrl=${contents.getURL()} loading=${contents.isLoading()}`);
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
    }
    // Chromium error pages report chrome-error://chromewebdata/ as location.href while
    // getURL() keeps the attempted target. Treat them as the same document so the model
    // can observe the error text and navigate away instead of failing forever.
    const observedUrl = snapshot.url.startsWith('chrome-error://') ? contents.getURL() : snapshot.url;
    if (snapshot.page_version !== collaborationPageVersion || observedUrl !== contents.getURL()) {
      throw new Error(`STALE_PAGE: navigation during observation (expected=${collaborationPageVersion} got=${snapshot.page_version} liveUrl=${contents.getURL()})`);
    }
    collaborationPending.clear();
    collaborationObservation = {
      page_version: collaborationPageVersion,
      url: observedUrl,
      id: crypto.randomUUID(),
      capturedAt: Date.now(),
      elements: new Map(snapshot.elements.map((item) => [item.index, item.fingerprint])),
      viewport: { ...snapshot.viewport },
    };
    snapshot.url = observedUrl;
    return { ...snapshot, protocol_version: 1, runtime_id: 'browser:collaboration',
      surface_id: String(contents.id), captured_at_ms: collaborationObservation.capturedAt, observation_id: collaborationObservation.id };
  }
  if (command === 'computer_observe') {
    const snapshot = await handleCollaborationBridge('observe', {});
    const observation = collaborationObservation;
    const bounds = view.getBounds();
    const image = await contents.capturePage();
    const dimensions = image.getSize();
    if (image.toJPEG(75).length > 2_000_000) throw new Error('CAPTURE_FAILED: screenshot exceeds size limit');
    const after = await contents.executeJavaScript(`(() => ({url: location.href, width: innerWidth, height: innerHeight, scrollY}))()`, true);
    const beforeUrl = snapshot.url.startsWith('chrome-error://') ? contents.getURL() : snapshot.url;
    const afterUrl = after.url.startsWith('chrome-error://') ? contents.getURL() : after.url;
    if (observation !== collaborationObservation || beforeUrl !== contents.getURL()
        || afterUrl !== beforeUrl || after.width !== snapshot.viewport.width
        || after.height !== snapshot.viewport.height || after.scrollY !== snapshot.viewport.scrollY
        || bounds.width !== snapshot.viewport.width || bounds.height !== snapshot.viewport.height) {
      throw new Error('STALE_PAGE: viewport changed during screenshot');
    }
    return { ...snapshot, screenshot: { width: dimensions.width, height: dimensions.height,
      scale_x: dimensions.width / bounds.width, scale_y: dimensions.height / bounds.height },
      mime: 'image/jpeg', data_url: `data:image/jpeg;base64,${image.toJPEG(75).toString('base64')}` };
  }
  if (command === 'screenshot') return handleCollaborationBridge('computer_observe', payload);
  if (command === 'click' || command === 'commit_click') {
    requireCurrentPageVersion(payload);
    if (command === 'commit_click' && !payload.pending_action_id) throw new Error('APPROVAL_INVALID');
    const index = Number(payload.index);
    if (!Number.isInteger(index) || index < 1 || index > 80) throw new Error('Invalid element index');
    const observation = collaborationObservation;
    const target = await contents.executeJavaScript(`(async () => {
      const el = document.querySelector('[data-crab-collab="${index}"]');
      if (!el) throw new Error('Element not found; observe again');
      const type = String(el.type || '').toLowerCase();
      const label = String(el.innerText || el.getAttribute('aria-label') || el.placeholder || '').slice(0, 100);
      const fingerprint = [el.tagName, type, el.id, el.name, String(el.innerText || el.placeholder || el.getAttribute('aria-label') || el.name || '').slice(0, 100)].join('|').slice(0, 240);
      el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
      // Occluded/minimized windows throttle rAF; never wait on it unbounded.
      await new Promise((resolve) => {
        let done = false;
        const finish = () => { if (!done) { done = true; resolve(); } };
        requestAnimationFrame(() => requestAnimationFrame(finish));
        setTimeout(finish, 500);
      });
      const rect = el.getBoundingClientRect();
      const x = Math.round(rect.left + rect.width / 2);
      const y = Math.round(rect.top + rect.height / 2);
      if (!rect.width || !rect.height || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight || document.elementFromPoint(x, y) !== el && !el.contains(document.elementFromPoint(x, y))) {
        throw new Error('Element is covered or outside the viewport; observe again');
      }
      const context = String(el.closest('form')?.innerText || '').slice(0, 250);
      const sensitive = ${isSensitiveInput.toString()}(type, [el.getAttribute('aria-label'), el.name, el.id, el.autocomplete, label, context].join(' '));
      const href = el.closest('a[href]')?.href;
      let crossOrigin = false;
      try { crossOrigin = Boolean(href && new URL(href).origin !== location.origin); } catch { crossOrigin = true; }
      const form = el.closest('form');
      const submit = (Boolean(form) && el.matches('button,input') && (el.type || '').toLowerCase() === 'submit')
        || (el.tagName === 'BUTTON' && !el.hasAttribute('type') && Boolean(form));
      return { index: ${index}, label, fingerprint, context, sensitive, crossOrigin, submit,
        x, y, url: location.href, title: document.title };
    })()`, true);
    if (observation !== collaborationObservation || observation.elements.get(index) !== target.fingerprint
        || target.url !== observation.url) throw new Error('STALE_PAGE: target changed; observe again');
    if (target.sensitive) throw new Error('SENSITIVE_INPUT');
    const risky = /pay|payment|purchase|order|delete|remove|send|submit|transfer|checkout|publish|account|security|付款|支付|下单|删除|发送|提交|转账|发布|账号|安全/i.test(target.label + ' ' + target.context)
      || target.crossOrigin || target.submit;
    const digest = crypto.createHash('sha256').update(JSON.stringify({
      index, fingerprint: target.fingerprint, origin: new URL(target.url).origin,
      observation: observation.id,
    })).digest('hex');
    if (collaborationStopped) throw new Error('STOPPED');
    if (command === 'click' && risky) {
      const pending_action_id = crypto.randomUUID();
      collaborationPending.set(pending_action_id, { digest, index, observation, expires: Date.now() + CONFIRM_TTL_MS });
      return { confirmation_required: true, pending_action_id, index, label: target.label,
        url: target.url, page_version: collaborationPageVersion };
    }
    if (command === 'commit_click') {
      const pending = collaborationPending.get(String(payload.pending_action_id || ''));
      collaborationPending.delete(String(payload.pending_action_id || ''));
      if (!pending || pending.expires < Date.now() || pending.index !== index
          || pending.observation !== observation || pending.digest !== digest || !risky) {
        throw new Error('APPROVAL_INVALID: action changed, expired or already used');
      }
    } else if (risky) {
      throw new Error('CONFIRMATION_REQUIRED');
    }
    // Recheck after all asynchronous DOM queries, immediately before dispatch.
    if (contents.getURL() !== target.url || observation !== collaborationObservation || collaborationStopped) throw new Error('STALE_PAGE');
    contents.sendInputEvent({ type: 'mouseMove', x: target.x, y: target.y });
    contents.sendInputEvent({ type: 'mouseDown', x: target.x, y: target.y, button: 'left', clickCount: 1 });
    contents.sendInputEvent({ type: 'mouseUp', x: target.x, y: target.y, button: 'left', clickCount: 1 });
    collaborationObservation = null;
    collaborationPending.clear();
    return { clicked: index, method: 'native_mouse', point: { x: target.x, y: target.y },
      url: target.url, title: target.title, page_version: collaborationPageVersion };
  }
  if (command === 'point' || command === 'commit_point') {
    requireCurrentPageVersion(payload);
    if (command === 'commit_point' && !payload.pending_action_id) throw new Error('APPROVAL_INVALID');
    const observation = collaborationObservation;
    const x = Number(payload.x);
    const y = Number(payload.y);
    const kind = String(payload.kind || 'click');
    if (!Number.isInteger(x) || !Number.isInteger(y) || !['click', 'double_click', 'move', 'drag', 'scroll'].includes(kind)) {
      throw new Error('Invalid point action');
    }
    const bounds = view.getBounds();
    if (x < 0 || y < 0 || x >= bounds.width || y >= bounds.height) throw new Error('POINT_OUTSIDE_VIEWPORT');
    const details = await contents.executeJavaScript(`(() => {
      const el = document.elementFromPoint(${x}, ${y});
      if (!el) throw new Error('Point has no target');
      const tag = el.tagName.toLowerCase();
      const label = String(el.innerText || el.getAttribute('aria-label') || el.title || '').slice(0, 100);
      const form = String(el.closest('form')?.innerText || '').slice(0, 250);
      const input = el.closest('input,textarea,select,[contenteditable]');
      return { tag, label, form, type: input?.type || '', url: location.href,
        sensitive: ${isSensitiveInput.toString()}(input?.type || '', [label, form, input?.name, input?.id, input?.autocomplete, input?.getAttribute('aria-label')].join(' ')),
        editable: Boolean(input) };
    })()`, true);
    if (observation !== collaborationObservation || details.url !== contents.getURL()) throw new Error('STALE_PAGE');
    if (details.sensitive || details.editable) throw new Error('SENSITIVE_OR_EDITABLE_POINT');
    if (kind === 'drag') {
      const x2 = Number(payload.x2), y2 = Number(payload.y2);
      if (!Number.isInteger(x2) || !Number.isInteger(y2) || x2 < 0 || y2 < 0
          || x2 >= bounds.width || y2 >= bounds.height) throw new Error('Invalid drag endpoint');
    }
    const digest = crypto.createHash('sha256').update(JSON.stringify({
      kind, x, y, x2: payload.x2, y2: payload.y2, amount: payload.amount,
      observation: observation.id, details,
    })).digest('hex');
    // Point clicks and drags are never classified low-risk without semantic grounding.
    const needsConfirmation = ['click', 'double_click', 'drag'].includes(kind);
    if (command === 'point' && needsConfirmation) {
      const pending_action_id = crypto.randomUUID();
      collaborationPending.set(pending_action_id, { digest, observation, expires: Date.now() + CONFIRM_TTL_MS });
      return { confirmation_required: true, pending_action_id, label: details.label || 'Visual target',
        url: details.url, page_version: collaborationPageVersion };
    }
    if (command === 'commit_point') {
      const pending = collaborationPending.get(String(payload.pending_action_id || ''));
      collaborationPending.delete(String(payload.pending_action_id || ''));
      if (!needsConfirmation || !pending || pending.expires < Date.now()
          || pending.observation !== observation || pending.digest !== digest) throw new Error('APPROVAL_INVALID');
    }
    if (collaborationStopped || observation !== collaborationObservation || details.url !== contents.getURL()) throw new Error('STOPPED_OR_STALE');
    if (kind === 'scroll') {
      const amount = Number(payload.amount);
      if (!Number.isInteger(amount) || Math.abs(amount) > 2000) throw new Error('Invalid scroll');
      contents.sendInputEvent({ type: 'mouseWheel', x, y, deltaY: -amount, deltaX: 0 });
    } else if (kind === 'move') {
      contents.sendInputEvent({ type: 'mouseMove', x, y });
    } else {
      if (kind === 'drag') {
        const x2 = Number(payload.x2), y2 = Number(payload.y2);
        if (!Number.isInteger(x2) || !Number.isInteger(y2) || x2 < 0 || y2 < 0
            || x2 >= bounds.width || y2 >= bounds.height) throw new Error('Invalid drag endpoint');
        contents.sendInputEvent({ type: 'mouseMove', x, y });
        await new Promise((resolve) => setTimeout(resolve, 40));
        contents.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 });
        await new Promise((resolve) => setTimeout(resolve, 40));
        contents.sendInputEvent({ type: 'mouseMove', x: x + Math.sign(x2 - x) || 1, y: y + Math.sign(y2 - y) || 1, button: 'left', buttons: ['left'] });
        await new Promise((resolve) => setTimeout(resolve, 40));
        let releaseX = x, releaseY = y;
        try {
          for (let i = 2; i <= 10; i++) {
            if (collaborationStopped || observation !== collaborationObservation) throw new Error('STOPPED_OR_STALE');
            releaseX = Math.round(x + (x2 - x) * i / 10);
            releaseY = Math.round(y + (y2 - y) * i / 10);
            contents.sendInputEvent({ type: 'mouseMove', x: releaseX, y: releaseY, button: 'left', buttons: ['left'] });
            await new Promise((resolve) => setTimeout(resolve, 30));
            await new Promise((resolve) => setTimeout(resolve, 16));
          }
          if (collaborationStopped || observation !== collaborationObservation) throw new Error('STOPPED_OR_STALE');
        } finally {
          await new Promise((resolve) => setTimeout(resolve, 40));
          contents.sendInputEvent({ type: 'mouseUp', x: releaseX, y: releaseY, button: 'left', clickCount: 1 });
        }
      } else {
        const count = kind === 'double_click' ? 2 : 1;
        contents.sendInputEvent({ type: 'mouseMove', x, y });
        for (let i = 1; i <= count; i++) {
          contents.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: i });
          contents.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount: i });
        }
      }
    }
    collaborationObservation = null;
    collaborationPending.clear();
    return { performed: kind, point: { x, y }, page_version: collaborationPageVersion };
  }
  if (command === 'type') {
    requireCurrentPageVersion(payload);
    const index = Number(payload.index);
    const input = String(payload.text || '');
    if (!Number.isInteger(index) || index < 1 || index > 80 || input.length > 10000) throw new Error('Invalid type request');
    const observation = collaborationObservation;
    const target = await contents.executeJavaScript(`(() => {
      const el = document.querySelector('[data-crab-collab="${index}"]');
      if (!el) throw new Error('Element not found; observe again');
      const type = String(el.type || '').toLowerCase();
      const label = String(el.placeholder || el.getAttribute('aria-label') || el.name || '');
      if (${isSensitiveInput.toString()}(type, [label, el.id, el.autocomplete, el.closest('form')?.innerText].join(' '))) throw new Error('SENSITIVE_INPUT: AI cannot type into this field');
      if (!el.matches('input,textarea,[contenteditable]:not([contenteditable="false"])')) throw new Error('Not an editable field');
      const text = String(el.innerText || el.placeholder || el.getAttribute('aria-label') || el.name || '').slice(0, 100);
      const fingerprint = [el.tagName, type, el.id, el.name, text].join('|').slice(0, 240);
      el.focus();
      if (el.isContentEditable) {
        const range = document.createRange();
        range.selectNodeContents(el);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      } else {
        el.select();
      }
      return { fingerprint, url: location.href };
    })()`, true);
    if (observation !== collaborationObservation || observation.elements.get(index) !== target.fingerprint
        || target.url !== contents.getURL() || collaborationStopped) throw new Error('STALE_PAGE');
    if (input) contents.insertText(input);
    collaborationObservation = null;
    collaborationPending.clear();
    return { typed: index, url: target.url, page_version: collaborationPageVersion };
  }
  if (command === 'scroll') {
    requireCurrentPageVersion(payload);
    const amount = Number(payload.amount);
    if (!Number.isInteger(amount) || Math.abs(amount) > 2000) throw new Error('Invalid scroll');
    if (collaborationStopped) throw new Error('STOPPED');
    const outcome = await contents.executeJavaScript(`(() => { window.scrollBy(0, ${amount}); return { scrollY: window.scrollY, url: location.href }; })()`, true);
    collaborationObservation = null;
    collaborationPending.clear();
    return { ...outcome, page_version: collaborationPageVersion };
  }
  if (command === 'select') {
    requireCurrentPageVersion(payload);
    const index = Number(payload.index);
    const value = String(payload.value || '');
    if (!Number.isInteger(index) || index < 1 || index > 80 || value.length > 1000) throw new Error('Invalid select request');
    const observation = collaborationObservation;
    const target = await contents.executeJavaScript(`(() => { const el = document.querySelector('[data-crab-collab="${index}"]'); if (!el || el.tagName !== 'SELECT') throw new Error('Element not found or not select'); const label = String(el.innerText || el.placeholder || el.getAttribute('aria-label') || el.name || '').slice(0, 100); const fingerprint = [el.tagName, String(el.type || '').toLowerCase(), el.id, el.name, label].join('|').slice(0, 240); const option = Array.from(el.options).find((item) => item.value === ${JSON.stringify(value)} || item.text === ${JSON.stringify(value)}); if (!option) throw new Error('Option not found'); return { fingerprint, sensitive: ${isSensitiveInput.toString()}('', [el.getAttribute('aria-label'), el.name, el.id, el.autocomplete, option.text, el.closest('form')?.innerText].join(' ')), url: location.href }; })()`, true);
    if (target.sensitive) throw new Error('SENSITIVE_INPUT');
    if (observation !== collaborationObservation || observation.elements.get(index) !== target.fingerprint
        || target.url !== contents.getURL() || collaborationStopped) throw new Error('STALE_PAGE');
    const outcome = await contents.executeJavaScript(`(() => { const el = document.querySelector('[data-crab-collab="${index}"]'); if (!el || !el.isConnected) throw new Error('STALE_PAGE'); const option = Array.from(el.options).find((item) => item.value === ${JSON.stringify(value)} || item.text === ${JSON.stringify(value)}); if (!option) throw new Error('STALE_PAGE'); el.value = option.value; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return { selected: ${index}, url: location.href }; })()`, true);
    collaborationObservation = null;
    collaborationPending.clear();
    return { ...outcome, page_version: collaborationPageVersion };
  }
  if (command === 'press_key') {
    requireCurrentPageVersion(payload);
    const key = String(payload.key || '');
    if (!/^(Enter|Escape|Tab|ArrowUp|ArrowDown|ArrowLeft|ArrowRight)$/.test(key)) throw new Error('Unsupported key');
    if (key === 'Enter') {
      const target = await contents.executeJavaScript(`(() => {
        const el = document.activeElement;
        return { tag: el?.tagName, type: el?.type || '', label: String(el?.outerHTML || '').slice(0, 300),
          form: String(el?.closest('form')?.innerText || '').slice(0, 250) };
      })()`, true);
      if (target.tag !== 'INPUT' || isSensitiveInput(target.type, target.label)
          || /pay|payment|purchase|delete|send|submit|transfer|checkout|支付|删除|发送|提交|转账/i.test(target.form)) {
        throw new Error('CONFIRMATION_REQUIRED: use a reviewed element click instead');
      }
    }
    if (collaborationStopped) throw new Error('STOPPED');
    contents.sendInputEvent({ type: 'keyDown', keyCode: key });
    contents.sendInputEvent({ type: 'keyUp', keyCode: key });
    collaborationObservation = null;
    collaborationPending.clear();
    return { pressed: key, url: contents.getURL(), page_version: collaborationPageVersion };
  }
  if (command === 'wait_for') {
    const timeout = Math.max(100, Math.min(30_000, Number(payload.timeout_ms) || 10_000));
    const text = String(payload.text || '').slice(0, 500);
    const urlIncludes = String(payload.url_includes || '').slice(0, 500);
    const started = Date.now();
    while (Date.now() - started < timeout) {
      if (collaborationStopped) throw new Error('STOPPED');
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
        if (body.protocol_version !== 1 || body.runtime_id !== 'browser:collaboration'
            || typeof body.task_id !== 'string' || !/^[0-9a-f-]{36}$/i.test(body.task_id)
            || typeof body.trace_id !== 'string' || !/^[0-9a-f-]{36}$/i.test(body.trace_id)) {
          throw new Error('Invalid computer protocol or runtime binding');
        }
        const command = String(body.command || '');
        const commands = new Set(['status', 'stop', 'resume', 'navigate', 'observe', 'computer_observe', 'screenshot',
          'click', 'commit_click', 'point', 'commit_point', 'type', 'scroll', 'select', 'press_key', 'wait_for',
          'macos_permissions', 'macos_windows', 'macos_allow_app',
          'macos_observe', 'macos_capture', 'macos_click', 'macos_type', 'macos_key', 'macos_scroll',
          'macos_activate']);
        if (!commands.has(command) || !body.payload || typeof body.payload !== 'object' || Array.isArray(body.payload)) {
          throw new Error('Invalid bridge command or payload');
        }
        if (command === 'macos_allow_app') {
          // Persists a user-approved bundle to the allowlist. The user consent happens in
          // the Python layer (confirm_callback card); the model can never reach this
          // command without that approval.
          const bundleId = String(body.payload?.bundleId || '').trim();
          if (!/^[A-Za-z0-9.-]+$/.test(bundleId)) {
            collaborationBridgeJson(res, 400, { detail: 'invalid bundle id' });
            return;
          }
          const config = macosComputerConfig();
          if (!config.allowlist.includes(bundleId)) config.allowlist.push(bundleId);
          fs.mkdirSync(path.dirname(MACOS_CONFIG_PATH), { recursive: true });
          fs.writeFileSync(MACOS_CONFIG_PATH, JSON.stringify(config, null, 2), { mode: 0o600 });
          const result = await runMacosHelper({ command: 'permissions' });
          collaborationBridgeJson(res, 200, { result: { ok: true, allowlist: config.allowlist, permissions: result.ok ? result.permissions : null } });
          return;
        }
        if (command === 'macos_permissions' || command === 'macos_windows') {
          // Read-only macOS surface queries; exempt from task binding and stop state.
          const result = await runMacosHelper({ command: command === 'macos_permissions' ? 'permissions' : 'windows' });
          collaborationBridgeJson(res, 200, { result });
          return;
        }
        if (command.startsWith('macos_')) {
          // M1 macOS surface commands: the helper enforces its own gates (opt-in via
          // macos-computer-config.json inputEnabled + allowlist + frontmost + secure
          // input/lock). Browser pause state must NOT gate macOS actions — they have
          // their own toggle in Settings → macOS 控制.
          if (!body.payload || typeof body.payload !== 'object') {
            collaborationBridgeJson(res, 400, { detail: 'payload required' });
            return;
          }
          const macosCommand = command.replace(/^macos_/, '');
          const result = await runMacosHelper({ command: macosCommand, ...body.payload });
          collaborationBridgeJson(res, 200, { result });
          return;
        }
        const queuedAtEpoch = collaborationStopEpoch;
        const execute = () => {
          if (collaborationTaskId && collaborationTaskId !== body.task_id && !['stop', 'resume', 'status'].includes(command)) {
            throw new Error('TASK_MISMATCH: stop and resume before switching browser tasks');
          }
          if (queuedAtEpoch !== collaborationStopEpoch && !['status', 'stop', 'resume'].includes(command)) {
            throw new Error('STOPPED: action queued before stop');
          }
          if (!collaborationTaskId && !collaborationStopped && !['stop', 'resume', 'status'].includes(command)) collaborationTaskId = body.task_id;
          const actionId = body.payload.action_id;
          const mutating = new Set(['navigate', 'click', 'commit_click', 'point', 'commit_point', 'type', 'scroll', 'select', 'press_key']);
          if (mutating.has(command)) {
            if (typeof actionId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(actionId)) {
              throw new Error('Invalid action_id');
            }
            for (const [id, timestamp] of collaborationActionIds) {
              if (Date.now() - timestamp > ACTION_ID_TTL_MS) collaborationActionIds.delete(id);
            }
            if (collaborationActionIds.has(actionId)) throw new Error('DUPLICATE_ACTION: do not retry; re-observe and reconcile');
            // Reserve before dispatch: a lost response must not cause a second injection.
            collaborationActionIds.set(actionId, Date.now());
            if (collaborationActionIds.size > 4096) collaborationActionIds.delete(collaborationActionIds.keys().next().value);
          }
          return handleCollaborationBridge(command, body.payload);
        };
        const result = ['status', 'stop'].includes(command) ? await execute() : await (collaborationActionQueue = collaborationActionQueue.then(execute, execute));
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
  if (DIAG) log(`DIAG bridge token: ${collaborationBridgeToken}`);
  return collaborationBridgePort;
}

// ── macOS computer-use helper (M0/M1) ──
// One-shot invocations of the Swift helper; no interactive stdio. Read-only
// commands (permissions/windows) are always available. Input commands (observe/
// capture/click/type/key/scroll against user apps) require an explicit opt-in
// config file plus an app allowlist, per docs/computer-use-macos-m0-decisions.md.
// electron-builder packs the helper into app.asar; executables must run from the
// unpacked directory, so resolve through app.asar.unpacked when packaged.
const MACOS_HELPER_PACKED_PATH = __dirname.includes('app.asar')
  ? path.join(__dirname.replace('app.asar', 'app.asar.unpacked'), 'helper', 'macos-helper')
  : path.join(__dirname, 'helper', 'macos-helper');
// TCC (macOS 26) attributes binaries inside an .app bundle to the app's own (adhoc)
// signature, which loses grants on every rebuild. Binaries outside the bundle are
// attributed to their own code-signing identity, so the helper runs from a stable
// per-user location; the cert-signed copy there keeps TCC grants across repacks.
const MACOS_HELPER_PATH = path.join(os.homedir(), '.crabagent', 'bin', 'macos-helper');

function macosHelperAvailable() {
  try {
    // Refresh the stable copy whenever the bundled helper is newer (app updates).
    if (fs.existsSync(MACOS_HELPER_PACKED_PATH)) {
      const bundled = fs.statSync(MACOS_HELPER_PACKED_PATH);
      let runtime = null;
      try { runtime = fs.statSync(MACOS_HELPER_PATH); } catch {}
      fs.mkdirSync(path.dirname(MACOS_HELPER_PATH), { recursive: true });
      if (!runtime || runtime.mtimeMs < bundled.mtimeMs || runtime.size !== bundled.size) {
        fs.copyFileSync(MACOS_HELPER_PACKED_PATH, MACOS_HELPER_PATH);
        fs.chmodSync(MACOS_HELPER_PATH, 0o755);
      }
      return fs.accessSync(MACOS_HELPER_PATH, fs.constants.X_OK) === undefined;
    }
    fs.accessSync(MACOS_HELPER_PATH, fs.constants.X_OK);
    return true;
  } catch { return false; }
}
const MACOS_CONFIG_PATH = path.join(app.getPath('userData'), 'macos-computer-config.json');
let macosHelperSecret = null;

function macosComputerConfig() {
  // { "inputEnabled": bool, "allowlist": ["com.bundle.id", ...] }
  try {
    const raw = JSON.parse(fs.readFileSync(MACOS_CONFIG_PATH, 'utf8'));
    return {
      inputEnabled: raw.inputEnabled === true,
      allowlist: Array.isArray(raw.allowlist) ? raw.allowlist.filter((x) => typeof x === 'string').slice(0, 32) : [],
    };
  } catch {
    return { inputEnabled: false, allowlist: [] };
  }
}

function runMacosHelper(request) {
  return new Promise((resolve) => {
    if (!macosHelperAvailable()) { resolve({ ok: false, error: 'helper not built' }); return; }
    if (!macosHelperSecret) macosHelperSecret = crypto.randomBytes(16).toString('hex');
    const requestPath = path.join(os.tmpdir(), `crab-helper-req-${crypto.randomBytes(8).toString('hex')}.json`);
    const config = macosComputerConfig();
    try {
      fs.writeFileSync(requestPath, JSON.stringify({
        ...request,
        allowlist: config.allowlist,
        secret: macosHelperSecret,
      }), { mode: 0o600 });
    } catch (e) { resolve({ ok: false, error: `request write failed: ${e.message}` }); return; }
    let out = '';
    let settled = false;
    const finish = (payload) => {
      if (settled) return;
      settled = true;
      try { fs.unlinkSync(requestPath); } catch {}
      try { resolve(JSON.parse(out)); } catch { resolve({ ok: false, error: 'bad helper output' }); }
    };
    const childEnv = { ...process.env };
    if (config.inputEnabled) childEnv.CRAB_MACOS_INPUT = '1';
    const child = spawn(MACOS_HELPER_PATH, ['--request-file', requestPath, '--secret', macosHelperSecret], { env: childEnv });
    child.stdout.on('data', (d) => { out += d; });
    child.on('error', (e) => finish({ ok: false, error: `helper spawn failed: ${e.message}` }));
    child.on('close', () => finish({ ok: false, error: 'helper produced no output' }));
    setTimeout(() => { if (!settled) { child.kill(); } }, 15000);
  });
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
const LOG_PATH = require('path').join(require('os').homedir(), '.crabagent', 'electron.log');
const LOG_MAX_BYTES = 50 * 1024 * 1024;
let logWriteCount = 0;

function rotateLogIfNeeded() {
  try {
    if (fs.existsSync(LOG_PATH) && fs.statSync(LOG_PATH).size > LOG_MAX_BYTES) {
      fs.rmSync(LOG_PATH + '.1', { force: true });
      fs.renameSync(LOG_PATH, LOG_PATH + '.1');
    }
  } catch {}
}

function log(msg) {
  console.log(`[CrabAgent] ${msg}`);
  try {
    // Rotated at launch and every 2000 lines; a runaway debug loop can no longer
    // grow the log without bound (it reached 8 GB once).
    if (++logWriteCount % 2000 === 0) rotateLogIfNeeded();
    const line = new Date().toISOString() + ' ' + msg + '\n';
    fs.appendFileSync(LOG_PATH, line);
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
ipcMain.handle('collaboration-browser-navigate', async (event, url) => {
  if (event.sender !== win?.webContents) throw new Error('Unauthorized browser request');
  const target = await checkedBrowserUrl(url);
  const view = ensureCollaborationView();
  await ensureCollaborationNetworkProxy(view.webContents.session);
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
ipcMain.handle('macos-computer-get-status', async (event) => {
  if (event.sender !== win?.webContents) throw new Error('Unauthorized settings request');
  const config = macosComputerConfig();
  const permissions = await runMacosHelper({ command: 'permissions' });
  return {
    config,
    permissions: permissions.ok ? permissions.permissions : null,
    helperAvailable: macosHelperAvailable(),
    error: permissions.ok ? null : permissions.error,
  };
});

ipcMain.handle('macos-computer-set-config', async (event, config) => {
  if (event.sender !== win?.webContents) throw new Error('Unauthorized settings request');
  if (!config || typeof config !== 'object') throw new Error('Invalid config');
  const next = {
    inputEnabled: config.inputEnabled === true,
    allowlist: Array.isArray(config.allowlist)
      ? config.allowlist.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim()).slice(0, 32)
      : [],
  };
  fs.mkdirSync(path.dirname(MACOS_CONFIG_PATH), { recursive: true });
  fs.writeFileSync(MACOS_CONFIG_PATH, JSON.stringify(next, null, 2), { mode: 0o600 });
  const permissions = await runMacosHelper({ command: 'permissions' });
  return {
    config: next,
    permissions: permissions.ok ? permissions.permissions : null,
    helperAvailable: macosHelperAvailable(),
    error: permissions.ok ? null : permissions.error,
  };
});

ipcMain.handle('macos-computer-open-settings', async (event, kind) => {
  if (event.sender !== win?.webContents) throw new Error('Unauthorized settings request');
  const panes = {
    accessibility: 'com.apple.preference.security?Privacy_Accessibility',
    screenRecording: 'com.apple.preference.security?Privacy_ScreenCapture',
  };
  const pane = panes[kind];
  if (!pane) throw new Error('Unknown settings pane');
  const child = spawn('open', [pane], { stdio: 'ignore' });
  child.on('error', (e) => log(`open system settings failed: ${e.message}`));
  // System Settings often opens behind the frontmost app; raise it explicitly.
  child.on('close', () => {
    const activate = spawn('osascript', ['-e', 'tell application "System Settings" to activate'], { stdio: 'ignore' });
    activate.on('error', (e) => log(`activate system settings failed: ${e.message}`));
  });
  return true;
});

ipcMain.handle('collaboration-browser-action', async (event, action) => {
  if (event.sender !== win?.webContents) throw new Error('Unauthorized browser request');
  const contents = ensureCollaborationView().webContents;
  if (action === 'back' && contents.canGoBack()) contents.goBack();
  if (action === 'forward' && contents.canGoForward()) contents.goForward();
  if (action === 'reload') contents.reload();
  if (action === 'stop') contents.stop();
  if (action === 'computer-stop') { collaborationStopEpoch += 1; collaborationStopped = true; collaborationTaskId = null; invalidateCollaborationObservation(); }
  if (action === 'computer-resume') { collaborationStopped = false; collaborationTaskId = null; invalidateCollaborationObservation(); }
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
  rotateLogIfNeeded();
  if (!DIAG) killExistingBackend();
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
    win.loadURL(process.env.CRAB_APP_ROUTE || BACKEND_URL);
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
  collaborationNetworkProxy?.close();
});
