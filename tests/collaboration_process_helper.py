from pathlib import Path

from crabagent.core.collaboration.write_coordinator import WriteConflict, replace_if_version


def process_write(path, version, content, lock_root, ready, start, results):
    ready.put("ready")
    if not start.wait(15):
        results.put("timeout")
        return
    try:
        replace_if_version(Path(path), content, version, lock_root=Path(lock_root))
        results.put("ok")
    except WriteConflict:
        results.put("conflict")
