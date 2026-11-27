"""The config plane's corners: the CLI's stdout render, knob() argument checks, init-kwarg
provenance on an undeclared field, redaction inside containers, the lint's domain-name rules and a
broken degraded hook."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from platform_kit.config import MASK, Domain, KnobClass, Source, effective, knob, lint, load_all
from platform_kit.config.__main__ import main as cli
from platform_kit.config.render import redact_userinfo

from .domains import DOMAINS, _Undeclared


def test_the_cli_renders_to_stdout_without_a_target_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["catalog", "tests.config.domains:DOMAINS"]) == 0
    assert "T_RISK_MAX_CARDS" in capsys.readouterr().out


def test_knob_refuses_a_class_that_is_not_a_knob_class() -> None:
    with pytest.raises(TypeError, match="cls must be a KnobClass"):
        knob(1, cls="tunable", env="T_X", doc="d")  # type: ignore[arg-type]


def test_an_init_kwarg_on_an_undeclared_field_is_sourced_init() -> None:
    assert _Undeclared(loose=4).source_of("loose") is Source.INIT


def test_userinfo_is_redacted_inside_lists_and_dicts() -> None:
    raw = {"a": ["postgresql://u:pw@h/db", 3], "b": {"c": "https://x:y@v/z"}}
    assert redact_userinfo(raw) == {"a": [f"postgresql://{MASK}@h/db", 3], "b": {"c": f"https://{MASK}@v/z"}}


def test_a_secret_value_under_a_non_secret_class_is_still_masked() -> None:
    class Odd(Domain):
        domain: ClassVar[str] = "t_odd"
        token_value: SecretStr = knob(SecretStr("s3"), cls=KnobClass.TUNABLE, env="T_ODD_VALUE", doc="d.")

    row = next(e for e in effective(Odd()) if e.name == "token_value")
    assert row.value == MASK and row.default == MASK
    assert any("typed as a secret but classed tunable" in f for f in lint([Odd]))


def test_the_lint_names_a_bad_domain_name_and_a_domain_declared_twice() -> None:
    class Nameless(Domain):
        x: int = knob(1, cls=KnobClass.TUNABLE, env="T_NAMELESS_X", doc="d.")

    class Shouty(Domain):
        domain: ClassVar[str] = "Not_Snake"

    class Again(Domain):
        domain: ClassVar[str] = "t_risk"

    found = lint([*DOMAINS, Nameless, Shouty, Again])
    assert any(f.startswith("Nameless: domain must be a snake_case ClassVar") for f in found)
    assert any("Shouty: domain must be a snake_case ClassVar, got 'Not_Snake'" in f for f in found)
    assert any("domain 't_risk' declared by both Risk and Again" in f for f in found)


class _Boom:
    def current(self, domain: str) -> dict[str, Any]:
        raise ConnectionError("override store down")


def test_an_unreadable_store_without_a_hook_and_with_a_broken_hook(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="platform_kit.config"):
        d: Any = load_all(DOMAINS, overrides=_Boom())["t_risk"]  # no on_degraded hook at all
    assert d.source_of("halted") is Source.FAILSAFE

    def hook(_reason: str) -> None:
        raise RuntimeError("hook broken")

    with caplog.at_level(logging.WARNING, logger="platform_kit.config"):
        d = load_all(DOMAINS, overrides=_Boom(), on_degraded=hook)["t_risk"]
    assert d.halted is True
    assert "config_on_degraded_hook_failed" in caplog.text


def test_a_secret_knob_typed_as_a_plain_string_is_a_finding() -> None:
    class Plain(Domain):
        domain: ClassVar[str] = "t_plain"
        api_secret: str = knob("x", cls=KnobClass.SECRET, env="T_PLAIN_API_SECRET", doc="d.")

    assert any("a SECRET knob must be typed SecretStr" in f for f in lint([Plain]))
