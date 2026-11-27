"""The service chassis's corners: an unlabelled process's entrypoint name, and a timeline unit
told no status code."""

from __future__ import annotations

import sys

import pytest

from platform_kit.service.pg_identity import entrypoint
from platform_kit.service.timeline import RemoteTimeline


@pytest.mark.parametrize(("argv", "want"), [([], "unknown"), ([""], "unknown"), (["/x/python3"], "unknown"),
                                            (["/srv/app/worker.py"], "worker")])  # fmt: skip
def test_entrypoint_names_the_script_or_says_unknown(monkeypatch: pytest.MonkeyPatch, argv: list[str],
                                                     want: str) -> None:  # fmt: skip
    monkeypatch.setattr(sys, "argv", argv)
    assert entrypoint() == want


def test_no_status_code_marks_nothing() -> None:
    class Unit:
        def __init__(self) -> None:
            self.marked: list[int] = []

        def mark_http(self, code: int) -> None:
            self.marked.append(code)

    u = Unit()
    RemoteTimeline.on_status(u, None)
    RemoteTimeline.on_status(u, 204)
    assert u.marked == [204]
