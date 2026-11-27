"""`platform_kit.service.pg_identity` -- the application_name authority.

Pure: env is monkeypatched, nothing connects. These assert the CONTRACT the incident needs —
that a process is never anonymous, that compose's value wins, and that the asyncpg path gets
the name explicitly (because asyncpg ignores PGAPPNAME, which is the whole reason this module
is not a one-line env var).

Regression target: an incident where every application connection presented an EMPTY
application_name, so pg_stat_activity could name the wedged PID but not the service behind it.
"""

from __future__ import annotations

import pytest

from platform_kit.service.pg_identity import PgIdentity

pg_identity = PgIdentity("billing")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with no PGAPPNAME — otherwise the runner's own env leaks in."""
    monkeypatch.delenv("PGAPPNAME", raising=False)


# ── naming ──────────────────────────────────────────────────────────────────


def test_compose_value_is_used_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGAPPNAME", "billing-price-streamer")
    assert pg_identity.app_name() == "billing-price-streamer"


def test_prefix_is_not_doubled(monkeypatch: pytest.MonkeyPatch) -> None:
    """compose sets the fully-qualified name; we must not produce billing-billing-*."""
    monkeypatch.setenv("PGAPPNAME", "billing-jobs")
    assert pg_identity.app_name() == "billing-jobs"
    assert not pg_identity.app_name().startswith("billing-billing")


def test_unqualified_value_gets_the_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGAPPNAME", "jobs")
    assert pg_identity.app_name() == "billing-jobs"


def test_unset_env_still_names_something(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank application_name is the bug. An ad-hoc script must still identify itself."""
    monkeypatch.setattr("sys.argv", ["/app/scripts/grade_hist.py"])
    name = pg_identity.app_name()
    assert name == "billing-py:grade_hist"
    assert name.strip() != ""


def test_suffix_narrows_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chain writer tags per symbol so a stuck holder names the symbol going dark."""
    monkeypatch.setenv("PGAPPNAME", "billing-jobs")
    assert pg_identity.app_name("capture:alpha") == "billing-jobs:capture:alpha"


def test_name_fits_postgres_namedatalen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres silently truncates at 63 bytes; truncating here keeps logs == pg_stat_activity."""
    monkeypatch.setenv("PGAPPNAME", "billing-" + "x" * 200)
    assert len(pg_identity.app_name("also-long")) == 63


# ── the asyncpg half (the reason this module exists) ────────────────────────


def test_server_settings_carries_application_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGAPPNAME", "billing-live-projector")
    assert pg_identity.server_settings() == {"application_name": "billing-live-projector"}


def test_server_settings_merges_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGAPPNAME", "billing-api")
    got = pg_identity.server_settings("listen", timezone="UTC")
    assert got["application_name"] == "billing-api:listen"
    assert got["timezone"] == "UTC"


def test_connect_args_is_the_sqlalchemy_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGAPPNAME", "billing-api")
    assert pg_identity.connect_args() == {
        "server_settings": {"application_name": "billing-api"},
    }


# ── install() ───────────────────────────────────────────────────────────────


def test_install_exports_pgappname_for_libpq(monkeypatch: pytest.MonkeyPatch) -> None:
    """psycopg reads PGAPPNAME natively — that is what covers the ~60 script callsites."""
    monkeypatch.setattr("sys.argv", ["/app/scripts/backfill_bars.py"])
    import os

    returned = pg_identity.install()
    assert os.environ["PGAPPNAME"] == "billing-py:backfill_bars"
    assert returned == "billing-py:backfill_bars"


def test_install_never_clobbers_an_existing_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """compose (or an operator debugging) has said something more specific than we can infer."""
    monkeypatch.setenv("PGAPPNAME", "billing-jobs")
    assert pg_identity.install() == "billing-jobs"

    import os

    assert os.environ["PGAPPNAME"] == "billing-jobs"


def test_install_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["/app/scripts/migrate.py"])
    first = pg_identity.install()
    assert pg_identity.install() == first


def test_the_prefix_and_the_variable_are_the_consumers(monkeypatch: pytest.MonkeyPatch) -> None:
    other = PgIdentity("content-data", env_var="CONTENT_APPNAME")
    monkeypatch.setenv("PGAPPNAME", "billing-jobs")  # another family's variable: not read
    monkeypatch.setenv("CONTENT_APPNAME", "ingest")
    assert other.app_name() == "content-data-ingest"
    with pytest.raises(ValueError, match="prefix"):
        PgIdentity("  ")
