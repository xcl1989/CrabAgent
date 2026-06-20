"""ChatGPT subscription OAuth authentication API.

Provides endpoints for the OAuth device code flow:
  - Request a device code (user visits auth.openai.com to authorize)
  - Poll for login completion
  - Check stored token validity
  - Query account info / rate limits from ChatGPT backend

litellm already ships a complete Authenticator implementation
(litellm.llms.chatgpt.authenticator.Authenticator). This module wraps it
into async-friendly FastAPI endpoints and adds a quota/usage query.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from crabagent.core.database import User
from crabagent.serve.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatgpt", tags=["chatgpt"])

# ── Constants (mirrored from litellm.llms.chatgpt.common_utils) ──

CHATGPT_AUTH_BASE = "https://auth.openai.com"
CHATGPT_DEVICE_CODE_URL = f"{CHATGPT_AUTH_BASE}/api/accounts/deviceauth/usercode"
CHATGPT_DEVICE_TOKEN_URL = f"{CHATGPT_AUTH_BASE}/api/accounts/deviceauth/token"
CHATGPT_OAUTH_TOKEN_URL = f"{CHATGPT_AUTH_BASE}/oauth/token"
CHATGPT_DEVICE_VERIFY_URL = f"{CHATGPT_AUTH_BASE}/codex/device"
CHATGPT_API_BASE = "https://chatgpt.com/backend-api/codex"
CHATGPT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

CHATGPT_TOKEN_DIR = os.getenv(
    "CHATGPT_TOKEN_DIR",
    os.path.expanduser("~/.config/litellm/chatgpt"),
)
CHATGPT_AUTH_FILE = os.path.join(CHATGPT_TOKEN_DIR, os.getenv("CHATGPT_AUTH_FILE", "auth.json"))

# In-memory device code sessions (short-lived)
_device_code_cache: dict[str, dict[str, Any]] = {}
_DEVICE_CODE_TTL = 15 * 60  # 15 minutes


def _parse_float_header(headers: dict, key: str) -> float | None:
    val = headers.get(key)
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int_header(headers: dict, key: str) -> int | None:
    val = headers.get(key)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ── Pydantic Models ──


class DeviceCodeResponse(BaseModel):
    device_auth_id: str
    user_code: str
    verification_url: str
    interval: int
    expires_in: int


class AuthStatusResponse(BaseModel):
    authenticated: bool
    access_token_preview: str = ""
    expires_at: int | None = None
    account_id: str | None = None
    error: str | None = None


class AccountInfoResponse(BaseModel):
    plan: str | None = None
    email: str | None = None
    name: str | None = None
    account_id: str | None = None
    rate_limits: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


# ── Token file helpers ──


def _read_auth_file() -> dict[str, Any] | None:
    try:
        with open(CHATGPT_AUTH_FILE) as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None


def _write_auth_file(data: dict[str, Any]) -> None:
    os.makedirs(CHATGPT_TOKEN_DIR, exist_ok=True)
    with open(CHATGPT_AUTH_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return {}


def _is_token_expired(auth_data: dict[str, Any], access_token: str) -> bool:
    expires_at = auth_data.get("expires_at")
    if expires_at is None:
        expires_at = _get_expires_at(access_token)
    if expires_at is None:
        return True
    return time.time() >= float(expires_at) - 60


def _get_expires_at(token: str) -> int | None:
    claims = _decode_jwt_claims(token)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp)
    return None


def _extract_account_id(token: str | None) -> str | None:
    if not token:
        return None
    claims = _decode_jwt_claims(token)
    auth_claims = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        account_id = auth_claims.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


# ── OAuth endpoints ──


async def _request_device_code() -> dict[str, Any]:
    """Request a device authorization code from OpenAI."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            CHATGPT_DEVICE_CODE_URL,
            json={"client_id": CHATGPT_CLIENT_ID},
        )
        resp.raise_for_status()
        return resp.json()


