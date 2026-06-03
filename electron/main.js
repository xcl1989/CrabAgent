const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

const PORT = 5210;
const URL = `http://127.0.0.1:${PORT}`;

let python = null;
let win = null;

function log(msg) { console.log(`[CrabAgent] ${msg}`); }

function startBackend() {
  return new Promise((resolve, reject) => {
    // Try direct command first, then python3 module
    const cmd = 'crabagent';
    const fallbackCmd = 'python3';
    const fallbackArgs = ['-m', 'crabagent.cli', '--serve'];
    const args = ['--serve'];

    log('Starting backend...');
    python = spawn(cmd, args, {
      stdio: 'pipe',
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
    python.on('error', () => {
      log('crabagent command not found, trying python3...');
      python = spawn(fallbackCmd, fallbackArgs, {
        stdio: 'pipe',
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
      });
      python.on('error', reject);
      python.on('exit', (c) => log(`Python done (${c})`));
      python.stdout.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
      python.stderr.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
      setTimeout(resolve, 500);
    });
    python.on('exit', (c) => log(`Python done (${c})`));
    python.stdout.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
    python.stderr.on('data', (d) => d.toString().split('\n').filter(Boolean).forEach((l) => log(`[py] ${l}`)));
    setTimeout(resolve, 500);
  });
}

function waitForServer(url, maxWait = 60000) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    function check() {
      http.get(url, (r) => {
        if (r.statusCode === 200) resolve();
        else retry();
      }).on('error', retry);
      function retry() {
        if (Date.now() - t0 > maxWait) reject(new Error('Timeout'));
        else setTimeout(check, 500);
      }
    }
    check();
  });
}

async function main() {
  await startBackend();
  log('Waiting for backend...');
  await waitForServer(`${URL}/api/health`);
  log('Backend ready!');

  win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  win.loadURL(URL);

  // Auto-login: after DOM ready, inject token and reload
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
  win.on('closed', () => { win = null; });
}

app.whenReady().then(main).catch((e) => { log(`Error: ${e.message}`); app.quit(); });
app.on('window-all-closed', () => {
  if (python && !python.killed) {
    python.kill('SIGTERM');
    setTimeout(() => { if (python && !python.killed) python.kill('SIGKILL'); }, 3000);
  }
  app.quit();
});
