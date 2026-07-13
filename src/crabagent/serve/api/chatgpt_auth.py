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

import base64
import json
import logging
import os
import time
import uuid
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


def _build_window_info(
    used_percent: float | int | None,
    window_seconds: int | None,
    reset_after_seconds: int | None,
) -> dict[str, Any]:
    """Build a unified rate-limit window dict from raw API seconds.

    The frontend reads ``window_seconds`` and ``reset_after_seconds`` to
    dynamically format labels (hours/days) without hardcoding any assumption
    about the window duration.
    """
    info: dict[str, Any] = {
        "used_percent": used_percent,
        "window_seconds": window_seconds,
        "reset_after_seconds": reset_after_seconds,
    }
    return info


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
    except (OSError, json.JSONDecodeError):
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

    Makes a lightweight API call to /wham/usage and extracts:
    - primary/secondary usage percentage (rolling window)
    - window duration and reset time in raw seconds (frontend formats dynamically)
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

    # ── Strategy: try /wham/usage first (single call, richer data, no token cost).
    #    Fall back to /codex/responses stream headers if wham is unavailable. ──
    wham_headers = _build_wham_headers(access_token, account_id)

    rate_limits: dict[str, Any] = {}
    plan_from_header = ""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{CHATGPT_WHAM_BASE}/usage",
                headers=wham_headers,
            )
            resp.raise_for_status()
            usage = resp.json()

            plan_from_header = usage.get("plan_type", "")
            rl = usage.get("rate_limit", {})

            primary = rl.get("primary_window") or {}
            secondary = rl.get("secondary_window")  # May be None

            rate_limits = {
                "active_limit": "",
                "plan": plan_from_header or plan_from_jwt,
                "primary": _build_window_info(
                    primary.get("used_percent"),
                    primary.get("limit_window_seconds"),
                    primary.get("reset_after_seconds"),
                ),
                "secondary": _build_window_info(
                    secondary.get("used_percent") if secondary else None,
                    secondary.get("limit_window_seconds") if secondary else None,
                    secondary.get("reset_after_seconds") if secondary else None,
                )
                if secondary
                else None,
                "credits": usage.get("credits", {}),
            }

            # Include banked reset info from the same response
            rlrc = usage.get("rate_limit_reset_credits", {})
            if rlrc:
                rate_limits["banked_resets"] = {
                    "available_count": rlrc.get("available_count", 0),
                    "credits": [],
                }
    except Exception as e:
        logger.debug("Failed to fetch /wham/usage, falling back to /codex/responses: %s", e)

        # ── Fallback: make a minimal /codex/responses call and parse x-codex-* headers ──
        codex_headers = {
            **wham_headers,
            "accept": "text/event-stream",
        }
        payload = {
            "model": "gpt-5.4",
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
            "instructions": "Reply with one word.",
            "stream": True,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream(
                    "POST",
                    f"{CHATGPT_API_BASE}/responses",
                    headers=codex_headers,
                    json=payload,
                ) as resp:
                    resp_headers = dict(resp.headers)
                    plan_from_header = resp_headers.get("x-codex-plan-type", "")

                    primary_used = _parse_float_header(resp_headers, "x-codex-primary-used-percent")
                    secondary_used = _parse_float_header(resp_headers, "x-codex-secondary-used-percent")
                    primary_window_min = _parse_int_header(resp_headers, "x-codex-primary-window-minutes")
                    secondary_window_min = _parse_int_header(resp_headers, "x-codex-secondary-window-minutes")
                    primary_reset = _parse_int_header(resp_headers, "x-codex-primary-reset-after-seconds")
                    secondary_reset = _parse_int_header(resp_headers, "x-codex-secondary-reset-after-seconds")

                    primary_window_s = primary_window_min * 60 if primary_window_min else None
                    secondary_window_s = secondary_window_min * 60 if secondary_window_min else None

                    has_secondary = (
                        secondary_used is not None
                        or secondary_window_s is not None
                        or secondary_reset is not None
                    )

                    rate_limits = {
                        "active_limit": resp_headers.get("x-codex-active-limit", ""),
                        "plan": plan_from_header or plan_from_jwt,
                        "primary": _build_window_info(
                            primary_used, primary_window_s, primary_reset,
                        ),
                        "secondary": _build_window_info(
                            secondary_used, secondary_window_s, secondary_reset,
                        )
                        if has_secondary
                        else None,
                        "credits": {
                            "has_credits": resp_headers.get("x-codex-credits-has-credits", "").lower() == "true",
                            "balance": resp_headers.get("x-codex-credits-balance", ""),
                            "unlimited": resp_headers.get("x-codex-credits-unlimited", "").lower() == "true",
                        },
                    }

                    resp.aclose()
        except Exception as e2:
            logger.debug("Fallback /codex/responses also failed: %s", e2)
            rate_limits = {
                "plan": plan_from_jwt,
                "error": f"Unable to fetch real-time usage: {e2}",
            }

    # Try to also fetch detailed banked reset credits (best-effort, non-blocking)
    try:
        reset_credits = await _fetch_reset_credits(access_token, account_id)
        if rate_limits is None:
            rate_limits = {}
        if "banked_resets" not in rate_limits:
            rate_limits["banked_resets"] = {
                "available_count": len(reset_credits),
                "credits": reset_credits,
            }
        else:
            # Enrich with credit details from the dedicated endpoint
            rate_limits["banked_resets"]["credits"] = reset_credits
    except Exception as e:
        logger.debug("Failed to fetch reset credits: %s", e)

    return AccountInfoResponse(
        plan=plan_from_header or plan_from_jwt or None,
        email=email or None,
        account_id=account_id,
        rate_limits=rate_limits if rate_limits else None,
    )


# ── Rate-Limit Reset (Banked Resets) ──

CHATGPT_WHAM_BASE = "https://chatgpt.com/backend-api/wham"


def _build_wham_headers(access_token: str, account_id: str | None) -> dict[str, str]:
    """Build the headers required for /wham/* endpoints."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "accept": "application/json",
        "User-Agent": "codex_cli_rs/0.0.0 (Darwin 24.0; arm64) xterm-256color",
        "originator": "codex_cli_rs",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    return headers


async def _fetch_reset_credits(access_token: str, account_id: str | None) -> list[dict[str, Any]]:
    """GET /wham/rate-limit-reset-credits — list banked reset credits."""
    headers = _build_wham_headers(access_token, account_id)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{CHATGPT_WHAM_BASE}/rate-limit-reset-credits", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        # Response shape: { credits: [{ id, reset_type, available_count, expires_at, ... }], available_count: N }
        if isinstance(data, dict):
            return data.get("credits", [])
        return []


async def _consume_reset_credit(
    access_token: str, account_id: str | None, credit_id: str
) -> dict[str, Any]:
    """POST /wham/rate-limit-reset-credits/consume — redeem a banked reset."""
    headers = _build_wham_headers(access_token, account_id)
    body = {
        "selected_credit": credit_id,
        "idempotency_key": str(uuid.uuid4()),
        "redeem_request_id": str(uuid.uuid4()),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{CHATGPT_WHAM_BASE}/rate-limit-reset-credits/consume",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        # Successful consume returns { "status": "reset" } or similar
        return resp.json()


async def _fetch_rate_limit_status(access_token: str, account_id: str | None) -> dict[str, Any]:
    """GET /wham/rate-limit-status — fetch current rate limit status."""
    headers = _build_wham_headers(access_token, account_id)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{CHATGPT_WHAM_BASE}/rate-limit-status", headers=headers)
        resp.raise_for_status()
        return resp.json()


@router.get("/reset-credits")
async def get_reset_credits(user: User = Depends(get_current_user)):
    """List available banked rate-limit reset credits."""
    try:
        access_token = await get_chatgpt_access_token()
    except HTTPException:
        return {"credits": [], "available_count": 0, "error": "Not authenticated"}

    auth_data = _read_auth_file() or {}
    account_id = auth_data.get("account_id") or _extract_account_id(access_token)

    try:
        credits = await _fetch_reset_credits(access_token, account_id)
        return {
            "credits": credits,
            "available_count": len(credits),
        }
    except Exception as e:
        logger.warning("Failed to fetch reset credits: %s", e)
        return {"credits": [], "available_count": 0, "error": str(e)}


class ConsumeResetRequest(BaseModel):
    credit_id: str


@router.post("/reset-credits/consume")
async def consume_reset_credit_endpoint(
    req: ConsumeResetRequest, user: User = Depends(get_current_user)
):
    """Consume (redeem) one banked rate-limit reset credit."""
    try:
        access_token = await get_chatgpt_access_token()
    except HTTPException:
        raise HTTPException(status_code=401, detail="ChatGPT authentication required")

    auth_data = _read_auth_file() or {}
    account_id = auth_data.get("account_id") or _extract_account_id(access_token)

    try:
        result = await _consume_reset_credit(access_token, account_id, req.credit_id)
        return {"status": "ok", "result": result}
    except httpx.HTTPStatusError as e:
        detail = f"Reset failed: HTTP {e.response.status_code}"
        try:
            detail = f"Reset failed: {e.response.json()}"
        except Exception:
            pass
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")


@router.get("/rate-limit-status")
async def get_rate_limit_status_endpoint(user: User = Depends(get_current_user)):
    """Fetch current rate limit status from wham API."""
    try:
        access_token = await get_chatgpt_access_token()
    except HTTPException:
        return {"error": "Not authenticated"}

    auth_data = _read_auth_file() or {}
    account_id = auth_data.get("account_id") or _extract_account_id(access_token)

    try:
        return await _fetch_rate_limit_status(access_token, account_id)
    except Exception as e:
        logger.warning("Failed to fetch rate limit status: %s", e)
        return {"error": str(e)}


@router.get("/models")
async def list_chatgpt_models(user: User = Depends(get_current_user)):
    """List available ChatGPT subscription models."""
    from crabagent.core.provider_store import CHATGPT_MODELS

    return [{"id": m, "owned_by": "chatgpt"} for m in CHATGPT_MODELS]
