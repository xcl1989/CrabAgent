from __future__ import annotations

import datetime
import logging
import time as _time
from collections.abc import AsyncGenerator

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crabagent.core.config import settings

logger = logging.getLogger(__name__)


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
    locale: Mapped[str] = mapped_column(String(10), default="en")
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
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    prompt_locale: Mapped[str] = mapped_column(String(10), default="")
    source: Mapped[str] = mapped_column(String(20), default="chat")  # chat | wechat | email | scheduled
    current_file: Mapped[str] = mapped_column(Text, default="")
    workspace_type: Mapped[str] = mapped_column(Text, default="")
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
    compressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
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


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    assignee: Mapped[str] = mapped_column(String(100), default="")
    deadline: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    source_ref: Mapped[str] = mapped_column(String(200), default="")
    source_session: Mapped[str] = mapped_column(String(32), default="")
    project: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class EmailConfig(Base):
    __tablename__ = "email_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, default=1)
    imap_host: Mapped[str] = mapped_column(String(200), default="")
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_user: Mapped[str] = mapped_column(String(200), default="")
    imap_pass: Mapped[str] = mapped_column(Text, default="")
    smtp_host: Mapped[str] = mapped_column(String(200), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_user: Mapped[str] = mapped_column(String(200), default="")
    smtp_pass: Mapped[str] = mapped_column(Text, default="")
    check_interval: Mapped[int] = mapped_column(Integer, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
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


class CalendarEvent(Base):
    """An event in the built-in calendar system.

    Events can originate from manual creation, Agent creation, iCal
    sync, or be dynamically derived from Task deadlines (those have
    ``type='task'`` and are not persisted — generated on the fly).
    """

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    type: Mapped[str] = mapped_column(String(20), default="manual")  # manual | agent | external
    source: Mapped[str] = mapped_column(String(50), default="manual")  # manual | ical | agent | meeting
    linked_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(500), default="")
    color: Mapped[str] = mapped_column(String(20), default="")
    reminder_minutes: Mapped[int] = mapped_column(Integer, default=15)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    ical_uid: Mapped[str] = mapped_column(String(200), default="", index=True)
    ical_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CalendarIcalSource(Base):
    """An external calendar subscription source.

    Supports two protocols:
    - ``ical``: static ICS URL (DingTalk, Feishu)
    - ``caldav``: CalDAV protocol (企业微信)
    """

    __tablename__ = "calendar_ical_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), default="ical")  # ical | caldav
    caldav_username: Mapped[str] = mapped_column(Text, default="")
    caldav_password: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_status: Mapped[str] = mapped_column(String(20), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    sync_event_count: Mapped[int] = mapped_column(Integer, default=0)
    lookback_days: Mapped[int] = mapped_column(Integer, default=7)
    lookahead_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


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


class MemoryEmbedding(Base):
    """Vector embedding cache for AgentMemory entries.

    Embeddings are stored as base64-encoded text for maximum SQLite compat.
    Each row is a 384-dim float32 vector (~6144 bytes base64).
    """

    __tablename__ = "memory_embedding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    embedding: Mapped[str] = mapped_column(Text, nullable=False)  # base64-encoded float32 vector
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


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


class TokenUsage(Base):
    """Per-LLM-call token usage record (one row = one iteration)."""

    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), default="")

    # Input tokens (cached + non-cached = prompt_tokens)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    non_cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Output tokens
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Totals
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    iteration: Mapped[int] = mapped_column(Integer, default=0)
    branch_id: Mapped[str] = mapped_column(String(32), default="main")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


