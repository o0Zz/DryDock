import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HARBORGUARD_", env_file=".env", extra="ignore")

    repo_path: Path = Field(default=Path("/repo"))
    data_path: Path = Field(default=Path("/data"))
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Auth / sessions
    secret_key: str | None = None
    session_cookie: str = "harborguard_session"
    # Session lifetime in seconds (default 14 days).
    session_max_age: int = 14 * 24 * 3600
    # Set true when served over HTTPS (e.g. behind a TLS reverse proxy).
    session_https_only: bool = False
    # Bootstrap admin, created on first startup if no users exist.
    admin_username: str = "admin"
    admin_password: str = "admin"

    @property
    def backups_path(self) -> Path:
        return self.data_path / "backups"

    @property
    def db_path(self) -> Path:
        return self.data_path / "harborguard.db"

    def resolve_secret_key(self) -> str:
        """Return the signing key, persisting a generated one so sessions survive restarts."""
        if self.secret_key:
            return self.secret_key
        key_file = self.data_path / "secret_key"
        if key_file.is_file():
            return key_file.read_text(encoding="utf-8").strip()
        self.data_path.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        key_file.write_text(key, encoding="utf-8")
        return key


settings = Settings()
