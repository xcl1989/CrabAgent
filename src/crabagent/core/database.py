from __future__ import annotations

import datetime
import time as _time
from collections.abc import AsyncGenerator

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crabagent.core.config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime.datetime:
    return datetime.datetime.now()


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extra: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    workspace: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    provider: Mapped[str] = mapped_column(String(100), default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    active_branch: Mapped[str] = mapped_column(String(32), default="main")
    agent: Mapped[str] = mapped_column(String(100), default="default")
    auto_titled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[str] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=True)
    reasoning_content: Mapped[str] = mapped_column(Text, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    branch_id: Mapped[str] = mapped_column(String(32), default="main")
    agent: Mapped[str] = mapped_column(String(100), default="default")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Molt(Base):
    __tablename__ = "molts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    molt_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    branch_id: Mapped[str] = mapped_column(String(32), default="main")
    description: Mapped[str] = mapped_column(String(500), default="")
    method: Mapped[str] = mapped_column(String(10), default="git")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    transport: Mapped[str] = mapped_column(String(20), nullable=False, default="stdio")
    command: Mapped[str] = mapped_column(Text, default="")
    args: Mapped[str] = mapped_column(Text, default="[]")
    url: Mapped[str] = mapped_column(Text, default="")
    env: Mapped[str] = mapped_column(Text, default="{}")
    headers: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_conversation_id: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    conversation_id: Mapped[str] = mapped_column(String(32), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(500), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    backstory: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    allow_delegation: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    icon: Mapped[str] = mapped_column(String(10), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    tools: Mapped[str] = mapped_column(Text, default="")
    tool_permissions: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SharedMemory(Base):
    __tablename__ = "shared_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), default="")
    category: Mapped[str] = mapped_column(String(50), default="")
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_session: Mapped[str] = mapped_column(String(32), default="")
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(10), default="")
    task_category: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaskRecord(Base):
    __tablename__ = "task_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    task_summary: Mapped[str] = mapped_column(String(200), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    elapsed: Mapped[float] = mapped_column(Float, default=0.0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    task_summary: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[float] = mapped_column(Float, default=_time.time)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[str | None] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[str | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


engine = create_async_engine(settings.db_url, echo=False, connect_args={"check_same_thread": False})
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def _ensure_workspace_dirs():
    from pathlib import Path

    ws = settings.workspace.resolve()
    if ws == Path("/"):
        ws = Path.home()
    base = ws / ".crabagent"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    skills_dir = base / "skills"
    if not skills_dir.exists():
        skills_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        from importlib.resources import files as _pkg_files

        try:
            bundled = _pkg_files("crabagent").joinpath("skills")
            if bundled.is_dir():
                for item in bundled.iterdir():
                    if item.is_dir():
                        shutil.copytree(str(item), str(skills_dir / item.name), dirs_exist_ok=True)
        except Exception:
            pass

    tools_dir = base / "tools"
    if not tools_dir.exists():
        tools_dir.mkdir(parents=True, exist_ok=True)
        sample = tools_dir / "hello.py"
        sample.write_text(
            'name = "hello"\n'
            'description = "Say hello — a sample custom tool. Edit or remove this file to add your own tools."\n'
            "parameters = {\n"
            '    "type": "object",\n'
            '    "properties": {\n'
            '        "name": {"type": "string", "description": "Name to greet"},\n'
            "    },\n"
            '    "required": ["name"],\n'
            "}\n"
            "requires_permission = True  # set to False to skip confirmation\n"
            "\n"
            "\n"
            "def run(name: str) -> str:\n"
            '    return f"Hello, {name}! Welcome to CrabAgent."\n'
        )


def _migrate_db_to_home():
    import logging
    import shutil
    from pathlib import Path

    logger = logging.getLogger(__name__)

    home_db = Path.home() / ".crabagent" / "crabagent.db"
    if home_db.exists():
        return

    cwd_db = Path.cwd() / "crabagent.db"
    if cwd_db.exists():
        home_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cwd_db, home_db)
        logger.info("Migrated database from %s to %s", cwd_db, home_db)


async def init_db() -> None:
    _ensure_workspace_dirs()
    _migrate_db_to_home()

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)

        result = await conn.execute(text("PRAGMA table_info(conversations)"))
        columns = [row[1] for row in result.fetchall()]
        if "tokens" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN tokens INTEGER DEFAULT 0"))
        if "active_branch" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN active_branch VARCHAR(32) DEFAULT 'main'"))
        if "agent" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN agent VARCHAR(100) DEFAULT 'default'"))
        if "auto_titled" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN auto_titled BOOLEAN DEFAULT 0"))
        if "provider" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN provider VARCHAR(100) DEFAULT ''"))

        result = await conn.execute(text("PRAGMA table_info(messages)"))
        columns = [row[1] for row in result.fetchall()]
        if "parent_id" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN parent_id INTEGER DEFAULT NULL"))
        if "branch_id" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN branch_id VARCHAR(32) DEFAULT 'main'"))
        if "agent" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN agent VARCHAR(100) DEFAULT 'default'"))

        result = await conn.execute(text("PRAGMA table_info(molts)"))
        columns = [row[1] for row in result.fetchall()]
        if "method" not in columns:
            await conn.execute(text("ALTER TABLE molts ADD COLUMN method VARCHAR(10) DEFAULT 'git'"))

        result = await conn.execute(text("PRAGMA table_info(todos)"))
        columns = [row[1] for row in result.fetchall()]
        if "task" not in columns:
            await conn.execute(text("ALTER TABLE todos ADD COLUMN task TEXT NOT NULL DEFAULT ''"))

        result = await conn.execute(text("PRAGMA table_info(agent_profiles)"))
        columns = [row[1] for row in result.fetchall()]
        if "icon" not in columns:
            await conn.execute(text("ALTER TABLE agent_profiles ADD COLUMN icon VARCHAR(10) DEFAULT ''"))
        if "is_default" not in columns:
            await conn.execute(text("ALTER TABLE agent_profiles ADD COLUMN is_default BOOLEAN DEFAULT 0"))
        if "tools" not in columns:
            await conn.execute(text("ALTER TABLE agent_profiles ADD COLUMN tools TEXT DEFAULT ''"))
        if "tool_permissions" not in columns:
            await conn.execute(text("ALTER TABLE agent_profiles ADD COLUMN tool_permissions TEXT DEFAULT '{}'"))

        result = await conn.execute(text("PRAGMA table_info(agent_memory)"))
        columns = [row[1] for row in result.fetchall()]
        if "source" not in columns:
            await conn.execute(text("ALTER TABLE agent_memory ADD COLUMN source VARCHAR(10) DEFAULT ''"))
        if "task_category" not in columns:
            await conn.execute(text("ALTER TABLE agent_memory ADD COLUMN task_category VARCHAR(50) DEFAULT ''"))

    from crabagent.core.provider_store import migrate_plaintext_keys

    await migrate_plaintext_keys()

    await _ensure_default_admin()
    await _ensure_default_agents()
    await _ensure_default_permissions_profile()

    try:
        migrated = await migrate_task_records_to_agent_runs()
        if migrated > 0:
            import logging

            logging.getLogger(__name__).info("Migrated %d task_records to agent_runs", migrated)
    except Exception:
        pass


