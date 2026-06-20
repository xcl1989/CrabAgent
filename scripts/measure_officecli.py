from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from crabagent.core.office.manager import get_office_manager


async def _ensure_manager() -> tuple[object, str | None]:
    mgr = get_office_manager()
    if mgr.available or await mgr.detect():
        return mgr, None
    return mgr, "OfficeCLI not available"


async def _measure(coro, repeat: int) -> list[float]:
    samples: list[float] = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = await coro()
        elapsed = (time.perf_counter() - start) * 1000
        if not getattr(result, "success", False):
            raise RuntimeError(getattr(result, "error", "Unknown OfficeCLI error"))
        samples.append(round(elapsed, 2))
    return samples


def _stats(samples: list[float]) -> dict[str, float | int]:
    return {
        "runs": len(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "avg_ms": round(sum(samples) / len(samples), 2),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Measure OfficeCLI operation latency")
    parser.add_argument("file_path", help="Path to an existing .docx/.xlsx/.pptx file")
    parser.add_argument("--repeat", type=int, default=3, help="How many times to run each check")
    parser.add_argument("--skip-preview", action="store_true", help="Skip HTML preview measurement")
    parser.add_argument("--skip-set", action="store_true", help="Skip set_props measurement")
    parser.add_argument("--skip-batch", action="store_true", help="Skip batch measurement")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    file_path = str(Path(args.file_path).expanduser().resolve())
    mgr, err = await _ensure_manager()
    if err:
        print(err)
        return 1

    ext = Path(file_path).suffix.lower()
    if ext not in {".docx", ".xlsx", ".pptx"}:
        print(f"Unsupported extension: {ext}")
        return 1

    default_set_path = {
        ".docx": "/body/p[1]",
        ".xlsx": "/Sheet1/A1",
        ".pptx": "/slide[1]",
    }[ext]
    default_set_props = {
        ".docx": {"text": "benchmark"},
        ".xlsx": {"text": "benchmark"},
        ".pptx": {"title": "benchmark"},
    }[ext]

    default_batch = {
        ".docx": [
            {"command": "set", "path": "/body/p[1]", "props": {"text": "benchmark"}},
            {"command": "set", "path": "/body/p[1]", "props": {"bold": True}},
        ],
        ".xlsx": [
            {"command": "set", "path": "/Sheet1/A1", "props": {"text": "benchmark"}},
            {"command": "set", "path": "/Sheet1/A1", "props": {"bold": True}},
        ],
        ".pptx": [
            {"command": "set", "path": "/slide[1]", "props": {"title": "benchmark"}},
            {"command": "set", "path": "/slide[1]", "props": {"background": "#F5F1E8"}},
        ],
    }[ext]

    report: dict[str, object] = {
        "file": file_path,
        "format": ext.lstrip("."),
        "officecli_version": getattr(mgr, "version", "unknown"),
        "results": {},
    }

    if not args.skip_preview:
        samples = await _measure(lambda: mgr.view_html(file_path), args.repeat)
        report["results"]["view_html"] = {"samples_ms": samples, **_stats(samples)}

    if not args.skip_set:
        samples = await _measure(lambda: mgr.set_props(file_path, default_set_path, dict(default_set_props)), args.repeat)
        report["results"]["set_props"] = {
            "path": default_set_path,
            "props": default_set_props,
            "samples_ms": samples,
            **_stats(samples),
        }

    if not args.skip_batch:
        samples = await _measure(lambda: mgr.batch(file_path, list(default_batch)), args.repeat)
        report["results"]["batch"] = {
            "commands": default_batch,
            "samples_ms": samples,
            **_stats(samples),
        }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"OfficeCLI benchmark for {file_path}")
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
