#!/usr/local/bin/node
const { execSync } = require('child_process');
try {
  const result = execSync(
    '/usr/local/bin/npm install --ignore-scripts 2>&1',
    { cwd: __dirname, encoding: 'utf-8', timeout: 180000,
      env: { ...process.env, PATH: '/usr/local/bin' }
    }
  );
  console.log(result.slice(-1000));
} catch(e) {
  console.log(e.stdout?.slice(-1000) || '');
  console.log(e.stderr?.slice(-500) || '');
  process.exit(1);
}