async def _ensure_default_admin():
    from sqlalchemy import select

    from crabagent.core.auth_utils import hash_password

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            return
        user = User(
            username="admin",
            password_hash=hash_password("xcl1989"),
            role="admin",
            enabled=True,
        )
        db.add(user)
        await db.commit()


DEFAULT_AGENTS = [
    {
        "name": "researcher",
        "display_name": "Web Researcher",
        "role": "Web Researcher",
        "goal": (
            "Find, collect, and summarize information from the web using browser and search tools. Always cite sources."
        ),
        "backstory": (
            "You are an experienced web researcher with expertise in finding accurate and relevant information quickly."
        ),
        "icon": "🔍",
        "tool_permissions": {
            "bash": "deny",
            "write": "deny",
            "edit": "deny",
        },
    },
    {
        "name": "analyst",
        "display_name": "Data Analyst",
        "role": "Data Analyst",
        "goal": (
            "Analyze data, compare findings, identify patterns, and generate structured reports with clear conclusions."
        ),
        "backstory": "You are a meticulous data analyst who excels at turning raw data into actionable insights.",
        "icon": "📊",
        "tool_permissions": {
            "write": "deny",
            "edit": "deny",
            "web_search": "deny",
            "web_scrape": "deny",
            "browser": "deny",
        },
    },
    {
        "name": "coder",
        "display_name": "Code Expert",
        "role": "Code Expert",
        "goal": "Write, review, debug, optimize, and refactor code. Generate clean, well-documented solutions.",
        "backstory": (
            "You are a senior software engineer with deep expertise "
            "across multiple programming languages and frameworks."
        ),
        "icon": "💻",
        "tool_permissions": {
            "web_search": "deny",
            "web_scrape": "deny",
            "browser": "deny",
        },
    },
    {
        "name": "writer",
        "display_name": "Content Writer",
        "role": "Content Writer",
        "goal": "Write, edit, translate, and format content. Produce clear, engaging, and well-structured documents.",
        "backstory": (
            "You are a professional writer skilled at transforming complex information into clear, readable content."
        ),
        "icon": "📝",
        "tool_permissions": {
            "bash": "deny",
        },
    },
]