async def _poll_device_token(device_auth_id: str, user_code: str) -> dict[str, Any] | None:
    """Poll once for device authorization (returns code data if authorized)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            CHATGPT_DEVICE_TOKEN_URL,
            json={"device_auth_id": device_auth_id, "user_code": user_code},
        )
        if resp.status_code == 200:
            data = resp.json()
            if all(k in data for k in ("authorization_code", "code_challenge", "code_verifier")):
                return data
        return None


async def _exchange_code_for_tokens(code_data: dict[str, Any]) -> dict[str, Any]:
    """Exchange authorization code for access/refresh tokens."""
    redirect_uri = f"{CHATGPT_AUTH_BASE}/deviceauth/callback"
    body = (
        f"grant_type=authorization_code"
        f"&code={code_data['authorization_code']}"
        f"&redirect_uri={redirect_uri}"
        f"&client_id={CHATGPT_CLIENT_ID}"
        f"&code_verifier={code_data['code_verifier']}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            CHATGPT_OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=body,
        )
        resp.raise_for_status()
        return resp.json()


async def _refresh_tokens(refresh_token: str) -> dict[str, Any]:
    """Refresh expired access token."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            CHATGPT_OAUTH_TOKEN_URL,
            json={
                "client_id": CHATGPT_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid profile email",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_chatgpt_access_token() -> str:
    """Get a valid ChatGPT access token, refreshing if needed.

    Raises HTTPException if authentication is required.
    """
    auth_data = _read_auth_file()
    if auth_data:
        access_token = auth_data.get("access_token", "")
        if access_token and not _is_token_expired(auth_data, access_token):
            return access_token
        refresh_token = auth_data.get("refresh_token")
        if refresh_token:
            try:
                refreshed = await _refresh_tokens(refresh_token)
                access_token = refreshed["access_token"]
                id_token = refreshed.get("id_token", "")
                expires_at = _get_expires_at(access_token) if access_token else None
                account_id = _extract_account_id(id_token or access_token)
                _write_auth_file({
                    "access_token": access_token,
                    "refresh_token": refreshed.get("refresh_token", refresh_token),
                    "id_token": id_token,
                    "expires_at": expires_at,
                    "account_id": account_id,
                })
                return access_token
            except Exception as e:
                logger.warning("ChatGPT refresh token failed: %s", e)

    raise HTTPException(status_code=401, detail="ChatGPT authentication required. Start device code login.")


# ── API Routes ──


@router.get("/auth/status", response_model=AuthStatusResponse)
async def get_auth_status(user: User = Depends(get_current_user)):
    """Check if ChatGPT subscription is authenticated."""
    auth_data = _read_auth_file()
    if not auth_data:
        return AuthStatusResponse(authenticated=False)

    access_token = auth_data.get("access_token", "")
    if not access_token:
        return AuthStatusResponse(authenticated=False)

    expired = _is_token_expired(auth_data, access_token)
    # If expired but we have a refresh token, try refreshing
    if expired:
        refresh_token = auth_data.get("refresh_token")
        if refresh_token:
            try:
                refreshed = await _refresh_tokens(refresh_token)
                access_token = refreshed["access_token"]
                id_token = refreshed.get("id_token", "")
                expires_at = _get_expires_at(access_token) if access_token else None
                account_id = _extract_account_id(id_token or access_token)
                _write_auth_file({
                    "access_token": access_token,
                    "refresh_token": refreshed.get("refresh_token", refresh_token),
                    "id_token": id_token,
                    "expires_at": expires_at,
                    "account_id": account_id,
                })
            except Exception as e:
                return AuthStatusResponse(
                    authenticated=False,
                    error=f"Token expired and refresh failed: {e}",
                )
        else:
            return AuthStatusResponse(
                authenticated=False,
                error="Token expired, no refresh token. Re-login required.",
            )

    return AuthStatusResponse(
        authenticated=True,
        access_token_preview=access_token[:16] + "..." if len(access_token) > 16 else "****",
        expires_at=auth_data.get("expires_at"),
        account_id=auth_data.get("account_id") or _extract_account_id(access_token),
    )


@router.post("/auth/device-code", response_model=DeviceCodeResponse)
async def start_device_code_auth(user: User = Depends(get_current_user)):
    """Start OAuth device code flow — returns a code for the user to authorize."""
    try:
        device_data = await _request_device_code()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Failed to request device code: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Device code request failed: {e}")

    device_auth_id = device_data.get("device_auth_id")
    user_code = device_data.get("user_code") or device_data.get("usercode")
    interval = int(device_data.get("interval", 5))

    if not device_auth_id or not user_code:
        raise HTTPException(status_code=502, detail=f"Invalid device code response: {device_data}")

    # Cache for polling
    _device_code_cache[user_code] = {
        "device_auth_id": device_auth_id,
        "user_code": user_code,
        "created_at": time.time(),
    }

    return DeviceCodeResponse(
        device_auth_id=device_auth_id,
        user_code=user_code,
        verification_url=CHATGPT_DEVICE_VERIFY_URL,
        interval=interval,
        expires_in=_DEVICE_CODE_TTL,
    )


@router.post("/auth/poll", response_model=AuthStatusResponse)
async def poll_device_auth(
    device_auth_id: str,
    user_code: str,
    user: User = Depends(get_current_user),
):
    """Poll once for device authorization completion."""
    # Cleanup expired sessions
    now = time.time()
    expired_keys = [k for k, v in _device_code_cache.items() if now - v.get("created_at", 0) > _DEVICE_CODE_TTL]
    for k in expired_keys:
        _device_code_cache.pop(k, None)

    # Poll for authorization code
    code_data = await _poll_device_token(device_auth_id, user_code)
    if not code_data:
        return AuthStatusResponse(
            authenticated=False,
            error="pending",
        )

    # Exchange code for tokens
    try:
        tokens = await _exchange_code_for_tokens(code_data)
    except Exception as e:
        return AuthStatusResponse(
            authenticated=False,
            error=f"Token exchange failed: {e}",
        )

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    id_token = tokens.get("id_token", "")
    expires_at = _get_expires_at(access_token) if access_token else None
    account_id = _extract_account_id(id_token or access_token)

    _write_auth_file({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "expires_at": expires_at,
        "account_id": account_id,
    })

    # Clean up session
    _device_code_cache.pop(user_code, None)

    return AuthStatusResponse(
        authenticated=True,
        access_token_preview=access_token[:16] + "..." if len(access_token) > 16 else "****",
        expires_at=expires_at,
        account_id=account_id,
    )


@router.post("/auth/logout")
async def logout(user: User = Depends(get_current_user)):
    """Clear stored ChatGPT OAuth tokens."""
    try:
        os.remove(CHATGPT_AUTH_FILE)
    except FileNotFoundError:
        pass
    return {"status": "ok"}


@router.get("/account", response_model=AccountInfoResponse)
async def get_account_info(user: User = Depends(get_current_user)):
    """Fetch real-time account info and usage from ChatGPT Codex backend.

    Makes a lightweight API call to /codex/responses and captures the
    x-codex-* rate limit headers, which contain real-time usage data:
    - primary/secondary usage percentage (rolling window)
    - window duration (5h primary, 7d secondary)
    - reset timestamps
    - plan type, active limit tier, credits

    Also extracts email/plan from the JWT claims (no extra API call needed).
    """
    try:
        access_token = await get_chatgpt_access_token()
    except HTTPException:
        return AccountInfoResponse()

    auth_data = _read_auth_file() or {}
    account_id = auth_data.get("account_id") or _extract_account_id(access_token)

    # Decode JWT for static account info
    claims = _decode_jwt_claims(access_token)
    auth_claims = claims.get("https://api.openai.com/auth", {})
    profile_claims = claims.get("https://api.openai.com/profile", {})

    plan_from_jwt = auth_claims.get("chatgpt_plan_type", "")
    email = profile_claims.get("email", "")

    # Make a minimal API call to get real-time rate limit headers
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "accept": "text/event-stream",
        "User-Agent": "codex_cli_rs/0.0.0 (Darwin 24.0; arm64) xterm-256color",
        "originator": "codex_cli_rs",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    # Minimal payload — gpt-5.4 is the model that actually works for Plus accounts
    payload = {
        "model": "gpt-5.4",
        "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        "instructions": "Reply with one word.",
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }

    rate_limits: dict[str, Any] = {}
    plan_from_header = ""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "POST",
                f"{CHATGPT_API_BASE}/responses",
                headers=headers,
                json=payload,
            ) as resp:
                # Rate limit info is in response headers — available immediately
                resp_headers = dict(resp.headers)
                plan_from_header = resp_headers.get("x-codex-plan-type", "")

                primary_used = _parse_float_header(resp_headers, "x-codex-primary-used-percent")
                secondary_used = _parse_float_header(resp_headers, "x-codex-secondary-used-percent")
                primary_window = _parse_int_header(resp_headers, "x-codex-primary-window-minutes")
                secondary_window = _parse_int_header(resp_headers, "x-codex-secondary-window-minutes")
                primary_reset = _parse_int_header(resp_headers, "x-codex-primary-reset-after-seconds")
                secondary_reset = _parse_int_header(resp_headers, "x-codex-secondary-reset-after-seconds")

                rate_limits = {
                    "active_limit": resp_headers.get("x-codex-active-limit", ""),
                    "plan": plan_from_header or plan_from_jwt,
                    "primary": {
                        "used_percent": primary_used,
                        "window_hours": round(primary_window / 60, 1) if primary_window else None,
                        "reset_after_minutes": round(primary_reset / 60, 1) if primary_reset else None,
                    },
                    "secondary": {
                        "used_percent": secondary_used,
                        "window_days": round(secondary_window / 1440, 1) if secondary_window else None,
                        "reset_after_hours": round(secondary_reset / 3600, 1) if secondary_reset else None,
                    },
                    "credits": {
                        "has_credits": resp_headers.get("x-codex-credits-has-credits", "").lower() == "true",
                        "balance": resp_headers.get("x-codex-credits-balance", ""),
                        "unlimited": resp_headers.get("x-codex-credits-unlimited", "").lower() == "true",
                    },
                }

                # Close stream immediately — we only needed headers
                resp.aclose()
    except Exception as e:
        logger.debug("Failed to fetch rate limits from Codex API: %s", e)
        # Fall back to JWT-only info
        rate_limits = {
            "plan": plan_from_jwt,
            "error": f"Unable to fetch real-time usage: {e}",
        }

    return AccountInfoResponse(
        plan=plan_from_header or plan_from_jwt or None,
        email=email or None,
        account_id=account_id,
        rate_limits=rate_limits if rate_limits else None,
    )


@router.get("/models")
async def list_chatgpt_models(user: User = Depends(get_current_user)):
    """List available ChatGPT subscription models."""
    from crabagent.core.provider_store import CHATGPT_MODELS

    return [{"id": m, "owned_by": "chatgpt"} for m in CHATGPT_MODELS]
