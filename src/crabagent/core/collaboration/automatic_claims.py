"""Coordinate managed file writes without requiring manual claim management."""

import json
import os
import uuid
from pathlib import Path

from sqlalchemy import select, text, update

from crabagent.core.database import (
    CollaborationBinding,
    CollaborationEntry,
    CollaborationProject,
    Conversation,
    async_session_factory,
)

_LOCKS: dict[int, tuple[int, Path]] = {}
_PREFIX = "Automatic managed write: "


def _try_lock(fd: int) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


def _new_lock() -> tuple[str, int, Path]:
    root = Path.home() / ".crabagent" / "collaboration-claims"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = uuid.uuid4().hex
    path = root / token
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.write(fd, b"0")
    if not _try_lock(fd):
        os.close(fd)
        path.with_suffix(".pid").unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise OSError("Could not lock collaboration claim")
    return token, fd, path


def _stale_lock(token: str) -> bool:
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        return False
    path = Path.home() / ".crabagent" / "collaboration-claims" / token
    marker = path.with_suffix(".pid")
    if marker.exists():
        try:
            pid = json.loads(marker.read_text())["pid"]
            if not isinstance(pid, int) or pid <= 0:
                return False
            try:
                os.kill(pid, 0)
                return False
            except ProcessLookupError:
                pass
            except PermissionError:
                return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return True
    try:
        return _try_lock(fd)
    finally:
        os.close(fd)


def stale_run_batch_claim(content: str) -> bool:
    prefix = "Run batch claim: "
    if not content.startswith(prefix):
        return False
    token = content[len(prefix) :].split("\n", 1)[0]
    return _stale_lock(token)


async def acquire(context, raw_path: str) -> tuple[int | None, str | None]:
    if not raw_path:
        return None, None
    workspace = Path(context.workspace).resolve()
    path = Path(raw_path).expanduser()
    path = (workspace / path).resolve() if not path.is_absolute() else path.resolve()
    user = context.metadata.get("user_id")
    session = context.metadata.get("session_id")
    branch = context.metadata.get("branch_id") or "main"
    if not user or not session:
        return None, None
    # Prefer an existing project boundary; otherwise coordinate the exact file.
    parent = path if path.is_dir() else path.parent
    root = next((p for p in (parent, *parent.parents) if (p / ".git").exists()), None)
    token, lock_fd, lock_path = _new_lock()
    try:
        return await _acquire_locked(context, path, user, session, branch, root, token, lock_fd, lock_path)
    finally:
        if lock_fd not in (item[0] for item in _LOCKS.values()):
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)


async def _acquire_locked(context, path, user, session, branch, root, token, lock_fd, lock_path):
    async with async_session_factory() as db:
        await db.execute(text("BEGIN IMMEDIATE"))
        try:
            conversation = (
                await db.execute(
                    select(Conversation).where(Conversation.session_id == session, Conversation.user_id == user)
                )
            ).scalar_one_or_none()
            if not conversation:
                await db.rollback()
                return None, "Collaboration session is unavailable; managed write stopped."
            binding = await db.get(CollaborationBinding, session)
            if root is None and binding and binding.user_id == user:
                bound = await db.get(CollaborationProject, binding.project_id)
                if bound and path.is_relative_to(Path(bound.workspace).resolve()):
                    root = Path(bound.workspace).resolve()
            if root is None:
                root = path
                scope = path.name
            elif path == root:
                scope = "."
            else:
                scope = str(path.relative_to(root))
            project = (
                await db.execute(
                    select(CollaborationProject).where(
                        CollaborationProject.user_id == user, CollaborationProject.workspace == str(root)
                    )
                )
            ).scalar_one_or_none()
            if not project:
                project = CollaborationProject(
                    user_id=user, workspace=str(root), name=root.name[:200] or str(root)[:200]
                )
                db.add(project)
                await db.flush()
            rows = await db.execute(
                select(CollaborationEntry, CollaborationProject)
                .join(CollaborationProject, CollaborationEntry.project_id == CollaborationProject.id)
                .where(
                    CollaborationEntry.user_id == user,
                    CollaborationProject.user_id == user,
                    CollaborationEntry.kind == "claim",
                    CollaborationEntry.state == "active",
                )
            )
            competing = []
            covered = False
            for existing, owner in rows:
                if (existing.content.startswith(_PREFIX) and _stale_lock(existing.content[len(_PREFIX) :])) or (
                    stale_run_batch_claim(existing.content)
                ):
                    existing.state = "closed"
                    continue
                owner_root = Path(owner.workspace)
                existing_path = (
                    owner_root if owner_root.is_file() or owner_root == path else owner_root / existing.scope
                )
                existing_path = existing_path.resolve()
                if existing.session_id == session and existing.branch_id == branch:
                    goal_claim = existing.content.startswith("Goal batch claim: ")
                    own_goal = existing.content.startswith(f"Goal batch claim: {context.metadata.get('goal_id')}\n")
                    if not goal_claim or own_goal:
                        if not existing.content.startswith(_PREFIX) and path.is_relative_to(existing_path):
                            covered = True
                        continue
                if path == existing_path or path.is_relative_to(existing_path) or existing_path.is_relative_to(path):
                    competing.append(existing.id)
            if competing:
                await db.rollback()
                return None, f"File is claimed by another session: {competing}. Retry after coordination."
            if covered:
                await db.commit()
                return None, None
            entry = CollaborationEntry(
                user_id=user,
                project_id=project.id,
                session_id=session,
                branch_id=branch,
                kind="claim",
                scope=scope,
                content=_PREFIX + token,
            )
            db.add(entry)
            await db.flush()
            entry_id = entry.id
            await db.commit()
            _LOCKS[entry_id] = (lock_fd, lock_path)
            return entry_id, None
        except BaseException:
            await db.rollback()
            raise


async def finish(context, entry_id: int, success: bool, tool: str) -> None:
    user = context.metadata.get("user_id")
    session = context.metadata.get("session_id")
    branch = context.metadata.get("branch_id") or "main"
    try:
        async with async_session_factory() as db:
            entry = await db.get(CollaborationEntry, entry_id)
            if not entry or entry.user_id != user or entry.session_id != session or entry.branch_id != branch:
                return
            await db.execute(update(CollaborationEntry).where(CollaborationEntry.id == entry_id).values(state="closed"))
            if success:
                db.add(
                    CollaborationEntry(
                        user_id=user,
                        project_id=entry.project_id,
                        session_id=session,
                        branch_id=branch,
                        kind="handoff",
                        scope=entry.scope,
                        content=f"Managed write completed: {tool} {entry.scope}.",
                    )
                )
            await db.commit()
    finally:
        _release_lock(entry_id)


def persist_background_pid(entry_id: int, pid: int) -> None:
    lock = _LOCKS.get(entry_id)
    if not lock or pid <= 0:
        raise ValueError("Background claim or PID unavailable")
    marker = lock[1].with_suffix(".pid")
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({"pid": pid}, stream)
        stream.flush()
        os.fsync(stream.fileno())


def _release_lock(entry_id: int) -> None:
    lock = _LOCKS.pop(entry_id, None)
    if lock:
        fd, path = lock
        os.close(fd)
        path.with_suffix(".pid").unlink(missing_ok=True)
        path.unlink(missing_ok=True)
