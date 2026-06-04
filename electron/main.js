const { app, BrowserWindow } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const http = require('http');

const PORT = 5210;
const URL = `http://127.0.0.1:${PORT}`;

let python = null;
let win = null;

function log(msg) { console.log(`[CrabAgent] ${msg}`); }

function killExistingBackend() {
  try {
    const result = execSync(`lsof -ti:${PORT} 2>/dev/null || true`, { encoding: 'utf-8' });
    const pids = result.trim().split('\n').filter(Boolean);
    for (const pid of pids) {
      try {
        process.kill(Number(pid), 'SIGTERM');
        log(`Killed existing process ${pid} on port ${PORT}`);
      } catch (e) {
        // process may have already exited
      }
    }
    if (pids.length > 0) {
      // wait for port to be freed
      const deadline = Date.now() + 3000;
      while (Date.now() < deadline) {
        try {
          execSync(`lsof -ti:${PORT} 2>/dev/null`);
        } catch {
          break;
        }
      }
    }
  } catch (e) {
    // lsof not available, skip
  }
}

function resolvePath(cmd) {
  try {
    return execSync(`/bin/bash -l -c 'command -v ${cmd} 2>/dev/null'`, { encoding: 'utf-8' }).trim();
  } catch {
    return null;
  }
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, PYTHONUNBUFFERED: '1' };
    const crabagentBin = resolvePath('crabagent');
    const pythonBin = resolvePath('python3') || 'python3';

    log(`crabagent: ${crabagentBin || 'not found'}`);
    log(`python3: ${pythonBin}`);

    if (crabagentBin) {
      log('Starting backend via crabagent...');
      python = spawn(crabagentBin, ['--serve'], { stdio: 'pipe', env });
    } else {
      log('Starting backend via python3 -m crabagent.cli...');
      python = spawn(pythonBin, ['-m', 'crabagent.cli', '--serve'], { stdio: 'pipe', env });
    }

    python.on('error', (e) => { log(`Backend error: ${e.message}`); reject(e); });
    python.on('exit', (c) => log(`Backend exited (${c})`));
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
  killExistingBackend();
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