def _migrate_tools_to_permissions(existing, agent_data: dict, _json) -> None:
    existing_perms = {}
    if existing.tool_permissions:
        try:
            existing_perms = _json.loads(existing.tool_permissions)
        except Exception:
            pass
    if existing_perms:
        return
    new_perms = agent_data.get("tool_permissions", {})
    if new_perms:
        existing.tool_permissions = _json.dumps(new_perms)


async def _ensure_default_agents():
    import json as _json

    from sqlalchemy import select

    async with async_session_factory() as db:
        for agent_data in DEFAULT_AGENTS:
            result = await db.execute(select(AgentProfile).where(AgentProfile.name == agent_data["name"]))
            existing = result.scalar_one_or_none()
            if existing:
                if not existing.icon:
                    existing.icon = agent_data["icon"]
                existing.is_default = True
                _migrate_tools_to_permissions(existing, agent_data, _json)
                continue
            db.add(
                AgentProfile(
                    user_id=1,
                    name=agent_data["name"],
                    display_name=agent_data["display_name"],
                    role=agent_data["role"],
                    goal=agent_data["goal"],
                    backstory=agent_data["backstory"],
                    icon=agent_data["icon"],
                    is_default=True,
                    tool_permissions=_json.dumps(agent_data.get("tool_permissions", {})),
                )
            )
        await db.commit()


async def _ensure_default_permissions_profile():
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(select(AgentProfile).where(AgentProfile.name == "__default__"))
        if result.scalar_one_or_none():
            return
        db.add(
            AgentProfile(
                user_id=1,
                name="__default__",
                display_name="Default Permissions",
                role="default",
                goal="default",
                is_default=True,
                enabled=True,
                tool_permissions="{}",
            )
        )
        await db.commit()


async def shared_memory_put(session_id: str, key: str, value: str, author: str = "") -> None:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(SharedMemory).where(
                SharedMemory.session_id == session_id,
                SharedMemory.key == key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            existing.author = author
            existing.updated_at = utcnow()
        else:
            db.add(
                SharedMemory(
                    session_id=session_id,
                    key=key,
                    value=value,
                    author=author,
                )
            )
        await db.commit()


async def shared_memory_get(session_id: str, key: str) -> str | None:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(SharedMemory).where(
                SharedMemory.session_id == session_id,
                SharedMemory.key == key,
            )
        )
        row = result.scalar_one_or_none()
        return row.value if row else None


async def shared_memory_get_all(session_id: str) -> list[dict]:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(SharedMemory).where(SharedMemory.session_id == session_id).order_by(SharedMemory.id)
        )
        return [{"key": r.key, "value": r.value, "author": r.author} for r in result.scalars().all()]


async def shared_memory_delete(session_id: str, key: str) -> None:
    from sqlalchemy import delete as sa_delete

    async with async_session_factory() as db:
        await db.execute(
            sa_delete(SharedMemory).where(
                SharedMemory.session_id == session_id,
                SharedMemory.key == key,
            )
        )
        await db.commit()


