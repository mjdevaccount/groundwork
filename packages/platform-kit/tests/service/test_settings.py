"""ServiceSettings: subclasses inherit the shared config -- unknown keys ignored, fields read by alias."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from platform_kit.service.settings import ServiceSettings

if TYPE_CHECKING:
    import pathlib

    import pytest


class _S(ServiceSettings):
    port: int = Field(default=1, alias="SVC_PORT")


def test_inherits_config(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SVC_PORT", "8091")
    monkeypatch.setenv("SOME_OTHER_SERVICE_KEY", "x")  # the shared .env: other services' keys
    s = _S()
    assert s.port == 8091
    assert _S.model_config["extra"] == "ignore" and _S.model_config["env_file"] == ".env"


def test_reads_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SVC_PORT", raising=False)
    (tmp_path / ".env").write_text("SVC_PORT=7\nUNRELATED=1\n", encoding="utf-8")
    assert _S().port == 7
