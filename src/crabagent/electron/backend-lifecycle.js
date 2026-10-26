const { execFile } = require('child_process');
const { promisify } = require('util');

function descendants(rows, root) {
  const children = new Map();
  for (const row of rows.trim().split('\n')) {
    const [pid, ppid] = row.trim().split(/\s+/).map(Number);
    if (!Number.isInteger(pid) || !Number.isInteger(ppid)) continue;
    if (!children.has(ppid)) children.set(ppid, []);
    children.get(ppid).push(pid);
  }
  const result = [];
  const seen = new Set([root]);
  const visit = (pid) => {
    for (const child of children.get(pid) || []) {
      if (seen.has(child)) continue;
      seen.add(child);
      visit(child);
      result.push(child);
    }
  };
  visit(root);
  return result;
}

async function stopBackend(child, {
  platform = process.platform,
  run = promisify(execFile),
  signal = process.kill.bind(process),
  delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  log = () => {},
} = {}) {
  if (!child?.pid) return;
  if (platform === 'win32') {
    await run('taskkill', ['/PID', String(child.pid), '/T', '/F'], { timeout: 5000 });
    return;
  }
  let children = [];
  try {
    const { stdout } = await run('/bin/ps', ['-axo', 'pid=,ppid='], { timeout: 2000 });
    children = descendants(stdout, child.pid);
  } catch (error) {
    log(`Cannot enumerate backend children: ${error.message}`);
  }
  const send = (pid, name) => {
    try { signal(pid, name); } catch (error) {
      if (error.code !== 'ESRCH') log(`Cannot signal ${pid}: ${error.message}`);
    }
  };
  // Snapshot before TERM: children may be reparented when the backend exits.
  for (const pid of children) send(pid, 'SIGTERM');
  if (child.exitCode === null && child.signalCode === null) send(child.pid, 'SIGTERM');
  await delay(3000);
  for (const pid of children) send(pid, 'SIGKILL');
  // ChildProcess.killed means a signal was sent, not that the process exited.
  if (child.exitCode === null && child.signalCode === null) send(child.pid, 'SIGKILL');
}

module.exports = { descendants, stopBackend };
