"""诊断：智谱 Coding Plan 端点流式返回是否包含明文 reasoning_content。

分两层验证：
1. 原始 openai SDK（绕过 litellm）——看服务端原始 delta 字段
2. litellm（CrabAgent 实际路径）——看 litellm 解析后 delta 字段
"""
import asyncio
import json
import sqlite3
import sys

sys.path.insert(0, "/Users/xiecongling/Documents/Coding/CrabAgent/src")

from crabagent.core.provider_store import decrypt_api_key

db = sqlite3.connect("/Users/xiecongling/.crabagent/crabagent.db")
row = db.execute(
    "SELECT api_key, base_url FROM provider_configs WHERE provider_type='zhipu' AND name='ZAI'"
).fetchone()
api_key, base_url = decrypt_api_key(row[0]), row[1]
print(f"base_url = {base_url}")

MODEL = "glm-5.3"
messages = [{"role": "user", "content": "用一句话说明什么是快速排序"}]


async def test_raw():
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    print("\n===== 1) 原始 openai SDK 流 =====")
    reasoning_chars = 0
    content_chars = 0
    seen_delta_keys = set()
    usage_info = None
    stream = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.usage:
            usage_info = chunk.usage
        if not chunk.choices:
            continue
        d = chunk.choices[0].delta
        # 记录原始 JSON 里出现过的字段
        raw = d.model_dump(exclude_none=True, exclude_unset=True)
        seen_delta_keys.update(raw.keys())
        reasoning_chars += len(raw.get("reasoning_content") or "")
        content_chars += len(raw.get("content") or "")
    print(f"delta 中出现过的字段: {sorted(seen_delta_keys)}")
    print(f"reasoning_content 累计字符: {reasoning_chars}")
    print(f"content 累计字符: {content_chars}")
    if usage_info:
        det = usage_info.completion_tokens_details
        print(f"usage: completion={usage_info.completion_tokens}, reasoning_tokens={getattr(det, 'reasoning_tokens', None) if det else None}")


async def test_litellm():
    import litellm

    print("\n===== 2) litellm 流（CrabAgent 实际路径）=====")
    reasoning_chars = 0
    content_chars = 0
    seen_attrs = set()
    usage_info = None
    stream = await litellm.acompletion(
        model=f"openai/{MODEL}",
        messages=messages,
        api_key=api_key,
        api_base=base_url,
        stream=True,
        stream_options={"include_usage": True},
        reasoning_effort="medium",
        allowed_openai_params=["reasoning_effort"],
    )
    async for chunk in stream:
        if getattr(chunk, "usage", None):
            usage_info = chunk.usage
        if not chunk.choices:
            continue
        d = chunk.choices[0].delta
        seen_attrs.update(a for a in ("content", "reasoning_content", "reasoning") if getattr(d, a, None))
        reasoning_chars += len(getattr(d, "reasoning_content", None) or "") + len(getattr(d, "reasoning", None) or "")
        content_chars += len(getattr(d, "content", None) or "")
    print(f"delta 上非空的属性: {sorted(seen_attrs)}")
    print(f"reasoning 累计字符: {reasoning_chars}")
    print(f"content 累计字符: {content_chars}")
    if usage_info:
        det = usage_info.completion_tokens_details
        print(f"usage: completion={usage_info.completion_tokens}, reasoning_tokens={getattr(det, 'reasoning_tokens', None) if det else None}")


async def main():
    await test_raw()
    await test_litellm()


asyncio.run(main())
