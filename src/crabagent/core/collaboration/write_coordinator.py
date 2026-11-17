"""Cooperative file version checks for participating local writers.

This does not prevent writes by external applications or shell commands.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path


class WriteConflict(Exception):
    """The target no longer matches the version used to prepare the edit."""

    def __init__(self, message: str, candidate_path: Path | None = None):
        super().__init__(message)
        self.candidate_path = candidate_path


def save_conflict_candidate(content: bytes, suffix: str = "") -> Path:
    """Retain a private candidate for manual recovery, never alongside the target."""
    root = Path.home() / ".crabagent" / "collaboration-conflicts"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    suffix = suffix if suffix in {".docx", ".xlsx", ".pptx", ".txt", ".md"} else ".bin"
    path = root / (uuid.uuid4().hex + suffix)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
    return path


def version_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def file_version(path: Path) -> str:
    try:
        return version_bytes(path.read_bytes())
    except FileNotFoundError:
        return "missing"


@contextmanager
def _resource_lock(path: Path, lock_root: Path):
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256(os.fsencode(str(path.resolve()))).hexdigest()
    lock_path = lock_root / (key + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def replace_if_version(path: Path, content: bytes, expected_version: str, *, lock_root: Path) -> str:
    """Replace a file if its content matches, serializing cooperating writers.

    External writers can still race between the final check and os.replace.
    The caller retains the candidate content when a conflict is raised.
    """
    path = path.resolve()
    with _resource_lock(path, lock_root):
        if file_version(path) != expected_version:
            raise WriteConflict(
                f"File changed since it was read: {path}", save_conflict_candidate(content, path.suffix)
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
        fd, temp_name = tempfile.mkstemp(prefix=".crabagent-write-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as temp:
                temp.write(content)
                temp.flush()
                os.fsync(temp.fileno())
            if existing_mode is not None:
                shutil.copystat(path, temp_name, follow_symlinks=True)
                os.utime(temp_name, None)
                os.chmod(temp_name, existing_mode)
            if file_version(path) != expected_version:
                raise WriteConflict(
                    f"File changed while preparing the write: {path}", save_conflict_candidate(content, path.suffix)
                )
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return version_bytes(content)
