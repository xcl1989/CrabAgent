import { execSync } from 'child_process';
try {
  const out = execSync('/usr/local/bin/npm install --ignore-scripts 2>&1', {
    cwd: import.meta.dirname,
    timeout: 180000,
    env: { ...process.env, PATH: '/usr/local/bin' },
    encoding: 'utf-8',
  });
  console.log(out.slice(-800));
} catch(e) {
  console.error(e.stdout?.slice(-800) || '');
  console.error(e.stderr?.slice(-800) || '');
  process.exit(1);
}
