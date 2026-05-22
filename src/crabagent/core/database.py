from __future__ import annotations

import datetime
from collections.abc import AsyncGenerator

from sqlalchemy import Boolean, DateTime, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crabagent.core.config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


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
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    active_branch: Mapped[str] = mapped_column(String(32), default="main")
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


engine = create_async_engine(settings.db_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def _ensure_workspace_dirs():
    base = settings.workspace.resolve() / ".crabagent"
    base.mkdir(parents=True, exist_ok=True)
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
            'parameters = {\n'
            '    "type": "object",\n'
            '    "properties": {\n'
            '        "name": {"type": "string", "description": "Name to greet"},\n'
            '    },\n'
            '    "required": ["name"],\n'
            '}\n'
            'requires_permission = True  # set to False to skip confirmation\n'
            '\n'
            '\n'
            'def run(name: str) -> str:\n'
            '    return f"Hello, {name}! Welcome to CrabAgent."\n'
        )


async def init_db() -> None:
    _ensure_workspace_dirs()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        result = await conn.execute(text("PRAGMA table_info(conversations)"))
        columns = [row[1] for row in result.fetchall()]
        if "tokens" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN tokens INTEGER DEFAULT 0"))
        if "active_branch" not in columns:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN active_branch VARCHAR(32) DEFAULT 'main'"))

        result = await conn.execute(text("PRAGMA table_info(messages)"))
        columns = [row[1] for row in result.fetchall()]
        if "parent_id" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN parent_id INTEGER DEFAULT NULL"))
        if "branch_id" not in columns:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN branch_id VARCHAR(32) DEFAULT 'main'"))

        result = await conn.execute(text("PRAGMA table_info(molts)"))
        columns = [row[1] for row in result.fetchall()]
        if "method" not in columns:
            await conn.execute(text("ALTER TABLE molts ADD COLUMN method VARCHAR(10) DEFAULT 'git'"))

        result = await conn.execute(text("PRAGMA table_info(todos)"))
        columns = [row[1] for row in result.fetchall()]
        if "task" not in columns:
            await conn.execute(text("ALTER TABLE todos ADD COLUMN task TEXT NOT NULL DEFAULT ''"))

    from crabagent.core.provider_store import migrate_plaintext_keys
    await migrate_plaintext_keys()

    await _ensure_default_admin()


async def _ensure_default_admin():
    from sqlalchemy import select

    from crabagent.serve.services.auth import hash_password

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
