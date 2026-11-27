"""ApiKeyGuard: several headers, a Bearer scheme, exempt paths -- an ops API's gate.

As in test_auth_health.py, a 404 proves the guard let the request through and a 401 that it blocked."""

from __future__ import annotations

import hmac

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_kit.service import auth
from platform_kit.service.auth import install_api_key_guard

KEY = "s3cret"


def _client(**kw) -> TestClient:
    app = FastAPI()
    install_api_key_guard(app, lambda: KEY, **kw)
    return TestClient(app)


OPS = {"headers": ("x-ops-token",), "bearer": True, "exempt_paths": ("/mcp", "/ops/open/")}


@pytest.mark.parametrize(
    ("hdrs", "want"),
    [
        ({"Authorization": f"Bearer {KEY}"}, 404),
        ({"Authorization": f"bearer {KEY}"}, 404),  # RFC 7235: the scheme is case-insensitive
        ({"Authorization": f"Bearer  {KEY} "}, 404),
        ({"X-Ops-Token": KEY}, 404),
        ({"Authorization": "Bearer nope"}, 401),
        ({"Authorization": f"Basic {KEY}"}, 401),
        ({"Authorization": KEY}, 401),  # no scheme is not a Bearer credential
        ({"X-Ops-Token": "nope"}, 401),
        ({"X-API-Key": KEY}, 401),  # `headers=` REPLACES the default header, it does not add to it
        ({}, 401),
        ({"Authorization": "Bearer nope", "X-Ops-Token": KEY}, 404),  # any one valid credential
    ],
)
def test_bearer_and_named_headers(hdrs, want) -> None:
    assert _client(**OPS).post("/ops/kill", headers=hdrs).status_code == want


def test_bearer_off_ignores_authorization() -> None:
    assert _client(headers=("x-ops-token",)).post("/x", headers={"Authorization": f"Bearer {KEY}"}).status_code == 401


@pytest.mark.parametrize(
    ("path", "want"),
    [
        ("/mcp", 404),
        ("/mcp/", 404),
        ("/mcp/messages", 404),
        ("/mcpx", 401),
        ("/ops/open", 404),
        ("/ops/open/a", 404),
        ("/ops/opener", 401),
        ("/ops/kill", 401),
    ],
)
def test_exempt_paths_open_at_a_segment_boundary_only(path, want) -> None:
    assert _client(**OPS).post(path).status_code == want


def test_root_exemption_opens_everything() -> None:
    assert _client(exempt_paths=("/",)).post("/anything").status_code == 404


def test_the_default_still_reads_x_api_key_only() -> None:
    c = _client()
    assert c.post("/x", headers={"X-API-Key": KEY}).status_code == 404
    assert c.post("/x", headers={"Authorization": f"Bearer {KEY}"}).status_code == 401


def test_every_candidate_is_compared_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def recorder(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", recorder)  # type: ignore[attr-defined]
    # the FIRST candidate matches; the bearer slot is still compared, so timing does not say which
    assert _client(**OPS).post("/ops/kill", headers={"X-Ops-Token": KEY}).status_code == 404
    assert len(calls) == 2 and all(w == KEY.encode() for _, w in calls)
