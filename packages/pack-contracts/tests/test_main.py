"""`python -m pack_contracts`: schema, surface, validate (and its exit codes)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pack_contracts.__main__ import main
from pack_contracts.schema import manifest_json_schema
from pack_contracts.surface import live_surface

if TYPE_CHECKING:
    from pathlib import Path


def test_schema_prints_the_projection(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out) == manifest_json_schema()


def test_surface_prints_the_live_entry(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["surface"]) == 0
    assert json.loads(capsys.readouterr().out) == live_surface()


def test_validate_passes_good_files_and_names_each_refusal(
    tmp_path: Path, example_manifest: str, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "pack.toml"
    good.write_text(example_manifest, encoding="utf-8")
    assert main(["validate", str(good)]) == 0
    assert "ok" in capsys.readouterr().out
    bad = tmp_path / "bad.toml"
    bad.write_text(example_manifest.replace('tier = "loads"', 'tier = "gold"'), encoding="utf-8")
    missing = tmp_path / "missing.toml"
    assert main(["validate", str(good), str(bad), str(missing)]) == 1
    err = capsys.readouterr().err
    assert f"REFUSED {bad}" in err and "validate" in err and f"REFUSED {missing}" in err


def test_usage_errors_exit_2() -> None:
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2
