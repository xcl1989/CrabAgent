"""iLink Bot HTTP client.

Wraps all iLink protocol calls: login (QR code), message long-poll,
send message, typing indicator, and media upload/download.

Protocol reference: https://www.wechatbot.dev/en/protocol
"""

from __future__ import annotations

import base64
import logging
import random
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ── File type detection for media download validation ────────────────

# Common magic bytes for various file types
_FILE_MAGIC = {
    b"\xff\xd8\xff": "JPEG image",
    b"\x89PNG": "PNG image",
    b"PK\x03\x04": "ZIP/Office (docx/xlsx/pptx)",
    b"%PDF": "PDF document",
    b"GIF8": "GIF image",
    b"RIFF": "WEBP/WAV/AVI",
    b"\x00\x00\x01\x00": "ICO image",
    b"ftyp": "MP4/MOV video",
}

# Text file extensions that suggest plaintext content
_TEXT_EXTS = {".txt", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".py", ".js", ".ts", ".log"}


def _is_plaintext_file(data: bytes) -> bool:
    """Check if data starts with a known file magic signature."""
    for magic, label in _FILE_MAGIC.items():
        if data[:len(magic)] == magic:
            return True
    # Check for common text: ASCII/UTF-8 without null bytes in first 512 bytes
    if len(data) > 0 and b"\x00" not in data[:512]:
        sample = data[:512]
        try:
            sample.decode("utf-8")
            return True  # Looks like text
        except (UnicodeDecodeError, Exception):
            pass
    return False


def _looks_valid(data: bytes, media_type: str = "") -> bool:
    """Heuristic check: does this data look like a valid decrypted file?

    For non-image types (files, videos), we check if the data looks
    like a real file rather than random AES output.
    """
    if len(data) < 4:
        return False
    # Already covered by _is_plaintext_file above, but double-check
    if _is_plaintext_file(data):
        return True
    # For file type attachments, check PK (Office files) or other structured formats
    if data[:4] == b"PK\x03\x04" or data[:4] == b"PK\x05\x06":
        return True
    # Check if there's reasonable structure (not all random bytes)
    # AES ECB on random data would produce near-uniform byte distribution
    # Real files have structure — we check for low-entropy regions
    if len(data) > 100:
        # Sample 256 bytes and check if there are repeated byte values
        # (real files have structure, random AES output doesn't)
        sample = data[:256]
        unique = len(set(sample))
        if unique < 200:  # Real files tend to have repeats
            return True
    return False

# Default base URL for iLink API
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"

# Protocol constants — must match the WeChat ClawBot channel version
CHANNEL_VERSION = "2.4.3"
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = str((2 << 16) | (4 << 8) | 3)  # "132099"

# Long-poll timeout (seconds) — server holds ~35s
_LONG_POLL_TIMEOUT = 45.0
_HTTP_TIMEOUT = 15.0


@dataclass
class QRCodeResult:
    """Result of a QR code request."""
    qrcode: str = ""
    qrcode_img_content: str = ""  # URL, data:image base64, SVG, or raw base64
    state: str = "wait"


@dataclass
class LoginCredentials:
    """Credentials obtained after successful QR code login."""
    bot_token: str = ""
    base_url: str = DEFAULT_BASE_URL  # 'baseurl' from server response
    ilink_bot_id: str = ""
    ilink_user_id: str = ""


@dataclass
class MediaAttachment:
    """A media attachment in an incoming message.

    Maps to ``item_list`` entries with type >= 2 (image/voice/file/video).
    """
    media_type: str = ""        # "image" | "voice" | "file" | "video"
    cdn_url: str = ""
    aes_key: str = ""           # hex or base64 (crypto._normalize_key handles both)
    file_name: str = ""
    file_size: int = 0
    width: int = 0              # image/video only
    height: int = 0             # image/video only
    duration: int = 0           # voice/video only (seconds)
    asr_text: str = ""          # voice only — speech-to-text from server
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class IncomingMessage:
    """A single incoming message from long-poll."""
    from_user: str = ""        # from_user_id
    from_nickname: str = ""    # sender display name (if available)
    content: str = ""          # parsed text from item_list
    context_token: str = ""
    msg_id: str = ""
    msg_type: int = 1          # 1 = incoming text
    chat_type: str = "direct"
    timestamp: int = 0
    get_updates_buf: str = ""  # cursor for next long-poll
    raw: dict[str, Any] = field(default_factory=dict)
    attachments: list[MediaAttachment] = field(default_factory=list)


