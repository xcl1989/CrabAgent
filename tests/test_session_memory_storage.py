from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from crabagent.core import database


async def test_session_memory_migration_and_transactional_revocation(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE agent_memory (
                    id INTEGER PRIMARY KEY, user_id INTEGER, key TEXT, content TEXT, category TEXT,
                    memory_type TEXT, scope TEXT, workspace_path TEXT, agent_name TEXT,
                    recall_policy TEXT, source_session TEXT, access_count INTEGER DEFAULT 0
                )
            """))
            await conn.execute(text("""
                INSERT INTO agent_memory VALUES (1, 7, 'k', 'v1', '', 'team', '', '', '', '', '', 0)
            """))
            for model in (database.Message, database.ConversationMemoryAnchor, database.ConversationMemoryInjection):
                await conn.run_sync(model.__table__.create)
            await database._migrate_session_memory(conn)
            original = (await conn.execute(text("SELECT memory_uid FROM agent_memory"))).scalar_one()
            await database._migrate_session_memory(conn)
            await conn.execute(text("UPDATE agent_memory SET access_count = 3, content = 'v1' WHERE id = 1"))
            versions = text("SELECT memory_uid, content_revision, visibility_epoch FROM agent_memory")
            assert (await conn.execute(versions)).one() == (original, 1, 1)
            await conn.execute(text("UPDATE agent_memory SET content = 'v2', scope = 'workspace' WHERE id = 1"))
            await conn.execute(text("UPDATE agent_memory SET scope = '' WHERE id = 1"))
            assert (await conn.execute(versions)).one() == (original, 2, 3)
            for conversation, branch, anchor in ((10, "main", 100), (11, "fork", 101)):
                await conn.execute(database.ConversationMemoryAnchor.__table__.insert().values(
                    conversation_id=conversation, branch_id=branch, anchor_message_id=anchor,
                ))
                await conn.execute(database.ConversationMemoryInjection.__table__.insert().values(
                    conversation_id=conversation, branch_id=branch, anchor_message_id=anchor, memory_uid=original,
                    content_revision=1, visibility_epoch=1, ordinal=0, snapshot_payload="v1",
                ))

        count = text("SELECT count(*) FROM conversation_memory_injections")
        async with engine.connect() as conn:
            await conn.execute(text("DELETE FROM agent_memory WHERE user_id = 7"))
            assert await conn.scalar(count) == 0
            await conn.rollback()
            assert await conn.scalar(count) == 2
            await conn.execute(text("DELETE FROM agent_memory WHERE user_id = 7"))
            await conn.execute(text("INSERT INTO agent_memory (id, user_id, key) VALUES (1, 7, 'k')"))
            new_uid = await conn.scalar(text("SELECT memory_uid FROM agent_memory"))
            assert new_uid and new_uid != original
            assert await conn.scalar(count) == 0
            assert await conn.scalar(text("SELECT count(*) FROM conversation_memory_anchors")) == 2
            await conn.execute(database.Message.__table__.insert().values(
                id=100, conversation_id=10, branch_id="main", role="user",
            ))
            await conn.execute(database.ConversationMemoryInjection.__table__.insert().values(
                conversation_id=10, branch_id="main", anchor_message_id=100, memory_uid=new_uid,
                content_revision=1, visibility_epoch=1, ordinal=0, snapshot_payload="new",
            ))
            await conn.execute(text("DELETE FROM messages WHERE id = 100"))
            assert await conn.scalar(count) == 0
            assert await conn.scalar(text("SELECT anchor_message_id FROM conversation_memory_anchors")) == 101
            await conn.commit()
    finally:
        await engine.dispose()
