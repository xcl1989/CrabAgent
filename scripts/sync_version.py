#!/usr/bin/env python3
"""同步版本号：从 pyproject.toml 读取版本，写入 Electron 的 package.json 文件。"""
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_pyproject_version() -> str:
    pyproject = PROJECT_ROOT / "pyproject.toml"
    content = pyproject.read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not m:
        print("ERROR: Cannot find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return m.group(1)


def update_package_json(path: Path, version: str) -> bool:
    if not path.exists():
        print(f"SKIP: {path} not found")
        return False
    data = json.loads(path.read_text())
    old = data.get("version", "")
    if old == version:
        return False
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"UPDATED: {path.relative_to(PROJECT_ROOT)}  {old} → {version}")
    return True


def main():
    version = read_pyproject_version()
    changed = False
    for pkg in [
        PROJECT_ROOT / "electron" / "package.json",
        PROJECT_ROOT / "src" / "crabagent" / "electron" / "package.json",
    ]:
        if update_package_json(pkg, version):
            changed = True
    if not changed:
        print(f"All package.json already at v{version}, nothing to update.")


if __name__ == "__main__":
    main()