engine = create_async_engine(
    settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},  # timeout=busy_timeout seconds
)
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

        result = await conn.execute(text("PRAGMA table_info(users)"))
        columns = [row[1] for row in result.fetchall()]
        if "locale" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN locale VARCHAR(10) DEFAULT 'en'"))

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
        if "system_prompt" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN system_prompt TEXT DEFAULT ''"))
        if "prompt_locale" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN prompt_locale VARCHAR(10) DEFAULT ''"))
        if "source" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN source VARCHAR(20) DEFAULT 'chat'"))
        if "current_file" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN current_file TEXT DEFAULT ''"))
        if "workspace_type" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN workspace_type TEXT DEFAULT ''"))

        result = await conn.execute(text("PRAGMA table_info(email_configs)"))
        columns = [row[1] for row in result.fetchall()]
        if "imap_host" not in columns:
            # email_configs table created by create_all
            pass

        result = await conn.execute(text("PRAGMA table_info(messages)"))
        columns = [row[1] for row in result.fetchall()]
        if "parent_id" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN parent_id INTEGER DEFAULT NULL"))
        if "branch_id" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN branch_id VARCHAR(32) DEFAULT 'main'"))
        if "agent" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN agent VARCHAR(100) DEFAULT 'default'"))
        if "compressed" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN compressed BOOLEAN DEFAULT 0"))

        # ── FTS5 full-text search index for messages ─────────────
        try:
            await conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
                "content, content=messages, content_rowid=id, tokenize='unicode61')"
            ))
            # Sync existing messages (idempotent: skip if already indexed)
            await conn.execute(text(
                "INSERT INTO messages_fts(rowid, content) "
                "SELECT id, content FROM messages "
                "WHERE id > IFNULL((SELECT max(rowid) FROM messages_fts), 0)"
            ))
            # Triggers for incremental sync
            await conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN "
                "INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END"
            ))
            await conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN "
                "INSERT INTO messages_fts(messages_fts, rowid, content) "
                "VALUES('delete', old.id, old.content); END"
            ))
            await conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN "
                "INSERT INTO messages_fts(messages_fts, rowid, content) "
                "VALUES('delete', old.id, old.content); "
                "INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END"
            ))
        except Exception as e:
            logger.warning("FTS5 setup failed (non-fatal): %s", e)

        # ── FTS5-CJK: jieba-based Chinese full-text search index ────────
        # Table creation only — actual indexing runs in background to avoid
        # blocking app startup (jieba dictionary load is ~1-2s, segmentation
        # of 30k+ messages can take minutes).
        try:
            await conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_cjk USING fts5("
                "content, tokenize='unicode61')"
            ))
        except Exception as e:
            logger.warning("FTS5-CJK table creation failed (non-fatal): %s", e)

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

        result = await conn.execute(text("PRAGMA table_info(tasks)"))
        columns = [row[1] for row in result.fetchall()]
        if "title" not in columns:
            # tasks 表由 create_all 自动创建，无需 ALTER TABLE
            pass
        if "source_session" not in columns:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN source_session VARCHAR(32) DEFAULT ''"))

        result = await conn.execute(text("PRAGMA table_info(agent_memory)"))
        columns = [row[1] for row in result.fetchall()]
        if "source" not in columns:
            await conn.execute(text("ALTER TABLE agent_memory ADD COLUMN source VARCHAR(10) DEFAULT ''"))
        if "task_category" not in columns:
            await conn.execute(text("ALTER TABLE agent_memory ADD COLUMN task_category VARCHAR(50) DEFAULT ''"))

        # --- MemoryEmbedding table (vector search) ---
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_embedding (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL UNIQUE,
                embedding TEXT NOT NULL,
                model_name VARCHAR(100) NOT NULL DEFAULT '',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_memory_embedding_memory_id ON memory_embedding(memory_id)"
        ))

        # --- Calendar tables migrations ---
        # calendar_ical_sources: add CalDAV fields if missing (for upgrades)
        result = await conn.execute(text("PRAGMA table_info(calendar_ical_sources)"))
        columns = [row[1] for row in result.fetchall()]
        if "source_type" not in columns:
            await conn.execute(text(
                "ALTER TABLE calendar_ical_sources ADD COLUMN source_type VARCHAR(20) DEFAULT 'ical'"
            ))
        if "caldav_username" not in columns:
            await conn.execute(text(
                "ALTER TABLE calendar_ical_sources ADD COLUMN caldav_username TEXT DEFAULT ''"
            ))
        if "caldav_password" not in columns:
            await conn.execute(text(
                "ALTER TABLE calendar_ical_sources ADD COLUMN caldav_password TEXT DEFAULT ''"
            ))

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


