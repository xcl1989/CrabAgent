from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {
        "env_prefix": "CRAB_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    workspace: Path = Path.cwd()

    max_iterations: int = 50
    max_tokens: int = 4096

    skills_dir: Path | None = None
    skills_paths: list[str] = []
    disable_opencode_skills: bool = False

    db_url: str = "sqlite+aiosqlite:///./crabagent.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "crabagent-secret-change-me"
    jwt_expire_minutes: int = 1440

    serve_host: str = "0.0.0.0"
    serve_port: int = 5210

    web_proxy: str = ""

    encryption_key: str = ""

    auto_approve_tools: bool = False

    bash_blocked_patterns: list[str] = [
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=",
        "dd of=/dev/",
        "shutdown",
        "reboot",
        "init 0",
        "init 6",
        ":(){ :|:& };:",
        "fork bomb",
    ]
    bash_block_privilege_escalation: bool = True
    bash_max_output_length: int = 50000
    bash_block_background: bool = False

    model_token_limits: dict[str, int] = {}
    context_compression_threshold: float = 0.8
    context_keep_recent: int = 6

    # v0.9 — Long-term memory middleware
    memory_auto_extract: bool = True
    memory_auto_recall: bool = True
    memory_max_inject: int = 5

    # v0.9 — Browser DOM labels + vision screenshot embedding
    browser_strategy: str = "dom"  # "dom" | "vision" | "hybrid" (v0.9 only implements dom+vision fallback)
    browser_screenshot_to_llm: bool = True
    browser_screenshot_history: int = 3
    browser_screenshot_max_bytes: int = 200_000

    molt_keep_count: int = 20
    molt_keep_days: int = 7

    @staticmethod
    def _user_config_dir() -> Path:
        d = Path.home() / ".crabagent"
        d.mkdir(exist_ok=True)
        return d

    def get_encryption_key(self) -> str:
        if self.encryption_key:
            return self.encryption_key
        key_path = self._user_config_dir() / "encryption_key"
        if key_path.exists():
            return key_path.read_text().strip()
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        key_path.write_text(key)
        return key

    def save_last_model(self, model: str) -> None:
        (self._user_config_dir() / "last_model").write_text(model)

    def load_last_model(self) -> str | None:
        p = self._user_config_dir() / "last_model"
        if p.exists():
            model = p.read_text().strip()
            return model or None
        return None

    def skill_discovery_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        if self.skills_dir:
            dirs.append(self.skills_dir)
        for p in self.skills_paths:
            dirs.append(Path(p))
        candidate = self.workspace / ".crabagent" / "skills"
        if candidate.exists():
            dirs.append(candidate)
        if not self.disable_opencode_skills:
            candidate = self.workspace / ".opencode" / "skills"
            if candidate.exists():
                dirs.append(candidate)
        home = Path.home()
        global_dir = home / ".crabagent" / "skills"
        if global_dir.exists():
            dirs.append(global_dir)
        if not self.disable_opencode_skills:
            global_opencode = home / ".opencode" / "skills"
            if global_opencode.exists():
                dirs.append(global_opencode)
        return dirs


settings = Settings()