class WeChatClient:
    """iLink HTTP client — all protocol calls are async.

    Lifecycle:
        1. ``get_qrcode()`` → display QR
        2. ``poll_qrcode()`` → wait for scan → obtain ``LoginCredentials``
        3. ``apply_credentials(creds)`` → set token for message ops
        4. ``get_updates()`` → long-poll loop
        5. ``send_message()`` → reply
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, bot_token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.bot_token = bot_token
        self.ilink_bot_id: str = ""
        self.ilink_user_id: str = ""

        # context_token cache: user_id → latest token
        self._context_store: dict[str, str] = {}

        self._http: httpx.AsyncClient | None = None

    # ---- HTTP helpers ----

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        return self._http

    def _make_uin(self) -> str:
        """Generate X-WECHAT-UIN: base64(decimal_string(random_uint32))."""
        uin_int = random.randint(0, 0xFFFFFFFF)
        return base64.b64encode(str(uin_int).encode("ascii")).decode("ascii")

    def _headers(self, *, authed: bool = True) -> dict[str, str]:
        """Build required headers.

        Every request includes X-WECHAT-UIN and iLink app headers.
        Authenticated requests add Bearer token.
        """
        h = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": self._make_uin(),
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": ILINK_APP_CLIENT_VERSION,
        }
        if authed and self.bot_token:
            h["Authorization"] = f"Bearer {self.bot_token}"
        return h

    def _base_info(self) -> dict[str, str]:
        """The base_info block required in every POST body."""
        return {
            "channel_version": CHANNEL_VERSION,
            "bot_agent": "CrabAgent/1.0",
        }

    async def _post(self, path: str, body: dict, *, authed: bool = True) -> dict[str, Any]:
        http = await self._get_http()
        url = f"{self.base_url}/{path}"
        headers = self._headers(authed=authed)
        try:
            resp = await http.post(url, json=body, headers=headers)
            # Log response headers to detect any token-refresh headers
            h = dict(resp.headers)
            logger.info("[iLink] %s response headers: set-cookie=%s x-context-token=%s x-session=%s",
                        path,
                        h.get("set-cookie", "—")[:80],
                        h.get("x-context-token", h.get("x-session-token", "—"))[:40],
                        h.get("x-session-id", "—"))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("[iLink] HTTP %d for %s: %s", e.response.status_code, path, e.response.text[:300])
            raise
        except Exception as e:
            logger.error("[iLink] POST failed for %s: %s", path, e)
            raise

    async def _get(self, path: str, *, authed: bool = True) -> dict[str, Any]:
        http = await self._get_http()
        url = f"{self.base_url}/{path}"
        headers = self._headers(authed=authed)
        try:
            resp = await http.get(url, headers=headers)
            h = dict(resp.headers)
            logger.info("[iLink] %s response headers: set-cookie=%s x-context-token=%s x-session=%s",
                        path,
                        h.get("set-cookie", "—")[:80],
                        h.get("x-context-token", h.get("x-session-token", "—"))[:40],
                        h.get("x-session-id", "—"))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("[iLink] HTTP %d for %s: %s", e.response.status_code, path, e.response.text[:300])
            raise
        except Exception as e:
            logger.error("[iLink] GET failed for %s: %s", path, e)
            raise

    # ---- Login (Phase 1) ----

    async def get_qrcode(self, bot_type: int = 3) -> QRCodeResult:
        """Request a login QR code.

        Uses POST with ``local_token_list`` (per official SDK),
        with GET fallback for compatibility.
        """
        body = {"local_token_list": [], "base_info": self._base_info()}
        try:
            data = await self._post(
                f"ilink/bot/get_bot_qrcode?bot_type={bot_type}",
                body,
                authed=False,
            )
        except Exception:
            # Fallback to GET
            data = await self._get(
                f"ilink/bot/get_bot_qrcode?bot_type={bot_type}",
                authed=False,
            )

        result = QRCodeResult(
            qrcode=data.get("qrcode", ""),
            qrcode_img_content=data.get("qrcode_img_content", ""),
            state=data.get("status", "wait"),
        )
        logger.info("[iLink] QR code obtained: %s", result.qrcode[:30] + "...")
        return result

    async def poll_qrcode(self, qrcode: str, verify_code: str | None = None) -> dict[str, Any]:
        """Poll the scan status of a QR code.

        Returns a dict with ``status`` (wait/scanned/confirmed/expired/etc.)
        and, on success, ``credentials`` with ``LoginCredentials``.
        """
        from urllib.parse import quote

        endpoint = f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode, safe='')}"
        if verify_code:
            endpoint += f"&verify_code={quote(verify_code, safe='')}"

        data = await self._get(endpoint, authed=False)
        status = data.get("status", "wait")

        result: dict[str, Any] = {"status": status, "raw": data}

        if status == "confirmed" or data.get("bot_token"):
            token = data.get("bot_token", "")
            base_url = data.get("baseurl") or data.get("base_url") or self.base_url
            bot_id = data.get("ilink_bot_id", "")
            user_id = data.get("ilink_user_id", "")

            result["credentials"] = LoginCredentials(
                bot_token=token,
                base_url=base_url,
                ilink_bot_id=bot_id,
                ilink_user_id=user_id,
            )
            logger.info("[iLink] Login confirmed: bot_id=%s", bot_id)

        elif status == "scaned":
            result["scanned"] = True

        elif status == "expired":
            result["expired"] = True

        elif status in ("need_verifycode", "verify_code_blocked"):
            result["need_verifycode"] = True

        elif status == "binded_redirect":
            result["already_connected"] = True

        elif status == "scaned_but_redirect":
            redirect_host = data.get("redirect_host")
            if redirect_host:
                result["redirect_base"] = f"https://{redirect_host}"

        return result

    def apply_credentials(self, creds: LoginCredentials) -> None:
        """Set credentials after successful login."""
        self.bot_token = creds.bot_token
        self.base_url = creds.base_url.rstrip("/")
        self.ilink_bot_id = creds.ilink_bot_id
        self.ilink_user_id = creds.ilink_user_id

    # ---- Message polling (Phase 2) ----

    async def get_updates(self, buf: str = "") -> list[IncomingMessage]:
        """Long-poll for new messages (~35s hold).

        Args:
            buf: Cursor from the last poll (empty for first call).

        Returns:
            List of :class:`IncomingMessage`.
        """
        http = await self._get_http()
        body = {"get_updates_buf": buf, "base_info": self._base_info()}

        try:
            resp = await http.post(
                f"{self.base_url}/ilink/bot/getupdates",
                json=body,
                headers=self._headers(),
                timeout=_LONG_POLL_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.ReadTimeout:
            return []  # Long-poll timeout — normal
        except httpx.HTTPStatusError as e:
            ret_code = None
            try:
                ret_code = e.response.json().get("ret") or e.response.json().get("errcode")
            except Exception:
                pass
            if ret_code == -14:
                raise SessionExpiredError("iLink session expired")
            raise

        # Check for session expiry in response body
        ret = data.get("ret", 0)
        if ret == -14:
            raise SessionExpiredError("iLink session expired")

        # Parse messages
        messages: list[IncomingMessage] = []
        new_buf = data.get("get_updates_buf", "")
        for item in data.get("msgs") or []:
            msg_type = item.get("message_type", 1)
            text = ""
            attachments: list[MediaAttachment] = []

            for list_item in item.get("item_list") or []:
                item_type = list_item.get("type", 0)

                if item_type == 1:  # TEXT
                    text = list_item.get("text_item", {}).get("text", "")

                elif item_type == 2:  # IMAGE
                    img = list_item.get("image_item", {})
                    attachments.append(MediaAttachment(
                        media_type="image",
                        cdn_url=img.get("cdn_url") or img.get("url", ""),
                        aes_key=img.get("aeskey") or img.get("aes_key", ""),
                        width=img.get("width", 0),
                        height=img.get("height", 0),
                        file_size=img.get("file_size", 0),
                        raw=img,
                    ))

                elif item_type == 3:  # VOICE
                    voice = list_item.get("voice_item", {})
                    attachments.append(MediaAttachment(
                        media_type="voice",
                        cdn_url=voice.get("cdn_url") or voice.get("url", ""),
                        aes_key=voice.get("aeskey") or voice.get("aes_key", ""),
                        duration=voice.get("playtime", 0),
                        asr_text=voice.get("text", ""),
                        file_size=voice.get("file_size", 0),
                        raw=voice,
                    ))

                elif item_type == 4:  # FILE
                    f = list_item.get("file_item", {})
                    attachments.append(MediaAttachment(
                        media_type="file",
                        cdn_url=f.get("cdn_url") or f.get("url", ""),
                        aes_key=f.get("aeskey") or f.get("aes_key", ""),
                        file_name=f.get("file_name", ""),
                        file_size=f.get("file_size", 0),
                        raw=f,
                    ))

                elif item_type == 5:  # VIDEO
                    vid = list_item.get("video_item", {})
                    attachments.append(MediaAttachment(
                        media_type="video",
                        cdn_url=vid.get("cdn_url") or vid.get("url", ""),
                        aes_key=vid.get("aeskey") or vid.get("aes_key", ""),
                        width=vid.get("width", 0),
                        height=vid.get("height", 0),
                        duration=vid.get("duration", 0),
                        file_size=vid.get("file_size", 0),
                        raw=vid,
                    ))

            msg = IncomingMessage(
                from_user=item.get("from_user_id", ""),
                from_nickname=item.get("from_nickname", item.get("nickname", "")),
                content=text,
                context_token=item.get("context_token", ""),
                msg_id=str(item.get("msg_id", item.get("id", ""))),
                msg_type=msg_type,
                timestamp=item.get("timestamp", item.get("ts", 0)),
                get_updates_buf=new_buf,
                raw=item,
                attachments=attachments,
            )
            if msg.from_user and msg.context_token:
                self._context_store[msg.from_user] = msg.context_token
            messages.append(msg)

        return messages

    async def send_message(self, to_user: str, text: str, context_token: str = "") -> bool:
        """Send a text message to a user.

        Args:
            to_user: Target user ID (from_user_id).
            text: Message content.
            context_token: Required for replies — use cached if empty.

        Returns:
            ``True`` on success.
        """
        if not context_token:
            context_token = self._context_store.get(to_user, "")

        if not context_token:
            logger.warning("[iLink] No context_token for user %s", to_user)
            return False

        client_id = f"openclaw-weixin-{random.randint(0, 0xFFFFFFFF):08x}"
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user,
                "client_id": client_id,
                "message_type": 2,   # outgoing
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {"type": 1, "text_item": {"text": text}}
                ],
            },
            "base_info": self._base_info(),
        }

        try:
            data = await self._post("ilink/bot/sendmessage", body)
            ret = data.get("ret", 0)
            # Server may return a refreshed context_token — use it
            new_token = data.get("context_token") or data.get("new_context_token", "")
            if new_token and new_token != context_token:
                self._context_store[to_user] = new_token
                logger.info("[iLink] send_message got refreshed context_token: %.20s", new_token)
            if ret == -14:
                raise SessionExpiredError("iLink session expired")
            if ret != 0:
                logger.warning("[iLink] send_message ret=%s, data=%s", ret, str(data)[:200])
                return False
            logger.info("[iLink] send_message success, response keys: %s", list(data.keys()))
            return True
        except SessionExpiredError:
            raise
        except Exception as e:
            logger.error("[iLink] send_message failed: %s", e)
            return False

    async def send_typing(self, to_user: str, status: int = 1) -> None:
        """Send "is typing" indicator.

        Two-step: first get typing_ticket via getconfig, then sendtyping.

        Args:
            to_user: Target user ID.
            status: 1 = typing, 2 = stopped.
        """
        context_token = self._context_store.get(to_user, "")
        if not context_token:
            return

        # Step 1: get typing_ticket
        body = {
            "ilink_user_id": to_user,
            "context_token": context_token,
            "base_info": self._base_info(),
        }
        try:
            data = await self._post("ilink/bot/getconfig", body)
            # Server may return a refreshed context_token — use it
            new_token = data.get("context_token") or data.get("new_context_token", "")
            if new_token and new_token != context_token:
                self._context_store[to_user] = new_token
                context_token = new_token
                logger.info("[iLink] getconfig got refreshed context_token: %.20s", new_token)
            typing_ticket = data.get("typing_ticket", "")
            if not typing_ticket:
                logger.info("[iLink] getconfig success (no typing_ticket), response keys: %s", list(data.keys()))
                return
            logger.info("[iLink] getconfig success, has typing_ticket, response keys: %s", list(data.keys()))
        except Exception as e:
            logger.debug("[iLink] getconfig failed: %s", e)
            return

        # Step 2: send typing
        body2 = {
            "ilink_user_id": to_user,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": self._base_info(),
        }
        try:
            await self._post("ilink/bot/sendtyping", body2)
        except Exception:
            pass  # Non-critical

    # ---- Media: download ----

    async def download_media(self, attachment: MediaAttachment) -> bytes:
        """Download and AES-decrypt a media attachment from CDN.

        Handles both direct URLs and CDN encrypt_query_param references.
        Returns the raw plaintext bytes.  On error returns empty bytes.
        """
        from urllib.parse import quote

        # Determine download URL
        cdn_base = "https://novac2c.cdn.weixin.qq.com/c2c"
        raw = attachment.raw
        media = raw.get("media", {}) if raw else {}
        eqp = media.get("encrypt_query_param", "")
        if eqp:
            download_url = f"{cdn_base}/download?encrypted_query_param={quote(eqp, safe='')}"
        elif attachment.cdn_url:
            download_url = attachment.cdn_url
        else:
            logger.warning(
                "[iLink] download_media: no download URL — raw keys=%s, media=%s",
                list(raw.keys()) if raw else "None",
                media,
            )
            return b""

        logger.info("[iLink] download_media: URL=%s, aes_key=%s", download_url[:120], bool(media.get("aes_key") or attachment.aes_key))

        http = await self._get_http()
        try:
            resp = await http.get(download_url, timeout=30.0)
            resp.raise_for_status()
        except Exception as e:
            logger.error("[iLink] CDN download failed: %s", e)
            return b""

        encrypted = resp.content

        # Determine media type for validation
        att_media_type = attachment.media_type or ""

        # If CDN already returned plaintext file, skip decryption
        if _is_plaintext_file(encrypted):
            logger.info("[iLink] CDN returned plaintext file (%d bytes), skipping decrypt", len(encrypted))
            return encrypted

        # Resolve AES key — prefer the top-level aeskey (hex format) over
        # media.aes_key (which is base64-of-hex, harder to parse correctly)
        aes_key = attachment.aes_key or media.get("aes_key", "")
        if aes_key:
            try:
                from crabagent.core.wechat.crypto import decrypt
                decrypted = decrypt(encrypted, aes_key)
                
                # Verify decrypted data looks like a valid file
                if _is_plaintext_file(decrypted) or _looks_valid(decrypted, att_media_type):
                    logger.info("[iLink] AES decrypt OK: %d bytes plaintext", len(decrypted))
                    return decrypted

                # Decryption produced unrecognized data — try alternative key interpretations
                logger.warning("[iLink] AES decrypt produced unrecognized data, trying alternative keys...")
                
                import hashlib as _hl
                from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher, algorithms as _alg, modes as _modes
                
                raw_key_str = attachment.aes_key or media.get("aes_key", "")
                alt_keys = [
                    ("raw_ascii_16", raw_key_str.encode("utf-8")[:16]),
                    ("md5_of_str", _hl.md5(raw_key_str.encode("utf-8")).digest()),
                    ("base64_decoded", base64.b64decode(raw_key_str) if len(raw_key_str) >= 20 else b""),
                ]
                
                for label, alt_k in alt_keys:
                    if len(alt_k) != 16:
                        continue
                    try:
                        c = _Cipher(_alg.AES(alt_k), _modes.ECB())
                        d = c.decryptor()
                        result = d.update(encrypted) + d.finalize()
                        if _is_plaintext_file(result) or _looks_valid(result, att_media_type):
                            logger.info("[iLink] Valid data with alt key '%s'", label)
                            pad = result[-1]
                            if 1 <= pad <= 16:
                                result = result[:-pad]
                            return result
                    except Exception:
                        pass
                
                logger.error("[iLink] All key interpretations failed, data is corrupted")
                return b""
            except Exception as e:
                logger.error("[iLink] AES decrypt failed: %s", e)
                return encrypted

        logger.warning("[iLink] download_media: no AES key, returning encrypted data")
        return encrypted

    # ---- Media: upload ----

    _CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"

    # Upload media_type mapping (1=IMAGE, 2=VIDEO, 3=FILE, 4=VOICE)
    _MEDIA_TYPE_IMAGE = 1
    _MEDIA_TYPE_VIDEO = 2
    _MEDIA_TYPE_FILE = 3
    _MEDIA_TYPE_VOICE = 4

    async def upload_media(
        self,
        file_path,
        media_type: int,
        to_user: str,
    ) -> dict[str, Any] | None:
        """Encrypt and upload a media file to WeChat CDN.

        Args:
            file_path: ``Path`` to the local file.
            media_type: 1=IMAGE, 2=VIDEO, 3=FILE, 4=VOICE.
            to_user: Target user ID (required by getuploadurl).

        Returns dict with ``encrypt_query_param``, ``aes_key_hex``,
        ``raw_size``, ``enc_size``, ``raw_md5`` or ``None`` on failure.
        """
        import hashlib
        import os

        from crabagent.core.wechat import crypto

        raw_bytes = file_path.read_bytes()
        raw_size = len(raw_bytes)
        raw_md5 = hashlib.md5(raw_bytes).hexdigest()

        # Random AES-128 key
        aes_key_hex = os.urandom(16).hex()

        # Encrypt (AES-128-ECB + PKCS7)
        encrypted = crypto.encrypt(raw_bytes, aes_key_hex)
        enc_size = len(encrypted)

        # Random file key
        file_key = os.urandom(16).hex()

        body = {
            "filekey": file_key,
            "media_type": media_type,
            "to_user_id": to_user,
            "rawsize": raw_size,
            "rawfilemd5": raw_md5,
            "filesize": enc_size,
            "no_need_thumb": True,
            "aeskey": aes_key_hex,
            "base_info": self._base_info(),
        }

        try:
            data = await self._post("ilink/bot/getuploadurl", body)
        except Exception as e:
            logger.error("[iLink] getuploadurl failed: %s", e)
            return None

        # The API may return:
        #   - "upload_full_url": complete CDN upload URL (observed in production)
        #   - "upload_param": just the encrypted_query_param value (protocol spec)
        upload_full_url = data.get("upload_full_url", "")
        upload_param = data.get("upload_param", "")

        if upload_full_url:
            # Server returned a complete URL — append filekey if not present
            cdn_upload_url = upload_full_url
            if "filekey" not in cdn_upload_url:
                cdn_upload_url += f"&filekey={file_key}"
        elif upload_param:
            from urllib.parse import quote as _quote
            eq = _quote(upload_param, safe='')
            cdn_upload_url = f"{self._CDN_BASE}/upload?encrypted_query_param={eq}&filekey={file_key}"
        else:
            logger.error("[iLink] getuploadurl returned no upload URL: %s", str(data)[:300])
            return None

        # Upload encrypted data to CDN
        http = await self._get_http()
        try:
            resp = await http.post(
                cdn_upload_url,
                content=encrypted,
                headers={"Content-Type": "application/octet-stream"},
                timeout=60.0,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("[iLink] CDN upload failed: %s", e)
            return None

        # Download param from response header
        download_param = resp.headers.get("x-encrypted-param", "")
        if not download_param:
            logger.warning("[iLink] CDN upload response missing x-encrypted-param")
            download_param = upload_param  # fallback

        return {
            "encrypt_query_param": download_param,
            "aes_key_hex": aes_key_hex,
            "raw_size": raw_size,
            "enc_size": enc_size,
            "raw_md5": raw_md5,
        }

    @staticmethod
    def _aes_key_to_b64_of_hex(aes_key_hex: str) -> str:
        """Convert AES key to "base64(hex string)" format (protocol format B)."""
        import base64 as _b64
        return _b64.b64encode(aes_key_hex.encode("ascii")).decode("ascii")

    # ---- Media: send image / file ----

    async def send_image(
        self,
        to_user: str,
        image_path,
        context_token: str = "",
    ) -> bool:
        """Send an image file to a WeChat user."""
        if not context_token:
            context_token = self._context_store.get(to_user, "")
        if not context_token:
            logger.warning("[iLink] send_image: no context_token for %s", to_user)
            return False

        upload = await self.upload_media(image_path, self._MEDIA_TYPE_IMAGE, to_user)
        if not upload:
            return False

        aes_key_b64 = self._aes_key_to_b64_of_hex(upload["aes_key_hex"])
        client_id = f"openclaw-weixin-{random.randint(0, 0xFFFFFFFF):08x}"
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": 2,
                        "image_item": {
                            "media": {
                                "encrypt_query_param": upload["encrypt_query_param"],
                                "aes_key": aes_key_b64,
                                "encrypt_type": 1,
                            },
                            "mid_size": upload["enc_size"],
                        },
                    }
                ],
            },
            "base_info": self._base_info(),
        }

        try:
            data = await self._post("ilink/bot/sendmessage", body)
            ret = data.get("ret", 0)
            if ret == -14:
                raise SessionExpiredError("iLink session expired")
            if ret != 0:
                logger.warning("[iLink] send_image ret=%s, data=%s", ret, str(data)[:200])
                return False
            logger.info("[iLink] send_image success: %s", image_path)
            return True
        except SessionExpiredError:
            raise
        except Exception as e:
            logger.error("[iLink] send_image failed: %s", e)
            return False

    async def send_file(
        self,
        to_user: str,
        file_path,
        context_token: str = "",
    ) -> bool:
        """Send a file attachment to a WeChat user."""
        if not context_token:
            context_token = self._context_store.get(to_user, "")
        if not context_token:
            logger.warning("[iLink] send_file: no context_token for %s", to_user)
            return False

        upload = await self.upload_media(file_path, self._MEDIA_TYPE_FILE, to_user)
        if not upload:
            return False

        aes_key_b64 = self._aes_key_to_b64_of_hex(upload["aes_key_hex"])
        client_id = f"openclaw-weixin-{random.randint(0, 0xFFFFFFFF):08x}"
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": 4,
                        "file_item": {
                            "media": {
                                "encrypt_query_param": upload["encrypt_query_param"],
                                "aes_key": aes_key_b64,
                                "encrypt_type": 1,
                            },
                            "file_name": file_path.name,
                            "md5": upload["raw_md5"],
                            "len": str(upload["raw_size"]),
                        },
                    }
                ],
            },
            "base_info": self._base_info(),
        }

        try:
            data = await self._post("ilink/bot/sendmessage", body)
            ret = data.get("ret", 0)
            if ret == -14:
                raise SessionExpiredError("iLink session expired")
            if ret != 0:
                logger.warning("[iLink] send_file ret=%s, data=%s", ret, str(data)[:200])
                return False
            logger.info("[iLink] send_file success: %s", file_path)
            return True
        except SessionExpiredError:
            raise
        except Exception as e:
            logger.error("[iLink] send_file failed: %s", e)
            return False

    # ---- Context token management ----

    def get_context_token(self, user_id: str) -> str:
        return self._context_store.get(user_id, "")

    def clear_context_token(self, user_id: str) -> None:
        self._context_store.pop(user_id, None)

    def clear_all_tokens(self) -> None:
        self._context_store.clear()

    # ---- Cleanup ----

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None


class SessionExpiredError(Exception):
    """Raised when the iLink session token has expired (ret/errcode -14)."""