async def _rebuild_cjk_index_async() -> None:
    """Background task: rebuild jieba-based FTS5 index."""
    try:
        from crabagent.core.fts import rebuild_index
        await rebuild_index()
    except Exception as e:
        logging.getLogger(__name__).warning("FTS5-CJK rebuild failed: %s", e)


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
            "read": "auto",
            "glob": "auto",
            "grep": "auto",
            "web_search": "auto",
            "web_scrape": "auto",
            "browser": "auto",
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
            "bash": "auto",
            "read": "auto",
            "glob": "auto",
            "grep": "auto",
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
            "bash": "auto",
            "read": "auto",
            "write": "auto",
            "edit": "auto",
            "glob": "auto",
            "grep": "auto",
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
            "read": "auto",
            "write": "auto",
            "edit": "auto",
            "glob": "auto",
            "grep": "auto",
            "web_search": "auto",
            "bash": "deny",
            "web_scrape": "deny",
            "browser": "deny",
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

    new_perms = dict(agent_data.get("tool_permissions", {}))

    old_tools = []
    if existing.tools:
        try:
            old_tools = _json.loads(existing.tools)
        except Exception:
            pass
    for t in old_tools:
        if t not in existing_perms and t not in new_perms:
            new_perms[t] = "auto"

    merged = {**new_perms, **existing_perms}
    if merged and merged != existing_perms:
        existing.tool_permissions = _json.dumps(merged)


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
        mem_id: int | None = None
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
            mem_id = existing.id
        else:
            new_mem = AgentMemory(
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
            db.add(new_mem)
        await db.commit()
        # For new records, get the id after commit
        if mem_id is None:
            result2 = await db.execute(
                select(AgentMemory).where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.key == key,
                )
            )
            fresh = result2.scalar_one_or_none()
            if fresh:
                mem_id = fresh.id

    # Best-effort embedding generation (non-blocking)
    if mem_id is not None:
        try:
            await agent_memory_ensure_embedding(mem_id, key, content)
        except Exception:
            pass  # embedding failure must not block upsert


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


