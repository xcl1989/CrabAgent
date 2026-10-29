"""Non-blocking, process-lifetime lock for a WeChat SQLite database."""

import errno
import os


def acquire_process_lock(path):
    # Never unlink the lock file: another process may already have it open.
    lock_file = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            # All contenders lock the same byte, regardless of file length.
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock_file.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise RuntimeError("Another WeChat polling process holds the database lock") from exc
        raise
    except BaseException:
        lock_file.close()
        raise
    return lock_file
