# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for CrabAgent --serve mode.
Target: standalone binary in dist/crabagent-backend/
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ── Package-relative paths (works for both source and pip-installed) ──
import crabagent as _crabagent
_CRABAGENT_ROOT = Path(os.path.dirname(_crabagent.__file__))
_ICON_DIR = _CRABAGENT_ROOT / "electron" / "build"
if sys.platform == "win32":
    _icon = str(_ICON_DIR / "icon.ico") if (_ICON_DIR / "icon.ico").exists() else None
elif sys.platform == "darwin":
    _icon = str(_ICON_DIR / "icon.png") if (_ICON_DIR / "icon.png").exists() else None
else:
    _icon = None

block_cipher = None

# ── Project paths ──────────────────────────────────────────────
# PyInstaller spec doesn't have __file__, use cwd
PROJECT_ROOT = Path(os.getcwd())
SRC = PROJECT_ROOT / "src"
STATIC = SRC / "crabagent" / "static"

# ── Exclude massive unnecessary packages ───────────────────────
EXCLUDES = [
    # GUIs not needed
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    # Test/dev
    "unittest", "test", "pytest", "_pytest",
    # Python packaging (not needed at runtime)
    "pip", "setuptools", "distlib", "wheel",
    # IDLE
    "idlelib", "lib2to3", "turtledemo",
    # Docs / data
    "pydoc_data", "pydoc",
    # Browser automation (not needed in serve mode)
    "playwright", "selenium",
    # Scientific computing (not used)
    "numpy", "pandas", "matplotlib", "scipy", "sklearn",
    "PIL", "Pillow", "cv2", "opencv",
    # ML frameworks (not used)
    "tensorflow", "torch", "torchvision", "torchaudio", "keras",
    # Cloud (not used)
    "boto3", "botocore", "azure", "google.cloud",
    # Network debugging
    "tornado", "django", "flask",
    # Email (keep because pkg_resources needs it)
    # ML frameworks (not used — litellm calls remote APIs, no local inference)
    "transformers", "onnxruntime", "torch",
    "tensorflow", "keras", "tf2onnx",
    # Database drivers not used (SQLite only)
    "psycopg2", "MySQLdb", "_mysql_connector",
    # HuggingFace hub (not needed without transformers)
    "hf_xet", "huggingface_hub",
    # Unnecessary stdlib
    "xml.etree.cElementTree",  # use xml.etree.ElementTree instead
    "dbm", "dbm.dumb", "dbm.gnu", "dbm.ndbm",
    "msilib", "msvcrt", "win32api", "win32com",
    "turtle", "turtledemo",
    "webbrowser",
    "pdb", "profile", "pstats", "cProfile",
    "audiodev", "audioop", "imghdr",
    "nis", "ossaudiodev", "sndhdr", "spwd",
    "tabnanny", "this", "antigravity",
    "uu", "xdrlib", "pyclbr",
    "filecmp", "fileinput",
    "wave", "wave", "chunk", "aifc", "sunau",
    "nis",
    # Cryptography backends (keep all — jose needs openssl for JWT signing)
    # "cryptography.hazmat.backends.openssl",
    # MCP / dev
    "IPython", "jupyter", "notebook", "ipykernel",
    "debugpy", "pydevd",
]

# ── Platform-specific exclusions ───────────────────────────────
# On Windows, some modules in the exclude list are actually needed
# (msvcrt, win32api, win32com, msilib). Remove them so PyInstaller
# keeps them bundled.
if sys.platform == "win32":
    _WIN_SAFE = {"msvcrt", "win32api", "win32com", "msilib"}
    EXCLUDES = [x for x in EXCLUDES if x not in _WIN_SAFE]