async def agent_memory_get_by_workspace(
    user_id: int,
    workspace: str,
    memory_types: tuple[str, ...] = ("agent_lesson", "user_preference"),
    limit: int = 5,
) -> list[dict]:
    """Return the most recent lessons/preferences linked to a workspace.

    Uses a JOIN through ``source_session`` → ``conversations(session_id)``
    so that only memories created while working in *workspace* are returned.
    Ordered by ``importance DESC`` then ``created_at DESC``.
    """
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(AgentMemory)
            .join(Conversation, AgentMemory.source_session == Conversation.session_id)
            .where(
                AgentMemory.user_id == user_id,
                Conversation.workspace == workspace,
                AgentMemory.memory_type.in_(memory_types),
                AgentMemory.source_session != "",  # only lessons linked to a session
            )
            .order_by(AgentMemory.importance.desc(), AgentMemory.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": r.id,
                "memory_type": r.memory_type,
                "agent_name": r.agent_name,
                "category": r.category,
                "content": r.content,
                "importance": r.importance,
                "confidence": r.confidence,
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


# ---------------------------------------------------------------------------
# Semantic (vector) search
# ---------------------------------------------------------------------------


async def agent_memory_search_vector(
    user_id: int,
    query: str,
    memory_type: str = "",
    limit: int = 5,
    fallback: bool = True,
) -> list[dict]:
    """Semantic vector search over AgentMemory.

    Encodes *query* with sentence-transformers, loads all embeddings for
    the user, and returns the top-K by cosine similarity combined with
    importance weight.

    Falls back to :func:`agent_memory_search` (LIKE) when:
    - sentence-transformers is not installed
    - no embeddings exist yet
    - encoding fails for any reason
    """
    from crabagent.core.memory_embed import cosine_similarity, decode_embedding, encode_query

    query_vec = await encode_query(query)
    if query_vec is None:
        if fallback:
            return await agent_memory_search(user_id, query, memory_type=memory_type, limit=limit)
        return []

    import base64

    from sqlalchemy import select

    async with async_session_factory() as db:
        stmt = (
            select(MemoryEmbedding, AgentMemory)
            .join(AgentMemory, MemoryEmbedding.memory_id == AgentMemory.id)
            .where(AgentMemory.user_id == user_id)
        )
        if memory_type:
            stmt = stmt.where(AgentMemory.memory_type == memory_type)

        result = await db.execute(stmt)
        rows = result.all()

    if not rows:
        if fallback:
            return await agent_memory_search(user_id, query, memory_type=memory_type, limit=limit)
        return []

    # Score each memory: similarity * 0.7 + importance * 0.3
    scored: list[tuple[float, float, AgentMemory]] = []
    for emb_row, mem_row in rows:
        try:
            vec_bytes = base64.b64decode(emb_row.embedding)
            vec = decode_embedding(vec_bytes)
            sim = cosine_similarity(query_vec, vec)
        except Exception:
            sim = 0.0
        score = sim * 0.7 + mem_row.importance * 0.3
        scored.append((score, sim, mem_row))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Increment access_count for top results and build output
    output: list[dict] = []
    async with async_session_factory() as db:
        for _score, sim, mem in scored[:limit]:
            # Access-count increment (best-effort)
            try:
                result = await db.execute(select(AgentMemory).where(AgentMemory.id == mem.id))
                fresh = result.scalar_one_or_none()
                if fresh:
                    fresh.access_count += 1
            except Exception:
                pass
            output.append(
                {
                    "id": mem.id,
                    "memory_type": mem.memory_type,
                    "agent_name": mem.agent_name,
                    "category": mem.category,
                    "key": mem.key,
                    "content": mem.content,
                    "importance": mem.importance,
                    "confidence": mem.confidence,
                    "access_count": mem.access_count,
                    "_similarity": round(sim, 4),
                }
            )
        try:
            await db.commit()
        except Exception:
            pass

    return output


async def agent_memory_ensure_embedding(memory_id: int, key: str, content: str) -> None:
    """Generate and persist an embedding for a memory entry (best-effort).

    Called after ``agent_memory_upsert`` to keep the embedding table in sync.
    """
    from crabagent.core.memory_embed import encode

    text = f"{key}: {content}"
    blob = await encode(text)
    if blob is None:
        return

    import base64

    from sqlalchemy import select

    b64_str = base64.b64encode(blob).decode("ascii")

    async with async_session_factory() as db:
        result = await db.execute(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.embedding = b64_str
            existing.updated_at = utcnow()
        else:
            db.add(
                MemoryEmbedding(
                    memory_id=memory_id,
                    embedding=b64_str,
                    model_name="paraphrase-multilingual-MiniLM-L12-v2",
                )
            )
        await db.commit()


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


# ---------------------------------------------------------------------------
# Token usage CRUD + aggregation queries
# ---------------------------------------------------------------------------


async def token_usage_batch_create(records: list[dict]) -> None:
    """Batch insert token usage records."""
    if not records:
        return
    async with async_session_factory() as db:
        for r in records:
            prompt = r.get("prompt_tokens", 0)
            cached = r.get("cached_tokens", 0)
            completion = r.get("completion_tokens", 0)
            db.add(
                TokenUsage(
                    user_id=r["user_id"],
                    session_id=r.get("session_id", ""),
                    run_id=r.get("run_id"),
                    agent_name=r.get("agent_name", "main"),
                    model=r.get("model", ""),
                    provider=r.get("provider", ""),
                    prompt_tokens=prompt,
                    cached_tokens=cached,
                    non_cached_tokens=prompt - cached,
                    completion_tokens=completion,
                    reasoning_tokens=r.get("reasoning_tokens", 0),
                    total_tokens=prompt + completion,
                    iteration=r.get("iteration", 0),
                    branch_id=r.get("branch_id", "main"),
                )
            )
        await db.commit()


def _usage_to_dict(u: TokenUsage) -> dict:
    return {
        "id": u.id,
        "session_id": u.session_id,
        "run_id": u.run_id,
        "agent_name": u.agent_name,
        "model": u.model,
        "provider": u.provider,
        "prompt_tokens": u.prompt_tokens,
        "cached_tokens": u.cached_tokens,
        "non_cached_tokens": u.non_cached_tokens,
        "completion_tokens": u.completion_tokens,
        "reasoning_tokens": u.reasoning_tokens,
        "total_tokens": u.total_tokens,
        "iteration": u.iteration,
        "branch_id": u.branch_id,
        "created_at": u.created_at.isoformat() if u.created_at else "",
    }


async def _resolve_session_ids_by_workspace(user_id: int, workspace: str) -> set[str] | None:
    """Return session_ids for a workspace, or None if no filter needed."""
    if not workspace:
        return None
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(Conversation.session_id).where(
                Conversation.user_id == user_id, Conversation.workspace == workspace
            )
        )
        return {r[0] for r in result.fetchall()}


async def token_usage_overview(
    user_id: int, days: int = 30, workspace: str = ""
) -> dict:
    """Aggregate overview: totals, by_agent, by_model, trend (daily or hourly)."""
    from sqlalchemy import func, select

    hourly = days <= 1  # hourly buckets for "today"
    if days <= 1:
        # "Today" means from midnight, not 24h ago
        cutoff_dt = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    elif days < 365:
        cutoff_ts = _time.time() - days * 86400
        cutoff_dt = datetime.datetime.fromtimestamp(cutoff_ts)
    else:
        cutoff_dt = datetime.datetime.min

    # Resolve workspace → session_ids filter
    ws_session_ids = await _resolve_session_ids_by_workspace(user_id, workspace)

    async with async_session_factory() as db:
        # Build base conditions
        conds = [TokenUsage.user_id == user_id, *_cutoff_filter(cutoff_dt)]
        if ws_session_ids is not None:
            if not ws_session_ids:
                # No sessions match this workspace → empty result
                return _empty_overview()
            conds.append(TokenUsage.session_id.in_(ws_session_ids))

        # Totals
        totals_result = await db.execute(
            select(
                func.sum(TokenUsage.prompt_tokens).label("prompt"),
                func.sum(TokenUsage.cached_tokens).label("cached"),
                func.sum(TokenUsage.non_cached_tokens).label("non_cached"),
                func.sum(TokenUsage.completion_tokens).label("completion"),
                func.sum(TokenUsage.reasoning_tokens).label("reasoning"),
                func.sum(TokenUsage.total_tokens).label("total"),
                func.count(TokenUsage.id).label("calls"),
            ).where(*conds)
        )
        row = totals_result.one()
        total_prompt = row.prompt or 0
        total_cached = row.cached or 0
        total_completion = row.completion or 0
        total_total = row.total or 0

        # Today's tokens (independent of range filter)
        today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_conds = [TokenUsage.user_id == user_id, TokenUsage.created_at >= today_start]
        if ws_session_ids is not None:
            today_conds.append(TokenUsage.session_id.in_(ws_session_ids))
        today_result = await db.execute(
            select(func.sum(TokenUsage.total_tokens).label("total")).where(*today_conds)
        )
        today_total = today_result.scalar() or 0

        # Sessions count
        sessions_result = await db.execute(
            select(func.count(func.distinct(TokenUsage.session_id))).where(*conds)
        )
        sessions_count = sessions_result.scalar() or 0

        # By agent
        agent_result = await db.execute(
            select(
                TokenUsage.agent_name,
                func.sum(TokenUsage.total_tokens).label("total"),
                func.sum(TokenUsage.prompt_tokens).label("prompt"),
                func.sum(TokenUsage.cached_tokens).label("cached"),
                func.sum(TokenUsage.completion_tokens).label("completion"),
                func.count(TokenUsage.id).label("calls"),
            )
            .where(*conds)
            .group_by(TokenUsage.agent_name)
            .order_by(func.sum(TokenUsage.total_tokens).desc())
        )
        by_agent = [
            {
                "agent_name": r[0],
                "total_tokens": r[1] or 0,
                "prompt_tokens": r[2] or 0,
                "cached_tokens": r[3] or 0,
                "completion_tokens": r[4] or 0,
                "calls": r[5] or 0,
            }
            for r in agent_result.fetchall()
        ]

        # By model
        model_result = await db.execute(
            select(
                TokenUsage.model,
                func.sum(TokenUsage.total_tokens).label("total"),
                func.sum(TokenUsage.prompt_tokens).label("prompt"),
                func.sum(TokenUsage.cached_tokens).label("cached"),
                func.sum(TokenUsage.completion_tokens).label("completion"),
                func.count(TokenUsage.id).label("calls"),
            )
            .where(*conds)
            .group_by(TokenUsage.model)
            .order_by(func.sum(TokenUsage.total_tokens).desc())
        )
        by_model = [
            {
                "model": r[0],
                "total_tokens": r[1] or 0,
                "prompt_tokens": r[2] or 0,
                "cached_tokens": r[3] or 0,
                "completion_tokens": r[4] or 0,
                "calls": r[5] or 0,
            }
            for r in model_result.fetchall()
        ]

        # Trend (daily or hourly)
        trend_result = await db.execute(
            select(TokenUsage).where(*conds).order_by(TokenUsage.created_at.asc())
        )
        rows = trend_result.scalars().all()
        trend: dict[str, dict] = {}
        for r in rows:
            if not r.created_at:
                continue
            if hourly:
                bucket = r.created_at.strftime("%H:00")
            else:
                bucket = r.created_at.strftime("%Y-%m-%d")
            if bucket not in trend:
                trend[bucket] = {
                    "date" if not hourly else "hour": bucket,
                    "prompt_tokens": 0,
                    "cached_tokens": 0,
                    "non_cached_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                }
            e = trend[bucket]
            e["prompt_tokens"] += r.prompt_tokens
            e["cached_tokens"] += r.cached_tokens
            e["non_cached_tokens"] += r.non_cached_tokens
            e["completion_tokens"] += r.completion_tokens
            e["reasoning_tokens"] += r.reasoning_tokens
            e["total_tokens"] += r.total_tokens

        # Fill missing hours for hourly view (0-23)
        if hourly:
            now_hour = datetime.datetime.now().hour
            for h in range(0, now_hour + 1):
                key = f"{h:02d}:00"
                if key not in trend:
                    trend[key] = {
                        "hour": key,
                        "prompt_tokens": 0,
                        "cached_tokens": 0,
                        "non_cached_tokens": 0,
                        "completion_tokens": 0,
                        "reasoning_tokens": 0,
                        "total_tokens": 0,
                    }

        trend_list = sorted(trend.values(), key=lambda x: list(x.values())[0])

        return {
            "total_tokens": total_total,
            "prompt_tokens": total_prompt,
            "cached_tokens": total_cached,
            "non_cached_tokens": (row.non_cached or 0),
            "completion_tokens": total_completion,
            "reasoning_tokens": (row.reasoning or 0),
            "cache_hit_rate": round(total_cached / total_prompt, 4) if total_prompt > 0 else 0,
            "total_calls": row.calls or 0,
            "today_tokens": today_total,
            "sessions_count": sessions_count,
            "by_agent": by_agent,
            "by_model": by_model,
            "hourly": hourly,
            "trend": trend_list,
            "daily": trend_list,  # backward compat
        }


def _empty_overview() -> dict:
    return {
        "total_tokens": 0,
        "prompt_tokens": 0,
        "cached_tokens": 0,
        "non_cached_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "cache_hit_rate": 0,
        "total_calls": 0,
        "today_tokens": 0,
        "sessions_count": 0,
        "by_agent": [],
        "by_model": [],
        "hourly": False,
        "trend": [],
        "daily": [],
    }


def _cutoff_filter(cutoff_dt):
    """Return filter conditions for created_at >= cutoff."""
    if cutoff_dt == datetime.datetime.min:
        return []
    return [TokenUsage.created_at >= cutoff_dt]


async def token_usage_sessions(
    user_id: int, limit: int = 20, offset: int = 0, workspace: str = ""
) -> tuple[list[dict], int]:
    """Per-session aggregated token usage."""
    from sqlalchemy import func, select

    ws_session_ids = await _resolve_session_ids_by_workspace(user_id, workspace)

    async with async_session_factory() as db:
        conds = [TokenUsage.user_id == user_id]
        if ws_session_ids is not None:
            if not ws_session_ids:
                return [], 0
            conds.append(TokenUsage.session_id.in_(ws_session_ids))

        # Get aggregated stats per session
        result = await db.execute(
            select(
                TokenUsage.session_id,
                func.sum(TokenUsage.total_tokens).label("total"),
                func.sum(TokenUsage.prompt_tokens).label("prompt"),
                func.sum(TokenUsage.cached_tokens).label("cached"),
                func.sum(TokenUsage.non_cached_tokens).label("non_cached"),
                func.sum(TokenUsage.completion_tokens).label("completion"),
                func.sum(TokenUsage.reasoning_tokens).label("reasoning"),
                func.count(TokenUsage.id).label("calls"),
                func.max(TokenUsage.created_at).label("last_active"),
                func.min(TokenUsage.created_at).label("created"),
            )
            .where(*conds)
            .group_by(TokenUsage.session_id)
            .order_by(func.sum(TokenUsage.total_tokens).desc())
            .offset(offset)
            .limit(limit)
        )
        rows = result.fetchall()

        # Get session titles
        session_ids = [r[0] for r in rows]
        titles: dict[str, str] = {}
        if session_ids:
            conv_result = await db.execute(
                select(Conversation.session_id, Conversation.title).where(
                    Conversation.session_id.in_(session_ids)
                )
            )
            for cid, title in conv_result.fetchall():
                titles[cid] = title or ""

        sessions = [
            {
                "session_id": r[0],
                "title": titles.get(r[0], ""),
                "total_tokens": r[1] or 0,
                "prompt_tokens": r[2] or 0,
                "cached_tokens": r[3] or 0,
                "non_cached_tokens": r[4] or 0,
                "completion_tokens": r[5] or 0,
                "reasoning_tokens": r[6] or 0,
                "cache_hit_rate": round((r[3] or 0) / (r[2] or 1), 4),
                "calls": r[7] or 0,
                "last_active": r[8].isoformat() if r[8] else "",
                "created_at": r[9].isoformat() if r[9] else "",
            }
            for r in rows
        ]

        # Total count
        count_result = await db.execute(
            select(func.count(func.distinct(TokenUsage.session_id))).where(*conds)
        )
        total = count_result.scalar() or 0

        return sessions, total


async def token_usage_workspaces(user_id: int) -> list[dict]:
    """List workspaces that have token usage data, with aggregated stats."""
    from sqlalchemy import func, select

    async with async_session_factory() as db:
        result = await db.execute(
            select(
                Conversation.workspace,
                func.sum(TokenUsage.total_tokens).label("total"),
                func.count(TokenUsage.id).label("calls"),
            )
            .join(TokenUsage, TokenUsage.session_id == Conversation.session_id)
            .where(TokenUsage.user_id == user_id, Conversation.workspace != "")
            .group_by(Conversation.workspace)
            .order_by(func.sum(TokenUsage.total_tokens).desc())
        )
        return [
            {"workspace": r[0], "total_tokens": r[1] or 0, "calls": r[2] or 0}
            for r in result.fetchall()
        ]


async def token_usage_session_detail(user_id: int, session_id: str) -> dict | None:
    """Detailed token usage for a single session."""
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(TokenUsage)
            .where(TokenUsage.user_id == user_id, TokenUsage.session_id == session_id)
            .order_by(TokenUsage.id.asc())
        )
        rows = result.scalars().all()
        if not rows:
            return None

        # Totals
        total_prompt = sum(r.prompt_tokens for r in rows)
        total_cached = sum(r.cached_tokens for r in rows)
        total_non_cached = sum(r.non_cached_tokens for r in rows)
        total_completion = sum(r.completion_tokens for r in rows)
        total_reasoning = sum(r.reasoning_tokens for r in rows)
        total_tokens = sum(r.total_tokens for r in rows)

        # By agent
        agent_map: dict[str, dict] = {}
        for r in rows:
            if r.agent_name not in agent_map:
                agent_map[r.agent_name] = {
                    "agent_name": r.agent_name,
                    "prompt_tokens": 0,
                    "cached_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                }
            e = agent_map[r.agent_name]
            e["prompt_tokens"] += r.prompt_tokens
            e["cached_tokens"] += r.cached_tokens
            e["completion_tokens"] += r.completion_tokens
            e["total_tokens"] += r.total_tokens
            e["calls"] += 1

        # By model
        model_map: dict[str, dict] = {}
        for r in rows:
            if r.model not in model_map:
                model_map[r.model] = {
                    "model": r.model,
                    "prompt_tokens": 0,
                    "cached_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                }
            e = model_map[r.model]
            e["prompt_tokens"] += r.prompt_tokens
            e["cached_tokens"] += r.cached_tokens
            e["completion_tokens"] += r.completion_tokens
            e["total_tokens"] += r.total_tokens
            e["calls"] += 1

        return {
            "session_id": session_id,
            "total": {
                "prompt_tokens": total_prompt,
                "cached_tokens": total_cached,
                "non_cached_tokens": total_non_cached,
                "completion_tokens": total_completion,
                "reasoning_tokens": total_reasoning,
                "total_tokens": total_tokens,
                "cache_hit_rate": round(total_cached / total_prompt, 4) if total_prompt > 0 else 0,
                "calls": len(rows),
            },
            "by_agent": list(agent_map.values()),
            "by_model": list(model_map.values()),
            "records": [_usage_to_dict(r) for r in rows],
        }