async def agent_memory_upsert(
    user_id: int,
    memory_type: str,
    agent_name: str,
    category: str,
    key: str,
    content: str,
    importance: float = 0.5,
    confidence: float = 1.0,
    source_session: str = "",
    source: str = "",
    task_category: str = "",
) -> None:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentMemory).where(
                AgentMemory.user_id == user_id,
                AgentMemory.key == key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.memory_type = memory_type
            existing.agent_name = agent_name
            existing.category = category
            existing.content = content
            existing.importance = importance
            if confidence >= existing.confidence:
                existing.confidence = confidence
            existing.source_session = source_session
            if source:
                existing.source = source
            if task_category:
                existing.task_category = task_category
            existing.updated_at = utcnow()
        else:
            db.add(
                AgentMemory(
                    user_id=user_id,
                    memory_type=memory_type,
                    agent_name=agent_name,
                    category=category,
                    key=key,
                    content=content,
                    importance=importance,
                    confidence=confidence,
                    source_session=source_session,
                    source=source,
                    task_category=task_category,
                )
            )
        await db.commit()


async def agent_memory_get_by_type(
    user_id: int,
    memory_type: str,
    limit: int = 15,
) -> list[dict]:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentMemory)
            .where(AgentMemory.user_id == user_id, AgentMemory.memory_type == memory_type)
            .order_by(AgentMemory.importance.desc())
            .limit(limit)
        )
        return [
            {
                "id": r.id,
                "memory_type": r.memory_type,
                "agent_name": r.agent_name,
                "category": r.category,
                "key": r.key,
                "content": r.content,
                "importance": r.importance,
                "confidence": r.confidence,
                "access_count": r.access_count,
            }
            for r in result.scalars().all()
        ]


async def agent_memory_get_by_agent(
    user_id: int,
    agent_name: str,
    limit: int = 5,
) -> list[dict]:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentMemory)
            .where(
                AgentMemory.user_id == user_id,
                AgentMemory.memory_type == "agent_lesson",
                AgentMemory.agent_name == agent_name,
            )
            .order_by(AgentMemory.importance.desc())
            .limit(limit)
        )
        return [
            {
                "id": r.id,
                "key": r.key,
                "content": r.content,
                "category": r.category,
                "importance": r.importance,
                "source": r.source or "",
                "task_category": r.task_category or "",
                "access_count": r.access_count or 0,
                "created_at": r.created_at,
            }
            for r in result.scalars().all()
        ]


async def agent_memory_search(
    user_id: int,
    query: str,
    memory_type: str = "",
    limit: int = 5,
) -> list[dict]:
    from sqlalchemy import or_, select

    async with async_session_factory() as db:
        conditions = [AgentMemory.user_id == user_id]
        if memory_type:
            conditions.append(AgentMemory.memory_type == memory_type)
        terms = [t for t in query.split() if len(t) >= 2]
        term_filters = []
        if terms:
            for term in terms:
                like = f"%{term}%"
                term_filters.append(AgentMemory.key.like(like))
                term_filters.append(AgentMemory.content.like(like))
        else:
            like = f"%{query}%"
            term_filters.append(AgentMemory.key.like(like))
            term_filters.append(AgentMemory.content.like(like))
        term_filters.append(AgentMemory.category == query)
        conditions.append(or_(*term_filters))
        result = await db.execute(
            select(AgentMemory).where(*conditions).order_by(AgentMemory.importance.desc()).limit(limit)
        )
        rows = result.scalars().all()
        for r in rows:
            r.access_count += 1
        await db.commit()
        return [
            {
                "id": r.id,
                "memory_type": r.memory_type,
                "agent_name": r.agent_name,
                "category": r.category,
                "key": r.key,
                "content": r.content,
                "importance": r.importance,
                "confidence": r.confidence,
            }
            for r in rows
        ]


async def agent_memory_list_all(
    user_id: int,
    memory_type: str = "",
    category: str = "",
) -> list[dict]:
    from sqlalchemy import select

    async with async_session_factory() as db:
        conditions = [AgentMemory.user_id == user_id]
        if memory_type:
            conditions.append(AgentMemory.memory_type == memory_type)
        if category:
            conditions.append(AgentMemory.category == category)
        result = await db.execute(select(AgentMemory).where(*conditions).order_by(AgentMemory.importance.desc()))
        return [
            {
                "id": r.id,
                "memory_type": r.memory_type,
                "agent_name": r.agent_name,
                "category": r.category,
                "key": r.key,
                "content": r.content[:200],
                "importance": r.importance,
                "confidence": r.confidence,
                "access_count": r.access_count,
                "updated_at": r.updated_at.isoformat() if r.updated_at else "",
            }
            for r in result.scalars().all()
        ]


