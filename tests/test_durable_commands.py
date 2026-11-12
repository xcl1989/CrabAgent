import os
import sqlite3
import subprocess
import sys

import pytest

from crabagent.core.agent import durable_commands as queue


def test_atomic_enqueue_and_scope(tmp_path):
    conn = sqlite3.connect(tmp_path / 'queue.db')
    queue.initialize(conn)
    conn.execute('BEGIN')
    queue.enqueue(conn, command_id='a', kind='group', record_id='g', user_id=1,
                  session_id='s', branch_id='b')
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM background_executor_command').fetchone()[0] == 0
    with pytest.raises(ValueError):
        queue.enqueue(conn, command_id='a', kind='group', record_id='g', user_id=True,
                      session_id='s', branch_id='b')


def test_cross_process_lease_fencing_and_no_replay(tmp_path):
    path = tmp_path / 'queue.db'
    conn = sqlite3.connect(path)
    queue.initialize(conn)
    queue.enqueue(conn, command_id='a', kind='task', record_id='t', user_id=1,
                  session_id='s', branch_id='b')
    conn.commit()
    code = '''import sqlite3, sys
from crabagent.core.agent import durable_commands as q
c=sqlite3.connect(sys.argv[1]); e=q.acquire(c, 'child', 30)
assert e == 1 and q.claim(c, 'child', e) == 'a'
c.commit()
'''
    subprocess.run([sys.executable, '-c', code, str(path)], check=True, env=os.environ.copy())
    assert queue.acquire(conn, 'parent', 10) is None
    conn.execute("UPDATE background_executor_lease SET expires=0 WHERE name='executor'")
    conn.commit()
    epoch = queue.acquire(conn, 'parent', 10)
    assert epoch == 2
    assert not queue.finish(conn, 'a', 'child', 1)
    assert not queue.renew(conn, 'child', 1, 10)
    assert queue.claim(conn, 'parent', epoch) is None
    assert conn.execute("SELECT status FROM background_executor_command WHERE id='a'").fetchone()[0] == 'interrupted'
    conn.commit()


def test_fenced_write_rolls_back_if_lease_expires(tmp_path):
    import time

    conn = sqlite3.connect(tmp_path / 'queue.db')
    queue.initialize(conn)
    conn.execute('CREATE TABLE business (value TEXT)')
    queue.enqueue(conn, command_id='a', kind='task', record_id='t', user_id=1,
                  session_id='s', branch_id='b')
    conn.commit()
    epoch = queue.acquire(conn, 'owner', 0.15)
    assert queue.claim(conn, 'owner', epoch) == 'a'
    conn.commit()

    def slow_write(c):
        c.execute("INSERT INTO business VALUES ('must roll back')")
        time.sleep(0.25)

    with pytest.raises(queue.LeaseLost):
        queue.fenced_write(conn, 'a', 'owner', epoch, slow_write)
    assert conn.execute('SELECT count(*) FROM business').fetchone()[0] == 0


def test_fenced_write_rejects_old_process_after_real_expiry(tmp_path):
    import time

    path = tmp_path / 'queue.db'
    conn = sqlite3.connect(path)
    queue.initialize(conn)
    conn.execute('CREATE TABLE business (value TEXT)')
    queue.enqueue(conn, command_id='a', kind='task', record_id='t', user_id=1,
                  session_id='s', branch_id='b')
    conn.commit()
    epoch = queue.acquire(conn, 'old', 0.2)
    assert queue.claim(conn, 'old', epoch) == 'a'
    conn.commit()
    time.sleep(0.3)
    code = '''import sqlite3, sys
from crabagent.core.agent import durable_commands as q
c=sqlite3.connect(sys.argv[1]); assert q.acquire(c, 'new', 30) == 2
'''
    subprocess.run([sys.executable, '-c', code, str(path)], check=True, env=os.environ.copy())
    with pytest.raises(queue.LeaseLost):
        queue.fenced_write(conn, 'a', 'old', epoch,
                           lambda c: c.execute("INSERT INTO business VALUES ('stale')"))
    assert conn.execute('SELECT count(*) FROM business').fetchone()[0] == 0
    assert conn.execute("SELECT status FROM background_executor_command WHERE id='a'").fetchone()[0] == 'interrupted'


def test_finish_with_write_atomic_and_fenced(tmp_path):
    conn = sqlite3.connect(tmp_path / 'atomic.db')
    queue.initialize(conn)
    conn.execute('CREATE TABLE business (value TEXT)')
    queue.enqueue(conn, command_id='one', kind='task', record_id='job',
                  user_id=1, session_id='session', branch_id='main')
    conn.commit()
    epoch = queue.acquire(conn, 'owner', 60)
    assert queue.claim(conn, 'owner', epoch) == 'one'
    conn.commit()
    with pytest.raises(RuntimeError):
        def fail(db):
            db.execute("INSERT INTO business VALUES ('partial')")
            raise RuntimeError('failure')
        queue.finish_with_write(conn, 'one', 'owner', epoch, fail)
    assert conn.execute('SELECT count(*) FROM business').fetchone()[0] == 0
    assert conn.execute('SELECT status FROM background_executor_command').fetchone()[0] == 'claimed'
    queue.finish_with_write(conn, 'one', 'owner', epoch,
                            lambda db: db.execute("INSERT INTO business VALUES ('complete')"))
    assert conn.execute('SELECT value FROM business').fetchone()[0] == 'complete'
    assert conn.execute('SELECT status FROM background_executor_command').fetchone()[0] == 'done'
    with pytest.raises(queue.LeaseLost):
        queue.finish_with_write(conn, 'one', 'owner', epoch, lambda db: None)
    conn.close()
