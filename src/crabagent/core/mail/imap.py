from __future__ import annotations

import asyncio
import email
import logging
from email.header import decode_header
from typing import Any

import imaplib

logger = logging.getLogger(__name__)


class ImapError(Exception):
    pass


def _create_connection(host: str, port: int, user: str, password: str):
    conn = imaplib.IMAP4_SSL(host, port, timeout=30)
    conn.login(user, password)
    return conn


def _imap_noop(conn):
    try:
        conn.noop()
        return True
    except Exception:
        return False


class ImapClient:
    """Simple IMAP client for reading emails."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._conn = None

    async def _connect(self):
        """Connect and login to IMAP server."""
        if self._conn:
            ok = await asyncio.to_thread(_imap_noop, self._conn)
            if ok:
                return
            self._conn = None

        try:
            conn = await asyncio.to_thread(_create_connection, self.host, self.port, self.user, self.password)
            self._conn = conn
        except Exception as e:
            raise ImapError(f"IMAP connection failed: {e}")

    def _decode_str(self, raw: bytes) -> str:
        """Decode email header or text."""
        if not raw:
            return ""
        try:
            decoded_parts = decode_header(raw)
            parts = []
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    try:
                        parts.append(part.decode(charset or "utf-8", errors="replace"))
                    except (LookupError, UnicodeDecodeError):
                        parts.append(part.decode("utf-8", errors="replace"))
                else:
                    parts.append(str(part))
            return " ".join(parts)
        except Exception:
            return raw.decode("utf-8", errors="replace")

    async def _get_body(self, msg: Any) -> str:
        """Extract text body from email message."""
        if msg.is_multipart():
            parts = []
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            parts.append(payload.decode("utf-8", errors="replace"))
                    except Exception:
                        pass
                elif content_type == "text/html" and not parts:
                    # Only use HTML if no text/plain found
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            import html

                            text = payload.decode("utf-8", errors="replace")
                            parts.append(html.unescape(text))
                    except Exception:
                        pass
            return "\n".join(parts)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace")
            return ""

    def _exec(self, method: str, *args):
        """Execute an IMAP command synchronously (to be called in thread pool)."""
        assert self._conn is not None
        return getattr(self._conn, method)(*args)

    async def fetch_unseen(self, limit: int = 10) -> list[dict]:
        """Fetch unseen (unread) emails from INBOX."""
        await self._connect()
        assert self._conn is not None

        try:
            await asyncio.to_thread(self._exec, "select", "INBOX")
            status, data = await asyncio.to_thread(self._exec, "search", None, "UNSEEN")
            if status != "OK" or not data[0]:
                return []

            msg_ids = data[0].split()
            recent = msg_ids[-limit:]

            results = []
            for mid in recent:
                status, msg_data = await asyncio.to_thread(self._exec, "fetch", mid, "(RFC822)")
                if status != "OK":
                    continue
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = self._decode_str(msg.get("Subject", ""))
                sender = self._decode_str(
                    email.utils.getaddresses([msg.get("From", "")])[0][1]
                    if msg.get("From")
                    else ""
                )
                date = msg.get("Date", "")
                body = await self._get_body(msg)

                results.append(
                    {
                        "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                        "subject": subject,
                        "from": sender,
                        "date": date,
                        "body": body[:5000],
                        "raw_message_id": msg.get("Message-ID", ""),
                    }
                )

                try:
                    await asyncio.to_thread(self._exec, "store", mid, "+FLAGS", "\\Seen")
                except Exception:
                    pass

            return results

        except Exception as e:
            raise ImapError(f"IMAP fetch failed: {e}")

    def _close_sync(self):
        """Close IMAP connection synchronously."""
        if self._conn:
            try:
                self._conn.close()
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    async def close(self):
        """Close IMAP connection."""
        await asyncio.to_thread(self._close_sync)

    def __del__(self):
        self._close_sync()