# ── Hidden imports (dynamic imports PyInstaller can't see) ─────
HIDDEN_IMPORTS = [
    # Serve mode
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.middleware",
    "uvicorn.middleware.proxy_headers",
    "starlette",
    "starlette.applications",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    "starlette.responses",
    "starlette.staticfiles",
    "starlette.requests",
    "fastapi",
    "fastapi.routing",
    "fastapi.openapi",
    "fastapi.openapi.utils",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    # API routers (imported dynamically in create_app)
    "crabagent.serve.api.agent",
    "crabagent.serve.api.auth",
    "crabagent.serve.api.branch",
    "crabagent.serve.api.confirm",
    "crabagent.serve.api.event",
    "crabagent.serve.api.files",
    "crabagent.serve.api.input",
    "crabagent.serve.api.mcp_server",
    "crabagent.serve.api.memory",
    "crabagent.serve.api.message",
    "crabagent.serve.api.molt",
    "crabagent.serve.api.notification",
    "crabagent.serve.api.prompt",
    "crabagent.serve.api.provider",
    "crabagent.serve.api.replay",
    "crabagent.serve.api.scheduled_task",
    "crabagent.serve.api.session",
    "crabagent.serve.api.settings",
    "crabagent.serve.api.todo",
    # Serve services
    "crabagent.serve.services",
    "crabagent.serve.services.persistence",
    "crabagent.serve.services.conversation",
    "crabagent.serve.services.message",
    "crabagent.serve.services.auth",
    "crabagent.serve.scheduler",
    "crabagent.serve.deps",
    "crabagent.serve.app",
    # Core modules
    "crabagent.core.database",
    "crabagent.core.config",
    "crabagent.core.event",
    "crabagent.core.provider_store",
    "crabagent.core.auth_utils",
    "crabagent.core.project_memory",
    "crabagent.core.tool_loader",
    # Agent tools (dynamically imported)
    "crabagent.core.agent.tools",
    "crabagent.core.agent.tools.bash",
    "crabagent.core.agent.tools.edit",
    "crabagent.core.agent.tools.glob",
    "crabagent.core.agent.tools.grep",
    "crabagent.core.agent.tools.image",
    "crabagent.core.agent.tools.read",
    "crabagent.core.agent.tools.web",
    "crabagent.core.agent.tools.write",
    "crabagent.core.agent.tools.registry",
    "crabagent.core.agent.tools.memory",
    "crabagent.core.agent.tools.custom_tool",
    "crabagent.core.agent.tools.sandbox",
    "crabagent.core.agent.tools.scheduled_task",
    "crabagent.core.agent.tools.agent",
    "crabagent.core.agent.tools.shared",
    "crabagent.core.agent.tools.browser",
    "crabagent.core.agent.tools.browser_dom",
    # Agent modules
    "crabagent.core.agent.context",
    "crabagent.core.agent.loop",
    "crabagent.core.agent.compress",
    "crabagent.core.agent.reflect",
    "crabagent.core.agent.agents",
    "crabagent.core.agent.token_limits",
    "crabagent.core.agent.run_recorder",
    "crabagent.core.agent.middlewares",
    "crabagent.core.agent.middlewares.compress_middleware",
    "crabagent.core.agent.middlewares.reflect_middleware",
    "crabagent.core.agent.middlewares.title_middleware",
    "crabagent.core.agent.agent_switch",
    # Skill loader
    "crabagent.core.agent.skill",
    "crabagent.core.agent.skill.loader",
    # MCP
    "crabagent.core.mcp",
    "crabagent.core.mcp.client",
    "crabagent.core.mcp.tools",
    # Molt
    "crabagent.core.molt",
    "crabagent.core.molt.store",
    "crabagent.core.molt.snapshot",
    "crabagent.core.molt.rollback",
    "crabagent.core.molt.tools",
    # Todo
    "crabagent.core.todo",
    "crabagent.core.todo.store",
    "crabagent.core.todo.tools",
    # CLI
    "crabagent.cli",
    "crabagent.cli.tui",
    "crabagent.cli.tui2",
    # Libraries
    "rich",
    "rich.markdown",
    "rich.live",
    "rich.text",
    "rich.console",
    "rich.panel",
    "prompt_toolkit",
    "sqlalchemy",
    "sqlalchemy.sql",
    "sqlalchemy.orm",
    "sqlalchemy.ext.asyncio",
    "aiosqlite",
    "apscheduler",
    "apscheduler.triggers",
    "apscheduler.triggers.cron",
    "apscheduler.triggers.interval",
    "apscheduler.executors",
    "apscheduler.executors.asyncio",
    "apscheduler.jobstores",
    "apscheduler.jobstores.memory",
    "mcp",
    "httpx",
    "httpx_sse",
    "lxml",
    "lxml.etree",
    "ddgs",
    "passlib",
    "passlib.hash",
    "bcrypt",
    "jose",
    "jose.jwt",
    "jose.backends",
    "jose.backends.cryptography_backend",
    "litellm",
    # Only the critical hidden imports that PyInstaller can't auto-discover.
    # DO NOT use collect_submodules('litellm') — it pulls 500+ modules and makes
    # the frozen binary extremely slow to start (~15s vs ~3s).
    "litellm.litellm_core_utils.tokenizers",
    "litellm.litellm_core_utils.token_counter",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "pydantic",
    "pydantic_settings",
]

# ── Data files: static frontend assets ─────────────────────────
DATAS = []
if STATIC.exists():
    for f in STATIC.rglob("*"):
        if f.is_file():
            rel = f.relative_to(SRC)
            DATAS.append((str(f), str(rel.parent)))

# Also bundle VERSION file for version resolution in frozen context
for _vp in [SRC / "crabagent" / "VERSION", SRC / "VERSION"]:
    if _vp.exists():
        DATAS.append((str(_vp), "crabagent"))
        break

# ── litellm: all data files via collect_data_files (JSON, YAML, etc.) ──
_litellm_datas = collect_data_files('litellm', include_py_files=False)
DATAS.extend(_litellm_datas)
print(f"[spec] Collected {len(_litellm_datas)} litellm data files")

# ── crabagent: i18n JSON files for agent switch / system prompt translations ──
_I18N_DIR = _CRABAGENT_ROOT / "core" / "i18n"
_i18n_count = 0
if _I18N_DIR.exists():
    for _f in _I18N_DIR.glob("*.json"):
        DATAS.append((str(_f), "crabagent/core/i18n"))
        _i18n_count += 1
print(f"[spec] Collected {_i18n_count} i18n translation files")

# ── Analysis ───────────────────────────────────────────────────
a = Analysis(
    [str(SRC / "crabagent" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SRC / "crabagent" / "runtime_hooks.py")],
    excludes=EXCLUDES,
    noarchive=False,
)

# ── PYZ ────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── EXE (scripts only — binaries/datas go in COLLECT for onedir) ──
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="crabagent-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

# ── COLLECT (onedir: files on disk — no decompression overhead at startup) ──
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    name="crabagent-backend",
)

# ── macOS .app bundle ────────────────────────────────────────
app = BUNDLE(
    coll,
    name="CrabAgent.app",
    icon=str(_ICON_DIR / "icon.png") if sys.platform == "darwin" and (_ICON_DIR / "icon.png").exists() else None,
    bundle_identifier="com.crabagent.app",
    info_plist={
        "CFBundleShortVersionString": _crabagent.__version__,
        "CFBundleVersion": _crabagent.__version__,
        "CFBundleName": "CrabAgent",
        "CFBundleDisplayName": "CrabAgent",
    },
)
