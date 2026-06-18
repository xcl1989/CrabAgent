const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const PORT = 5210;
const URL = `http://127.0.0.1:${PORT}`;
const isMac = process.platform === 'darwin';

let python = null;
let win = null;
let tray = null;
let forceQuit = false;

// ── Window state persistence ──
const STATE_PATH = path.join(app.getPath('userData'), 'window-state.json');

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

// ── Logging ──
function log(msg) { console.log(`[CrabAgent] ${msg}`); }

// ── Kill existing process on port ──
function killExistingBackend() {
  try {
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
  } catch {}
}

function resolvePath(cmd) {
  try { return execSync(`/bin/bash -l -c 'command -v ${cmd} 2>/dev/null'`, { encoding: 'utf-8' }).trim(); }
  catch { return null; }
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, PYTHONUNBUFFERED: '1' };
    const crabagentBin = resolvePath('crabagent');
    const pythonBin = resolvePath('python3') || 'python3';

    log(`crabagent: ${crabagentBin || 'not found'}`);
    log(`python3: ${pythonBin}`);

    const cmd = crabagentBin || pythonBin;
    const args = crabagentBin ? ['--serve'] : ['-m', 'crabagent.cli', '--serve'];

    python = spawn(cmd, args, { stdio: 'pipe', env });

    python.on('error', (e) => { log(`Backend error: ${e.message}`); reject(e); });
    python.on('exit', (c) => log(`Backend exited (${c})`));
    python.stdout.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
    python.stderr.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
    setTimeout(resolve, 500);
  });
}

function waitForServer(maxWait = 60000) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    function check() {
      http.get(`${URL}/api/health`, (r) => { if (r.statusCode === 200) resolve(); else retry(); })
        .on('error', retry);
      function retry() { if (Date.now() - t0 > maxWait) reject(new Error('Timeout')); else setTimeout(check, 500); }
    }
    check();
  });
}

// ── Create tray ──
function createTray() {
  // Try app icon, fall back to a simple 16x16 image
  let trayIcon;
  const iconPath = path.join(__dirname, 'build', 'icon.png');
  if (fs.existsSync(iconPath)) {
    trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 22, height: 22 });
  } else {
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);
  tray.setToolTip('CrabAgent');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示窗口',
      click: () => showWindow(),
      accelerator: 'CmdOrCtrl+Shift+C',
    },
    { type: 'separator' },
    {
      label: '打开工作目录',
      click: () => {
        const { exec } = require('child_process');
        exec(`open "${process.env.HOME}/.crabagent"`);
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
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  if (saved.maximized) win.maximize();

  win.loadURL(URL);

  // Auto-login
  let injected = false;
  win.webContents.on('dom-ready', async () => {
    if (injected) return;
    injected = true;
    try {
      const body = JSON.stringify({ username: 'admin', password: 'xcl1989' });
      const tokenResp = await new Promise((resolve, reject) => {
        const req = http.request(
          `${URL}/api/auth/login`,
          { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } },
          (res) => {
            let data = '';
            res.on('data', (c) => (data += c));
            res.on('end', () => {
              try { resolve(JSON.parse(data).access_token); } catch (e) { reject(e); }
            });
          }
        );
        req.on('error', reject);
        req.write(body);
        req.end();
      });

      await win.webContents.executeJavaScript(
        `window.localStorage.setItem('crab_token','${tokenResp}')`,
      );
      log('Auto-login done');
      win.webContents.reload();
    } catch (e) {
      log(`Auto-login skipped: ${e.message}`);
    }
  });

  // Show window when ready
  win.once('ready-to-show', () => {
    win.show();
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
    if (python && !python.killed) {
      python.kill('SIGTERM');
      setTimeout(() => { if (python && !python.killed) python.kill('SIGKILL'); }, 3000);
    }
  });

  win.on('closed', () => { win = null; });
}

// ── IPC handlers for window control ──
ipcMain.on('window-minimize', () => win?.minimize());
ipcMain.on('window-maximize', () => {
  if (win?.isMaximized()) win.unmaximize(); else win?.maximize();
});
ipcMain.on('window-close', () => win?.close());
ipcMain.handle('window-is-maximized', () => win?.isMaximized() ?? false);

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

// ── App lifecycle ──
app.whenReady().then(async () => {
  killExistingBackend();
  await startBackend();
  log('Waiting for backend...');
  await waitForServer();
  log('Backend ready!');

  createAppMenu();
  createWindow();
  createTray();

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
  app.quit();
});

app.on('window-all-closed', () => {
  // Don't quit on window close (we hide to tray)
  // Only quit when forceQuit is set
});

app.on('before-quit', () => {
  forceQuit = true;
});
