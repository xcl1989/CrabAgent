"""Experimental SQLite command journal; not connected to the executor.

Only opaque, already-authorized record IDs belong here.  Callers must insert the
command in the same transaction as the authorized business record.  A lease
fences journal writes, not network requests or existing executor state writes.
"""
from __future__ import annotations

import sqlite3

# SQLite's clock is authoritative for all participants using this database.
_NOW = "((julianday('now') - 2440587.5) * 86400.0)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS background_executor_lease (
    name TEXT PRIMARY KEY, owner TEXT NOT NULL, epoch INTEGER NOT NULL,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS background_executor_command (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, record_id TEXT NOT NULL,
    user_id INTEGER NOT NULL, session_id TEXT NOT NULL, branch_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'claimed', 'done', 'interrupted')),
    owner TEXT, epoch INTEGER,
    UNIQUE(kind, record_id)
);
"""


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def enqueue(conn: sqlite3.Connection, *, command_id: str, kind: str, record_id: str,
            user_id: int, session_id: str, branch_id: str) -> None:
    """Insert only; the caller owns authorization, transaction and commit."""
    if (kind not in {'task', 'group', 'semantic_summary'} or not command_id or
            not record_id or isinstance(user_id, bool) or not isinstance(user_id, int) or
            user_id <= 0 or not session_id or not branch_id):
        raise ValueError('Invalid command scope or kind')
    conn.execute("INSERT INTO background_executor_command "
                 "(id, kind, record_id, user_id, session_id, branch_id, status) "
                 "VALUES (?, ?, ?, ?, ?, ?, 'queued')",
                 (command_id, kind, record_id, user_id, session_id, branch_id))


def acquire(conn: sqlite3.Connection, owner: str, ttl: float) -> int | None:
    if not owner or not 0 < ttl <= 300:
        raise ValueError('Invalid lease')
    # This transaction must commit before the returned token can be used.
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute(f"INSERT INTO background_executor_lease VALUES ('executor', ?, 1, {_NOW} + ?) "
                     f"ON CONFLICT(name) DO UPDATE SET owner=excluded.owner, "
                     f"epoch=background_executor_lease.epoch+1, expires=excluded.expires "
                     f"WHERE background_executor_lease.expires <= {_NOW}", (owner, ttl))
        changed = conn.execute('SELECT changes()').fetchone()[0]
        epoch = conn.execute("SELECT epoch FROM background_executor_lease WHERE name='executor'").fetchone()[0] if changed else None
        if changed:
            # A claimed command may have sent external effects: never replay it.
            conn.execute("UPDATE background_executor_command SET status='interrupted' WHERE status='claimed'")
        conn.commit()
        return epoch
    except BaseException:
        conn.rollback()
        raise


def renew(conn: sqlite3.Connection, owner: str, epoch: int, ttl: float) -> bool:
    if not 0 < ttl <= 300:
        raise ValueError('Invalid lease')
    cur = conn.execute(f"UPDATE background_executor_lease SET expires={_NOW}+? "
                       f"WHERE name='executor' AND owner=? AND epoch=? AND expires>{_NOW}",
                       (ttl, owner, epoch))
    return cur.rowcount == 1


def claim(conn: sqlite3.Connection, owner: str, epoch: int) -> str | None:
    """Claim a queued command only while the lease is current; caller commits."""
    row = conn.execute(f"UPDATE background_executor_command SET status='claimed', owner=?, epoch=? "
                       f"WHERE id=(SELECT id FROM background_executor_command WHERE status='queued' ORDER BY rowid LIMIT 1) "
                       f"AND EXISTS (SELECT 1 FROM background_executor_lease WHERE name='executor' "
                       f"AND owner=? AND epoch=? AND expires>{_NOW}) RETURNING id",
                       (owner, epoch, owner, epoch)).fetchone()
    return row[0] if row else None


def finish(conn: sqlite3.Connection, command_id: str, owner: str, epoch: int) -> bool:
    """Fence the acknowledgement; business state must be fenced in the same transaction."""
    cur = conn.execute(f"UPDATE background_executor_command SET status='done' WHERE id=? "
                       f"AND status='claimed' AND owner=? AND epoch=? AND EXISTS "
                       f"(SELECT 1 FROM background_executor_lease WHERE name='executor' "
                       f"AND owner=? AND epoch=? AND expires>{_NOW})",
                       (command_id, owner, epoch, owner, epoch))
    return cur.rowcount == 1


class LeaseLost(RuntimeError):
    """The executor no longer owns a live lease and claimed command."""


def _owns_claim(conn: sqlite3.Connection, command_id: str, owner: str, epoch: int) -> bool:
    return conn.execute(
        f"SELECT 1 FROM background_executor_command c "
        f"JOIN background_executor_lease l ON l.name='executor' "
        f"WHERE c.id=? AND c.status='claimed' AND c.owner=? AND c.epoch=? "
        f"AND l.owner=? AND l.epoch=? AND l.expires>{_NOW}",
        (command_id, owner, epoch, owner, epoch),
    ).fetchone() is not None


def fenced_write(conn: sqlite3.Connection, command_id: str, owner: str, epoch: int,
                 write) -> None:
    """Run a short SQLite write transaction fenced by a live claimed command.

    The callback must not commit, roll back, perform external I/O, or retain the
    connection. This experimental primitive is not wired into business writes.
    """
    if conn.in_transaction:
        raise ValueError('fenced_write requires a connection outside a transaction')
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not _owns_claim(conn, command_id, owner, epoch):
            raise LeaseLost('Executor lease or command claim is no longer valid')
        write(conn)
        if not conn.in_transaction:
            raise RuntimeError('fenced_write callback ended the transaction')
        if not _owns_claim(conn, command_id, owner, epoch):
            raise LeaseLost('Executor lease or command claim expired during write')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def finish_with_write(conn: sqlite3.Connection, command_id: str, owner: str,
                      epoch: int, write) -> None:
    """Commit a short business update and command acknowledgement together.

    This remains an experimental primitive; the existing executor does not use it.
    The callback must not commit, roll back, or perform external I/O.
    """
    def complete(transaction):
        write(transaction)
        if not finish(transaction, command_id, owner, epoch):
            raise LeaseLost('Executor lease or command claim is no longer valid')

    # The command changes to done inside this transaction, so verify its claim
    # immediately before acknowledgement instead of using fenced_write's postcheck.
    if conn.in_transaction:
        raise ValueError('finish_with_write requires a connection outside a transaction')
    conn.execute('BEGIN IMMEDIATE')
    try:
        if not _owns_claim(conn, command_id, owner, epoch):
            raise LeaseLost('Executor lease or command claim is no longer valid')
        complete(conn)
        if not conn.in_transaction:
            raise RuntimeError('finish_with_write callback ended the transaction')
        if not conn.execute(
            f"SELECT 1 FROM background_executor_lease WHERE name='executor' "
            f"AND owner=? AND epoch=? AND expires>{_NOW}", (owner, epoch)
        ).fetchone():
            raise LeaseLost('Executor lease expired during write')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
