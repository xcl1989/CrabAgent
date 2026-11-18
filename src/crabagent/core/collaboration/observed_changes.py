"""Detect changes to files previously read by this agent; this is not a lock."""

from pathlib import Path

from crabagent.core.collaboration.write_coordinator import file_version


def changed_observed_files(context) -> list[str]:
    changed = []
    for raw_path, observed in dict(context.metadata.get("_file_versions", {})).items():
        try:
            if file_version(Path(raw_path)) != observed:
                changed.append(raw_path)
        except OSError:
            changed.append(raw_path)
    return sorted(changed)
