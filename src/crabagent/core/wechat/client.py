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
            # Only process incoming text messages (message_type 1)
            msg_type = item.get("message_type", 1)
            # Extract text from item_list
            text = ""
            for list_item in item.get("item_list") or []:
                if list_item.get("type") == 1:
                    text = list_item.get("text_item", {}).get("text", "")
                    break

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
            if ret == -14:
                raise SessionExpiredError("iLink session expired")
            if ret != 0:
                logger.warning("[iLink] send_message ret=%s, data=%s", ret, str(data)[:200])
                return False
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
            typing_ticket = data.get("typing_ticket", "")
            if not typing_ticket:
                return
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

    # ---- Media (Phase 3) ----

    async def get_upload_url(self, file_key: str, media_type: int, raw_size: int, file_size: int, aes_key: str) -> dict[str, Any]:
        """Request CDN upload parameters for media files."""
        body = {
            "filekey": file_key,
            "media_type": media_type,
            "rawsize": raw_size,
            "filesize": file_size,
            "aeskey": aes_key,
            "base_info": self._base_info(),
        }
        return await self._post("ilink/bot/getuploadurl", body)

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
