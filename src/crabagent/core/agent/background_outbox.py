"""Transactional primitives for a future UI-only background result inbox.

These helpers do not authenticate callers. The caller must authorize the exact
user/session/branch scope in the same transaction before invoking them.
"""
from sqlalchemy import select, update

from crabagent.core import database as db


async def authorize(conn, group_id, scope):
    """Opt in a live group; callers must authenticate the user's action."""
    user, session, branch = scope
    # Serialize authorization against finalization and revocation using a write.
    changed = await conn.execute(update(db.BackgroundGroup).where(
        db.BackgroundGroup.id == group_id, db.BackgroundGroup.user_id == user,
        db.BackgroundGroup.session_id == session, db.BackgroundGroup.branch_id == branch,
        db.BackgroundGroup.status.in_(("queued", "running")),
        select(db.Conversation.id).where(
            db.Conversation.user_id == user, db.Conversation.session_id == session,
            db.Conversation.active_branch == branch,
        ).exists(),
    ).values(updated_at=db.BackgroundGroup.updated_at))
    if not changed.rowcount:
        raise ValueError("Active group not found")
    existing = await conn.get(db.BackgroundDelivery, group_id)
    if existing:
        if existing.status != "revoked":
            raise ValueError("Delivery already authorized")
        existing.status = "authorized"
        existing.terminal_status = ""
        existing.acknowledged_at = None
    else:
        conn.add(db.BackgroundDelivery(group_id=group_id, user_id=user, session_id=session,
                                       branch_id=branch, status="authorized"))
    await conn.flush()


async def revoke(conn, group_id, scope):
    user, session, branch = scope
    changed = await conn.execute(update(db.BackgroundDelivery).where(
        db.BackgroundDelivery.group_id == group_id, db.BackgroundDelivery.user_id == user,
        db.BackgroundDelivery.session_id == session, db.BackgroundDelivery.branch_id == branch,
        db.BackgroundDelivery.status.in_(("authorized", "ready")),
        select(db.Conversation.id).where(db.Conversation.user_id == user,
            db.Conversation.session_id == session, db.Conversation.active_branch == branch).exists(),
    ).values(status="revoked"))
    return bool(changed.rowcount)


async def finalize(conn, group_id, expected_status, status):
    """Change group status and publish its reference in the caller's transaction."""
    if status not in ("succeeded", "failed", "cancelled", "interrupted"):
        raise ValueError("Not a terminal status")
    changed = await conn.execute(update(db.BackgroundGroup).where(
        db.BackgroundGroup.id == group_id, db.BackgroundGroup.status == expected_status,
    ).values(status=status, updated_at=db.utcnow()))
    if changed.rowcount:
        await conn.execute(update(db.BackgroundDelivery).where(
            db.BackgroundDelivery.group_id == group_id,
            db.BackgroundDelivery.status == "authorized",
        ).values(status="ready", terminal_status=status))
    return bool(changed.rowcount)


async def acknowledge(conn, group_id, scope):
    """Persist an idempotent receipt without consuming the UI-visible record."""
    user, session, branch = scope
    conditions = (db.BackgroundDelivery.group_id == group_id,
                  db.BackgroundDelivery.user_id == user,
                  db.BackgroundDelivery.session_id == session,
                  db.BackgroundDelivery.branch_id == branch)
    await conn.execute(update(db.BackgroundDelivery).where(
        *conditions, db.BackgroundDelivery.status == "ready",
        db.BackgroundDelivery.acknowledged_at.is_(None),
    ).values(acknowledged_at=db.utcnow()))
    return await conn.scalar(select(db.BackgroundDelivery).where(
        *conditions, db.BackgroundDelivery.status == "ready")) is not None
