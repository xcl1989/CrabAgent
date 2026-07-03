from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".crabagent" / "crabagent.db"

GLOBAL_ALWAYS_KEYS = {
    "user_preference:complete_loop1_before_feedback",
    "lesson:resolve_memory_conflict_with_agents",
    "pyinstaller_litellm_pitfalls",
    "build:pyinstaller:litellm_hidden_imports",
    "litellm:error_handling",
    "desktop_dev_workflow",
    "electron_fast_startup_pattern",
    "chatgpt_codex_models_202606",
}

WORKSPACE_ALWAYS_MAP = {
    "/Users/xiecongling/Documents/Coding/CrabAgent": {
        "api:ilink_protocol_details",
        "api:wechat:context_token_expiry",
        "feature:wechat_ilink_implemented",
        "feature:quick_edit",
        "feature:wechat_ilink",
        "api:prototype_preview_fix",
        "feature:lesson_dedup_upgrade",
        "data-analytics:log_directory",
        "indicator:overall_investment_fields",
        "feature:officecli:table_data",
        "decision:wechat_ilink_scope",
        "feature:quick_edit_style",
        "officecli:check_available_auto_detect",
        "officecli:path_syntax",
        "feature:quick_edit_day2_done",
        "feature:quick_edit_day1_done",
        "ui:pages:redesign",
        "design:tool_result_render",
        "feature:chatgpt_subscription_oauth",
    },
    "/Users/xiecongling/Documents/Coding/godotbefore": {
        "art_direction:bg_match_enemy_style_not_soulslike",
        "feature:current_direction_card_dungeon",
        "feature:rewrite_back_to_card_dungeon",
        "art_generation:green_bg_single_subject_no_shadow",
        "art_style:burst_enemy_hybrid_a_c",
    },
    "/Users/xiecongling/Documents/Coding/godotgame": {
        "user_preference:game_direction_push_against_darkness",
        "version:v0.5_complete",
        "version:v0.4_complete",
        "roadmap:phase_plan",
        "user_preference:game_direction_not_escape_survival",
        "cleanup:v0.6_hud_prototype_removal",
        "perf:v0.6_runtime_optimizations",
        "architecture:flow_modules_extracted",
        "v0.3_narrative_rewrite_complete",
        "user_preference:darkness_progression_over_ui",
        "game_concept:before_the_light_dies",
    },
    "/Users/xiecongling/Documents/文档/公司文档/月度工作记录/2407/axurecode/自定义组件/ai盒子接口": {
        "api:uniview_cloud_migration",
        "api:uniview_cloud_alarm_types",
    },
}


def ensure_columns(cur: sqlite3.Cursor) -> None:
    cols = {row[1] for row in cur.execute("PRAGMA table_info(agent_memory)")}
    if "scope" not in cols:
        cur.execute("ALTER TABLE agent_memory ADD COLUMN scope VARCHAR(20) DEFAULT ''")
    if "workspace_path" not in cols:
        cur.execute("ALTER TABLE agent_memory ADD COLUMN workspace_path TEXT DEFAULT ''")
    if "recall_policy" not in cols:
        cur.execute("ALTER TABLE agent_memory ADD COLUMN recall_policy VARCHAR(20) DEFAULT ''")


def fill_workspace_paths(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        UPDATE agent_memory
        SET workspace_path = (
            SELECT c.workspace
            FROM conversations c
            WHERE c.session_id = agent_memory.source_session
            LIMIT 1
        )
        WHERE COALESCE(workspace_path, '') = ''
          AND COALESCE(source_session, '') != ''
        """
    )


def apply_curated_overrides(cur: sqlite3.Cursor) -> None:
    for key in GLOBAL_ALWAYS_KEYS:
        cur.execute(
            "UPDATE agent_memory SET scope='global', recall_policy='always', workspace_path='' WHERE key=?",
            (key,),
        )
    for workspace, keys in WORKSPACE_ALWAYS_MAP.items():
        for key in keys:
            cur.execute(
                "UPDATE agent_memory SET scope='workspace', recall_policy='always', workspace_path=? WHERE key=?",
                (workspace, key),
            )


def classify_remaining(cur: sqlite3.Cursor) -> None:
    cur.execute(
        "UPDATE agent_memory SET scope='agent', recall_policy='query_only' WHERE memory_type='agent_lesson' AND COALESCE(scope, '')=''"
    )
    cur.execute(
        """
        UPDATE agent_memory
        SET scope='global', recall_policy='query_only', workspace_path=''
        WHERE memory_type='user_preference' AND COALESCE(scope, '')=''
        """
    )
    cur.execute(
        """
        UPDATE agent_memory
        SET scope='global', recall_policy='query_only'
        WHERE memory_type='lesson' AND COALESCE(scope, '')=''
        """
    )
    cur.execute(
        """
        UPDATE agent_memory
        SET scope = CASE WHEN COALESCE(workspace_path, '') != '' THEN 'workspace' ELSE 'global' END,
            recall_policy = CASE WHEN COALESCE(workspace_path, '') != '' THEN 'query_only' ELSE 'always' END
        WHERE memory_type='team' AND COALESCE(scope, '')=''
        """
    )
    cur.execute(
        """
        UPDATE agent_memory
        SET scope='workspace', recall_policy='query_only'
        WHERE memory_type='lesson' AND COALESCE(scope, '')='' AND COALESCE(workspace_path, '') != ''
        """
    )


def print_summary(cur: sqlite3.Cursor) -> None:
    print("Migration summary:")
    for row in cur.execute(
        """
        SELECT COALESCE(scope, '') AS scope, COALESCE(recall_policy, '') AS recall_policy, COUNT(*)
        FROM agent_memory
        GROUP BY COALESCE(scope, ''), COALESCE(recall_policy, '')
        ORDER BY COUNT(*) DESC
        """
    ):
        print(f"- scope={row[0]!r}, recall_policy={row[1]!r}, count={row[2]}")


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        ensure_columns(cur)
        fill_workspace_paths(cur)
        apply_curated_overrides(cur)
        classify_remaining(cur)
        conn.commit()
        print_summary(cur)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
