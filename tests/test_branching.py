import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crabagent.core.database import Base, Conversation, Message


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestMessageBranchFields:
    def test_message_has_branch_id(self, db_session):
        msg = Message(
            conversation_id=1,
            sequence=1,
            role="user",
            content="hello",
            branch_id="branch-abc",
        )
        db_session.add(msg)
        db_session.commit()
        loaded = db_session.get(Message, msg.id)
        assert loaded.branch_id == "branch-abc"

    def test_message_has_parent_id(self, db_session):
        msg = Message(
            conversation_id=1,
            sequence=1,
            role="user",
            content="hello",
            parent_id=42,
        )
        db_session.add(msg)
        db_session.commit()
        loaded = db_session.get(Message, msg.id)
        assert loaded.parent_id == 42

    def test_message_defaults(self, db_session):
        msg = Message(
            conversation_id=1,
            sequence=1,
            role="user",
            content="hello",
        )
        db_session.add(msg)
        db_session.commit()
        loaded = db_session.get(Message, msg.id)
        assert loaded.branch_id == "main"
        assert loaded.parent_id is None


class TestConversationBranchField:
    def test_conversation_has_active_branch(self, db_session):
        conv = Conversation(
            session_id="abc123",
            user_id=1,
            active_branch="branch-xyz",
        )
        db_session.add(conv)
        db_session.commit()
        loaded = db_session.get(Conversation, conv.id)
        assert loaded.active_branch == "branch-xyz"

    def test_conversation_default_branch(self, db_session):
        conv = Conversation(
            session_id="def456",
            user_id=1,
        )
        db_session.add(conv)
        db_session.commit()
        loaded = db_session.get(Conversation, conv.id)
        assert loaded.active_branch == "main"
