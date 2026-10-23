"""Non-destructive legacy index retirement regression tests."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "compact_message_db", Path(__file__).parents[1] / "scripts" / "compact_message_db.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_snapshot_preserves_messages_and_cjk_index(tmp_path):
    source, output = tmp_path / "live.db", tmp_path / "compact.db"
    with sqlite3.connect(source) as db:
        db.executescript("""
            CREATE TABLE messages(id INTEGER PRIMARY KEY, content TEXT);
            CREATE TABLE conversations(id INTEGER PRIMARY KEY);
            CREATE VIRTUAL TABLE messages_fts USING fts5(content);
            CREATE VIRTUAL TABLE messages_fts_cjk USING fts5(content);
            CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
              INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END;
            INSERT INTO messages VALUES (1, 'original data:image/png;base64,AAAA');
            INSERT INTO conversations VALUES (1);
            INSERT INTO messages_fts_cjk VALUES ('searchable');
        """)
    original = source.read_bytes()
    report = module.compact_snapshot(source, output)
    assert source.read_bytes() == original
    assert report["integrity_check"] == "ok"
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT content FROM messages").fetchone()[0].endswith("base64,AAAA")
        assert db.execute("SELECT content FROM messages_fts_cjk").fetchone() == ("searchable",)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name = 'messages_fts'").fetchall()
        assert not db.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall()


def test_refuses_to_overwrite_files(tmp_path):
    source, output = tmp_path / "live.db", tmp_path / "existing.db"
    source.write_bytes(b"source")
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        module.compact_snapshot(source, output)
    assert output.read_bytes() == b"keep"
    with pytest.raises(ValueError):
        module.compact_snapshot(source, source)
    assert source.read_bytes() == b"source"
