from __future__ import annotations

import os
import re
import sys

from crabagent.core.config import settings

IS_WINDOWS = sys.platform == "win32"

_DESTRUCTIVE_PATTERNS = [
    (r"rm\s+-rf\s+/(?:\s|$)", "rm -rf /"),
    (r"rm\s+-rf\s+/\*", "rm -rf /*"),
    (r"\bmkfs\b", "mkfs"),
    (r"dd\s+if=", "dd if="),
    (r"dd\s+of=/dev/", "dd of=/dev/"),
    (r"\bshutdown\b", "shutdown"),
    (r"\breboot\b", "reboot"),
    (r"\binit\s+[06]\b", "init 0/6"),
    (r":\(\)\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\bfork\s+bomb\b", "fork bomb"),
]

# Windows-specific dangerous patterns
if IS_WINDOWS:
    _DESTRUCTIVE_PATTERNS.extend([
        (r"\bformat\s+[a-z]:", "format drive"),
        (r"\bdiskpart\b", "diskpart"),
        (r"\bcd\s+\\.*\\Windows\\System32", "cd to System32"),
        (r"\bdel\s+/[fsq]\s+[a-z]:\\Windows", "delete Windows files"),
        (r"\brmdir\s+/s\s+/q\s+[a-z]:\\Windows", "rmdir Windows"),
        (r"\breg\s+delete\s+HKLM", "delete registry HKLM"),
    ])

_COMPILED = [re.compile(pat, re.IGNORECASE) for pat, _ in _DESTRUCTIVE_PATTERNS]
_LABELS = [label for _, label in _DESTRUCTIVE_PATTERNS]

if IS_WINDOWS:
    _CRITICAL_DIRS = (
        r"C:\Windows\System32",
        r"C:\Windows\System32\config",
        r"C:\Windows\System32\drivers",
        r"C:\Windows\System32\config\SAM",
        r"C:\Windows\System32\config\SYSTEM",
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"%WINDIR%",
        r"%SYSTEMROOT%",
    )
else:
    _CRITICAL_DIRS = (
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
        "/boot",
        "/usr/bin",
        "/usr/sbin",
        "/bin",
        "/sbin",
        "/System",
        "/Library/System",
    )

_DANGEROUS_PIPES = ("curl", "wget")

_PRIVILEGE_CMDS = (
    "sudo ",
    "su -",
    "chmod 777",
    "chmod 666",
    "chown root",
    # Windows elevated commands
    "runas ",
    "takeown ",
    "icacls ",
    "net user",
    "net localgroup",
    "reg add HKLM",
    "reg delete HKLM",
    "sc config",
    "bcdedit",
)

_BACKGROUND_PATTERNS = (
    re.compile(r"\bscreen\b"),
    re.compile(r"\btmux\b"),
    re.compile(r"\bdisown\b"),
)

# Capture the path operand of a shell redirect ("> file", ">> file", "2> file")
# and of "tee file".  The leading lookbehind avoids matching ">" that is part of
# a larger token (e.g. inside a quoted JSON payload like {"a":">b"}).
_REDIRECT_RE = re.compile(r"(?<![A-Za-z_])>>?\s*([^\s;&|()<>]+)")
_TEE_RE = re.compile(r"(?<![A-Za-z_])tee\s+(?:-[A-Za-z]+\s+)*([^\s;&|()<>]+)")


def _redirect_write_targets(command: str) -> list[str]:
    """Return the file paths a command writes to via ``>``, ``>>`` or ``tee``.

    Collecting only real redirect operands means a bare substring such as
    ``/bin`` inside ``$HOME/.hecom-cli/bin`` is never mistaken for a write to
    that directory.
    """
    targets = [m.group(1) for m in _REDIRECT_RE.finditer(command)]
    targets.extend(m.group(1) for m in _TEE_RE.finditer(command))
    return targets


def _critical_write_target(command: str) -> str | None:
    """Return the critical dir a command redirects into, if any."""
    for raw in _redirect_write_targets(command):
        target = os.path.expanduser(os.path.expandvars(raw)).strip("\"'")
        if not target or target.startswith("&"):
            continue
        target = re.sub(r"/{2,}", "/", target)
        for crit_dir in _CRITICAL_DIRS:
            base = crit_dir.rstrip("/")
            if target == base or target.startswith(base + "/"):
                return crit_dir
    return None


def validate_command(command: str) -> str | None:
    for compiled, label in zip(_COMPILED, _LABELS):
        if compiled.search(command):
            return f"Command blocked: contains dangerous pattern '{label}'"

    if settings.bash_block_privilege_escalation:
        lower = command.lower()
        for priv in _PRIVILEGE_CMDS:
            if priv in lower:
                return f"Command blocked: privilege escalation ('{priv.strip()}')"

    for pipe_cmd in _DANGEROUS_PIPES:
        pipe_pattern = f"{pipe_cmd} "
        if pipe_pattern in command and ("| sh" in command or "| bash" in command):
            return f"Command blocked: remote code execution via pipe ('{pipe_cmd}... | sh')"

    crit_target = _critical_write_target(command)
    if crit_target:
        return f"NEED_CONFIRM:writing to critical system path '{crit_target}'"

    if "> /dev/sd" in command or "> /dev/hd" in command:
        return "Command blocked: direct write to block device"

    # Windows block device write detection
    lower_for_block = command.lower()
    if r"\\.\physicaldrive" in lower_for_block or r"\\\\.\physicaldrive" in lower_for_block:
        return "Command blocked: direct write to physical drive"

    if settings.bash_block_background:
        for bg_pat in _BACKGROUND_PATTERNS:
            if bg_pat.search(command):
                return "Command blocked: background process not allowed"

    return None


def truncate_output(output: str, max_length: int | None = None) -> str:
    limit = max_length or settings.bash_max_output_length
    if len(output) <= limit:
        return output
    half = limit // 2
    return output[:half] + f"\n\n... [truncated {len(output) - limit} chars] ...\n\n" + output[-half:]
