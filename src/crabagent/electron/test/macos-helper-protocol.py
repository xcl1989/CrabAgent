#!/usr/bin/env python3
"""M0 protocol test for the macOS computer-use helper (one-shot invocation mode).

Usage: python3 macos-helper-protocol.py /path/to/macos-helper
Covers: secret enforcement, command allowlist, malformed input, size limit,
permissions preflight, window listing. Run after `swiftc -O -o helper helper/macos-helper.swift`.
"""
import json
import os
import secrets
import subprocess
import sys
import tempfile


def main() -> int:
    helper = sys.argv[1]
    secret = secrets.token_hex(16)
    failures = []

    def run_request(request, use_secret=None):
        if use_secret is None:
            use_secret = secret
        payload = dict(request)
        if use_secret:
            payload["secret"] = use_secret
        fd, path = tempfile.mkstemp(prefix="crab-helper-req-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            args = [helper, "--request-file", path]
            if use_secret:
                args += ["--secret", use_secret]
            p = subprocess.run(args, capture_output=True, text=True, timeout=15)
            try:
                return json.loads(p.stdout)
            except json.JSONDecodeError:
                return {"ok": False, "error": f"unparseable output: {p.stdout[:120]!r}"}
        finally:
            os.unlink(path)

    def check(name, condition, detail=""):
        if not condition:
            failures.append(f"{name}: {str(detail)[:140]}")

    r0 = run_request({"command": "permissions"})
    check("permissions preflight", r0.get("ok") and isinstance(r0["permissions"]["accessibility"], bool)
          and isinstance(r0["permissions"]["screenRecording"], bool), r0)

    # Launch with the real secret but a request whose secret field is wrong.
    fd, wrong_path = tempfile.mkstemp(prefix="crab-helper-req-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump({"secret": "wrong", "command": "permissions"}, f)
    p = subprocess.run([helper, "--request-file", wrong_path, "--secret", secret], capture_output=True, text=True, timeout=15)
    os.unlink(wrong_path)
    try:
        r1 = json.loads(p.stdout)
    except json.JSONDecodeError:
        r1 = {"ok": False, "error": f"unparseable: {p.stdout[:80]!r}"}
    check("bad secret rejected", r1 == {"ok": False, "error": "bad request or secret"}, r1)

    r2 = run_request({"command": "windows"})
    check("windows listing", r2.get("ok") and isinstance(r2.get("windows"), list) and len(r2["windows"]) >= 1, r2)
    if r2.get("ok"):
        for w in r2["windows"]:
            check("window schema", all(k in w for k in ("windowId", "pid", "bundleId", "bounds")), w)

    r3 = run_request({"command": "observe"})
    # Environment-adaptive: without AX → clean permission refusal; with AX → argument validation.
    check("observe gate", r3.get("ok") is False
          and ("permission denied" in r3.get("error", "") or "bad request" in r3.get("error", "")), r3)

    r4 = run_request({"command": "launchctl-user-do-my-bidding"})
    check("unknown command refused", r4.get("ok") is False, r4)

    r5 = run_request({"command": "permissions", "extra_field": "a" * 400 * 1024})
    check("size limit", r5 == {"ok": False, "error": "request too large"}, str(r5)[:100])

    # M1 input commands are opt-in gated inside the helper itself.
    r8 = run_request({"command": "click", "x": 10, "y": 10})
    check("click without opt-in refused", r8.get("ok") is False and "opt-in" in r8.get("error", ""), r8)
    r9 = run_request({"command": "type", "text": "hi"})
    check("type without opt-in refused", r9.get("ok") is False and "opt-in" in r9.get("error", ""), r9)
    r10 = run_request({"command": "capture"})
    check("capture preflight runs", isinstance(r10, dict), r10)

    # request file that is not the JSON we signed off on
    fd, path = tempfile.mkstemp(prefix="crab-helper-req-", suffix=".json")
    os.write(fd, b"not json")
    os.close(fd)
    p = subprocess.run([helper, "--request-file", path, "--secret", secret], capture_output=True, text=True, timeout=15)
    os.unlink(path)
    try:
        check("malformed json refused", json.loads(p.stdout) == {"ok": False, "error": "bad request or secret"}, p.stdout)
    except json.JSONDecodeError:
        check("malformed json refused", False, p.stdout)

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("windows seen (pre-TCC):", len(r2["windows"]))
    print("HELPER PROTOCOL TESTS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
