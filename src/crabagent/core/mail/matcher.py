"""Email ↔ Project matching.

Given an email (subject + body snippet) and a list of known projects with
their keywords/context, determine which project the email is most likely
related to and return relevant context (pending tasks, recent activity).
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def match_email_to_project(
    subject: str,
    body_snippet: str,
    sender: str,
    projects: list[dict],
    model: str = "gpt-4o",
    llm_params: dict | None = None,
) -> dict | None:
    """Match an email to the most relevant project using LLM classification.

    Args:
        subject: Email subject line.
        body_snippet: First ~300 chars of email body.
        sender: Sender email address.
        projects: List of dicts with keys: name, task_count, keywords.
        model: LLM model to use.
        llm_params: litellm params (api_key, api_base, etc.).

    Returns:
        {"project": "ProjectName", "confidence": "high|medium|low"} or None.
    """
    if not projects:
        return None

    # For 1-2 projects, skip LLM and use simple keyword matching
    if len(projects) <= 2:
        return _keyword_match(subject, body_snippet, sender, projects)

    import litellm

    project_list = "\n".join(
        f"  - {p['name']} (keywords: {', '.join(p.get('keywords', []))})"
        for p in projects
    )

    prompt = (
        "You are an email-to-project classifier.\n\n"
        f"Known projects:\n{project_list}\n\n"
        f"Email:\n"
        f"  Subject: {subject[:200]}\n"
        f"  From: {sender}\n"
        f"  Body preview: {body_snippet[:300]}\n\n"
        "Determine which project this email is most likely about. "
        'If it doesn\'t clearly relate to any project, respond with: {"project": null}\n\n'
        'Respond with JSON only:\n'
        '{"project": "ProjectName", "confidence": "high|medium|low"}'
    )

    try:
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.0,
            **(llm_params or {}),
        )
        raw = (response.choices[0].message.content or "").strip()
        # Clean markdown code block if present
        if raw.startswith("```"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]

        data = json.loads(raw)
        if data.get("project") is None:
            return None

        # Validate project name exists
        names = [p["name"] for p in projects]
        matched = data["project"]
        # Fuzzy match: case-insensitive, partial
        for name in names:
            if matched.lower() == name.lower() or matched.lower() in name.lower():
                return {"project": name, "confidence": data.get("confidence", "medium")}

        return None

    except Exception as e:
        logger.error(f"Email project matching failed: {e}")
        return None


def _keyword_match(
    subject: str,
    body_snippet: str,
    sender: str,
    projects: list[dict],
) -> dict | None:
    """Simple keyword-based matching for small project lists."""
    text = f"{subject} {body_snippet} {sender}".lower()

    best_match = None
    best_score = 0

    for p in projects:
        score = 0
        keywords = p.get("keywords", [])
        name_lower = p["name"].lower()

        # Project name in text
        if name_lower in text:
            score += 3

        # Keyword matching
        for kw in keywords:
            if kw.lower() in text:
                score += 1

        if score > best_score:
            best_score = score
            best_match = p

    if best_match and best_score > 0:
        return {"project": best_match["name"], "confidence": "high" if best_score >= 3 else "medium"}

    return None


def build_project_context(
    project_name: str,
    project_tasks: list[dict],
) -> str:
    """Build a context block for a matched project."""
    if not project_tasks:
        return f"📁 Project: **{project_name}** (no active tasks)"

    lines = [f"📁 Project: **{project_name}**", ""]

    pending = [t for t in project_tasks if t["status"] in ("pending", "in_progress")]
    done_recent = [t for t in project_tasks if t["status"] == "done"][:3]

    if pending:
        lines.append(f"  **Active tasks ({len(pending)}):**")
        for t in pending[:5]:
            pri = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t.get("priority", "medium"), "🟡")
            line = f"    {pri} {t['title']}"
            if t.get("deadline"):
                line += f" 📅 {t['deadline'][:10]}"
            lines.append(line)

    if done_recent:
        lines.append(f"  **Recently done:**")
        for t in done_recent:
            lines.append(f"    ✅ {t['title']}")

    return "\n".join(lines)
