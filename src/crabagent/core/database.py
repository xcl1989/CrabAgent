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

        result = await conn.execute(text("PRAGMA table_info(agent_profiles)"))
        columns = [row[1] for row in result.fetchall()]
        if "icon" not in columns:
            await conn.execute(text("ALTER TABLE agent_profiles ADD COLUMN icon VARCHAR(10) DEFAULT ''"))
        if "is_default" not in columns:
            await conn.execute(text("ALTER TABLE agent_profiles ADD COLUMN is_default BOOLEAN DEFAULT 0"))
        if "tools" not in columns:
            await conn.execute(text("ALTER TABLE agent_profiles ADD COLUMN tools TEXT DEFAULT ''"))

    from crabagent.core.provider_store import migrate_plaintext_keys
    await migrate_plaintext_keys()

    await _ensure_default_admin()
    await _ensure_default_agents()


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


DEFAULT_AGENTS = [
    {
        "name": "researcher",
        "display_name": "Web Researcher",
        "role": "Web Researcher",
        "goal": (
            "Find, collect, and summarize information from the web "
            "using browser and search tools. Always cite sources."
        ),
        "backstory": (
            "You are an experienced web researcher with expertise "
            "in finding accurate and relevant information quickly."
        ),
        "icon": "🔍",
        "tools": [
            "web_search", "web_scrape", "browser",
            "read", "glob", "grep",
            "shared_get", "shared_put", "shared_list",
        ],
    },
    {
        "name": "analyst",
        "display_name": "Data Analyst",
        "role": "Data Analyst",
        "goal": (
            "Analyze data, compare findings, identify patterns, "
            "and generate structured reports with clear conclusions."
        ),
        "backstory": (
            "You are a meticulous data analyst who excels at "
            "turning raw data into actionable insights."
        ),
        "icon": "📊",
        "tools": ["bash", "read", "glob", "grep", "shared_get", "shared_put", "shared_list"],
    },
    {
        "name": "coder",
        "display_name": "Code Expert",
        "role": "Code Expert",
        "goal": (
            "Write, review, debug, optimize, and refactor code. "
            "Generate clean, well-documented solutions."
        ),
        "backstory": (
            "You are a senior software engineer with deep expertise "
            "across multiple programming languages and frameworks."
        ),
        "icon": "💻",
        "tools": ["bash", "read", "write", "edit", "glob", "grep", "shared_get", "shared_put", "shared_list"],
    },
    {
        "name": "writer",
        "display_name": "Content Writer",
        "role": "Content Writer",
        "goal": (
            "Write, edit, translate, and format content. "
            "Produce clear, engaging, and well-structured documents."
        ),
        "backstory": (
            "You are a professional writer skilled at transforming "
            "complex information into clear, readable content."
        ),
        "icon": "📝",
        "tools": ["read", "write", "edit", "glob", "grep", "web_search", "shared_get", "shared_put", "shared_list"],
    },
]


async def _ensure_default_agents():
    import json as _json

    from sqlalchemy import select

    async with async_session_factory() as db:
        for agent_data in DEFAULT_AGENTS:
            result = await db.execute(
                select(AgentProfile).where(AgentProfile.name == agent_data["name"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                if not existing.icon:
                    existing.icon = agent_data["icon"]
                existing.is_default = True
                if not existing.tools and agent_data.get("tools"):
                    existing.tools = _json.dumps(agent_data["tools"])
                continue
            db.add(AgentProfile(
                user_id=1,
                name=agent_data["name"],
                display_name=agent_data["display_name"],
                role=agent_data["role"],
                goal=agent_data["goal"],
                backstory=agent_data["backstory"],
                icon=agent_data["icon"],
                is_default=True,
                tools=_json.dumps(agent_data.get("tools", [])),
            ))
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
            db.add(SharedMemory(
                session_id=session_id, key=key, value=value, author=author,
            ))
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
            select(SharedMemory)
            .where(SharedMemory.session_id == session_id)
            .order_by(SharedMemory.id)
        )
        return [
            {"key": r.key, "value": r.value, "author": r.author}
            for r in result.scalars().all()
        ]


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
