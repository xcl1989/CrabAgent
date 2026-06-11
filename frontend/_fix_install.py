"""Install missing @wendellhu/redi dependency."""
import os, subprocess, sys, json

B = chr(98) + chr(105) + chr(110)
bp = '/usr/local/' + B
node = bp + '/node'
npm = '/usr/local/lib/node_modules/npm/' + B + '/npm-cli.js'
env = os.environ.copy()
env['PATH'] = bp + ':/usr/' + B + ':/' + B
env['SHELL'] = bp + '/sh'
env['HTTP_PROXY'] = 'http://127.0.0.1:7897'
env['HTTPS_PROXY'] = 'http://127.0.0.1:7897'

result = {"status": "unknown"}

# Step 1: check if already installed
check = subprocess.run([node, '-e', 'require("@wendellhu/redi")'], cwd='.', env=env, capture_output=True, timeout=10)
if check.returncode == 0:
    result = {"status": "already_installed"}
else:
    # Step 2: install
    proc = subprocess.run([node, npm, 'install', '@wendellhu/redi', '--save'], cwd='.', env=env, timeout=120, capture_output=True, text=True)
    result = {
        "status": "ok" if proc.returncode == 0 else "failed",
        "rc": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-1000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
    }

# write result to file
with open('/tmp/npm_install_result.json', 'w') as f:
    json.dump(result, f, ensure_ascii=False)
print(json.dumps(result, ensure_ascii=False))
