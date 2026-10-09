from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SKILLBOOK_", env_file=".env", extra="ignore")
    api_key: SecretStr = SecretStr("")
    provider: Literal["ollama", "mock"] = "ollama"
    model: str = "qwen2.5:0.5b"
    ollama_url: str = "http://127.0.0.1:11434"
    audit_db: Path = Path("state/audit.sqlite")
    release_state: str = ""
    trusted_key: str = ""
    timeout_seconds: float = Field(default=45, ge=1, le=120)

    @field_validator("ollama_url")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname not in {"localhost", "127.0.0.1", "::1", "ollama"}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("Only loopback or the Compose ollama service is accepted")
        return value.rstrip("/")

    @model_validator(mode="after")
    def paired_release_settings(self):
        if bool(self.release_state) != bool(self.trusted_key):
            raise ValueError("Release state and trusted public key must be configured together")
        return self
