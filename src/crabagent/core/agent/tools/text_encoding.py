"""Decode tool output without splitting multibyte characters across reads."""
import codecs
import locale
import sys


def windows_output_encoding() -> str:
    if sys.platform == "win32":
        try:
            import ctypes
            codepage = ctypes.windll.kernel32.GetConsoleOutputCP() or ctypes.windll.kernel32.GetOEMCP()
            if codepage:
                return f"cp{codepage}"
        except (AttributeError, OSError):
            pass
        return locale.getpreferredencoding(False) or "utf-8"
    return "utf-8"


def decode_file(data: bytes) -> str:
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8-sig"),
                          (codecs.BOM_UTF32_LE, "utf-32"),
                          (codecs.BOM_UTF32_BE, "utf-32"),
                          (codecs.BOM_UTF16_LE, "utf-16"),
                          (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            return data.decode(encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        for encoding in (windows_output_encoding(), "gb18030"):
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")


class StreamDecoder:
    """Prefer UTF-8; select the console encoding on the first invalid sequence."""

    def __init__(self, fallback: str):
        self.fallback = fallback
        self.pending = b""
        self.decoder = None

    def decode(self, data: bytes, final: bool = False) -> str:
        if self.decoder is not None:
            return self.decoder.decode(data, final=final)
        data = self.pending + data
        self.pending = b""
        try:
            text, consumed = codecs.utf_8_decode(data, "strict", final)
        except UnicodeDecodeError:
            try:
                self.decoder = codecs.getincrementaldecoder(self.fallback)(errors="replace")
            except LookupError:
                self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            return self.decoder.decode(data, final=final)
        self.pending = data[consumed:]
        if any(ord(char) > 127 for char in text):
            self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            self.decoder.decode(self.pending)
            self.pending = b""
        return text