async def agent_memory_delete(user_id: int, key: str) -> bool:
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentMemory).where(
                AgentMemory.user_id == user_id,
                AgentMemory.key == key,
            )
        )
        if not result.scalar_one_or_none():
            return False
        await db.execute(
            sa_delete(AgentMemory).where(
                AgentMemory.user_id == user_id,
                AgentMemory.key == key,
            )
        )
        await db.commit()
        return True


async def agent_memory_clear(user_id: int) -> int:
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import func, select

    async with async_session_factory() as db:
        count_result = await db.execute(
            select(func.count()).select_from(AgentMemory).where(AgentMemory.user_id == user_id)
        )
        count = count_result.scalar() or 0
        await db.execute(sa_delete(AgentMemory).where(AgentMemory.user_id == user_id))
        await db.commit()
        return count


async def agent_memory_replace(
    user_id: int,
    key: str,
    old_text: str,
    new_text: str,
) -> bool:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentMemory).where(
                AgentMemory.user_id == user_id,
                AgentMemory.key == key,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        if old_text not in row.content:
            return False
        row.content = row.content.replace(old_text, new_text, 1)
        row.updated_at = utcnow()
        await db.commit()
        return True


async def task_record_create(
    user_id: int,
    agent_name: str,
    task_summary: str = "",
    success: bool = True,
    elapsed: float = 0.0,
    tokens: int = 0,
    iterations: int = 0,
) -> None:
    async with async_session_factory() as db:
        db.add(
            TaskRecord(
                user_id=user_id,
                agent_name=agent_name,
                task_summary=task_summary[:200],
                success=success,
                elapsed=elapsed,
                tokens=tokens,
                iterations=iterations,
            )
        )
        await db.commit()


async def task_record_stats(user_id: int, agent_name: str) -> dict:
    from sqlalchemy import func, select

    async with async_session_factory() as db:
        total = await db.execute(
            select(func.count())
            .select_from(TaskRecord)
            .where(
                TaskRecord.user_id == user_id,
                TaskRecord.agent_name == agent_name,
            )
        )
        total_count = total.scalar() or 0
        success_count_result = await db.execute(
            select(func.count())
            .select_from(TaskRecord)
            .where(
                TaskRecord.user_id == user_id,
                TaskRecord.agent_name == agent_name,
                TaskRecord.success.is_(True),
            )
        )
        success_count = success_count_result.scalar() or 0
        avg_elapsed_result = await db.execute(
            select(func.avg(TaskRecord.elapsed))
            .select_from(TaskRecord)
            .where(
                TaskRecord.user_id == user_id,
                TaskRecord.agent_name == agent_name,
            )
        )
        avg_elapsed = avg_elapsed_result.scalar() or 0.0
        avg_tokens_result = await db.execute(
            select(func.avg(TaskRecord.tokens))
            .select_from(TaskRecord)
            .where(
                TaskRecord.user_id == user_id,
                TaskRecord.agent_name == agent_name,
            )
        )
        avg_tokens = avg_tokens_result.scalar() or 0
        return {
            "total": total_count,
            "success_rate": round(success_count / total_count * 100, 1) if total_count else 0,
            "avg_elapsed": round(avg_elapsed, 1),
            "avg_tokens": int(avg_tokens),
        }


async def run_record_create(
    user_id: int,
    agent_name: str,
    model: str = "",
    session_id: str = "",
    parent_run_id: int | None = None,
    task_summary: str = "",
    metadata: dict | None = None,
) -> int:
    async with async_session_factory() as db:
        run = AgentRun(
            user_id=user_id,
            agent_name=agent_name,
            model=model,
            session_id=session_id,
            parent_run_id=parent_run_id,
            task_summary=task_summary[:200],
            metadata_=metadata,
            started_at=_time.time(),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def run_record_update(run_id: int, **kwargs) -> None:
    from sqlalchemy import update as sa_update

    async with async_session_factory() as db:
        await db.execute(sa_update(AgentRun).where(AgentRun.id == run_id).values(**kwargs))
        await db.commit()


async def run_record_finalize(
    run_id: int,
    status: str,
    elapsed: float,
    tokens_used: int = 0,
    iterations: int = 0,
    tool_calls: list[dict] | None = None,
    result_summary: str = "",
    error: str = "",
) -> None:
    from sqlalchemy import update as sa_update

    async with async_session_factory() as db:
        values = {
            "status": status,
            "elapsed": elapsed,
            "tokens_used": tokens_used,
            "iterations": iterations,
            "finished_at": _time.time(),
        }
        if tool_calls:
            values["tool_calls"] = tool_calls
        if result_summary:
            values["result_summary"] = result_summary[:1000]
        if error:
            values["error"] = error[:500]
        stmt = sa_update(AgentRun).where(AgentRun.id == run_id).values(**values)
        await db.execute(stmt)
        await db.commit()


async def run_record_get(run_id: int) -> dict | None:
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return None
        return _run_to_dict(run)


async def run_record_list(
    user_id: int,
    agent_name: str = "",
    status: str = "",
    session_id: str = "",
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    from sqlalchemy import select

    conditions = [AgentRun.user_id == user_id]
    if agent_name:
        conditions.append(AgentRun.agent_name == agent_name)
    if status:
        conditions.append(AgentRun.status == status)
    if session_id:
        conditions.append(AgentRun.session_id == session_id)
    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentRun).where(*conditions).order_by(AgentRun.id.desc()).offset(offset).limit(limit)
        )
        return [_run_to_dict(r) for r in result.scalars().all()]


async def run_record_growth(
    user_id: int,
    agent_name: str,
    days: int = 30,
) -> list[dict]:
    from sqlalchemy import select

    async with async_session_factory() as db:
        cutoff = _time.time() - days * 86400
        result = await db.execute(
            select(AgentRun)
            .where(
                AgentRun.user_id == user_id,
                AgentRun.agent_name == agent_name,
                AgentRun.started_at >= cutoff,
            )
            .order_by(AgentRun.started_at.asc())
        )
        rows = result.scalars().all()
        by_date: dict[str, dict] = {}
        for row in rows:
            dt = datetime.datetime.fromtimestamp(row.started_at)
            date_key = dt.strftime("%Y-%m-%d")
            if date_key not in by_date:
                by_date[date_key] = {
                    "date": date_key,
                    "total": 0,
                    "success_count": 0,
                    "avg_elapsed": 0.0,
                    "avg_tokens": 0,
                    "elapsed_sum": 0.0,
                    "tokens_sum": 0,
                }
            entry = by_date[date_key]
            entry["total"] += 1
            if row.status == "completed":
                entry["success_count"] += 1
            entry["elapsed_sum"] += row.elapsed or 0
            entry["tokens_sum"] += row.tokens_used or 0
        growth = []
        for k, v in by_date.items():
            total = v["total"]
            v["success_rate"] = round(v["success_count"] / total * 100, 1) if total else 0
            v["avg_elapsed"] = round(v["elapsed_sum"] / total, 1) if total else 0
            v["avg_tokens"] = int(v["tokens_sum"] / total) if total else 0
            del v["elapsed_sum"]
            del v["tokens_sum"]
            growth.append(v)
        return growth


async def migrate_task_records_to_agent_runs() -> int:
    from sqlalchemy import func, select

    async with async_session_factory() as db:
        existing = await db.execute(select(func.count()).select_from(AgentRun))
        if (existing.scalar() or 0) > 0:
            return 0
        records_result = await db.execute(select(TaskRecord).order_by(TaskRecord.id))
        records = records_result.scalars().all()
        count = 0
        for r in records:
            db.add(
                AgentRun(
                    user_id=r.user_id,
                    agent_name=r.agent_name,
                    task_summary=r.task_summary,
                    status="completed" if r.success else "failed",
                    elapsed=r.elapsed,
                    tokens_used=r.tokens,
                    iterations=r.iterations,
                    finished_at=r.created_at.timestamp(),
                    started_at=r.created_at.timestamp() - (r.elapsed or 0),
                    created_at=r.created_at,
                )
            )
            count += 1
        await db.commit()
        return count


def _run_to_dict(run) -> dict:
    return {
        "id": run.id,
        "user_id": run.user_id,
        "session_id": run.session_id,
        "parent_run_id": run.parent_run_id,
        "agent_name": run.agent_name,
        "model": run.model,
        "task_summary": run.task_summary,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "elapsed": run.elapsed,
        "tokens_used": run.tokens_used,
        "iterations": run.iterations,
        "tool_calls": run.tool_calls,
        "tool_calls_count": len(run.tool_calls) if run.tool_calls else 0,
        "result_summary": run.result_summary,
        "error": run.error,
        "metadata": run.metadata_,
        "created_at": run.created_at.isoformat() if run.created_at else "",
    }
