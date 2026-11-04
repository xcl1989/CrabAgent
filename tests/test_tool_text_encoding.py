import asyncio
from types import SimpleNamespace

import pytest

from crabagent.core.agent.tools import bash as bash_tool
from crabagent.core.agent.tools.read import read_file
from crabagent.core.agent.tools.text_encoding import StreamDecoder, decode_file


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32", "gb18030"])
def test_read_text_encodings(tmp_path, encoding):
    path = tmp_path / "text.txt"
    path.write_bytes("中文内容\nsecond".encode(encoding))
    result = read_file(str(path))
    assert "1: 中文内容" in result
    assert "2: second" in result


def test_binary_not_read_as_text(tmp_path):
    path = tmp_path / "binary"
    path.write_bytes(b"hello\x00world")
    assert "Binary file" in read_file(str(path))


@pytest.mark.parametrize("encoding", ["utf-8", "gb18030"])
def test_incremental_multibyte_and_ascii_prefix(encoding):
    decoder = StreamDecoder("gb18030")
    data = "hello 中文".encode(encoding)
    assert "".join(decoder.decode(bytes([b])) for b in data) + decoder.decode(b"", final=True) == "hello 中文"


def test_invalid_file_bytes_do_not_raise():
    assert decode_file(b"\xff\xff\xff")


@pytest.mark.asyncio
async def test_stream_stdout_and_stderr_use_independent_decoders(monkeypatch):
    monkeypatch.setattr(bash_tool, "_ENCODING", "gb18030")
    events = []
    async def emit(context, text, tool_call_id=""):
        events.append(text)
    monkeypatch.setattr(bash_tool, "_emit_bash_output", emit)
    class Reader:
        def __init__(self, data):
            self.chunks = iter(bytes([b]) for b in data)
        async def read(self, size):
            await asyncio.sleep(0)
            return next(self.chunks, b"")
    proc = SimpleNamespace(stdout=Reader("输出".encode()), stderr=Reader("错误".encode("gb18030")))
    out, err = [], []
    await bash_tool._stream_output(proc, out, err, None)
    assert "".join(out) == "输出"
    assert "".join(err) == "错误"
    assert "�" not in "".join(events)
