"""`ContractVersion` and `satisfies`: the comparison the reader's `contract` stage rests on."""

from __future__ import annotations

import pytest

from pack_contracts.contract import CONTRACT_MAJOR, CONTRACT_MINOR, CONTRACT_VERSION, ContractVersion, satisfies


def test_parse_and_render() -> None:
    assert ContractVersion.parse("1.2") == ContractVersion(1, 2)
    assert str(ContractVersion(3, 0)) == "3.0"
    assert ContractVersion.parse("10.0") > ContractVersion.parse("9.9")
    assert tuple(CONTRACT_VERSION) == (CONTRACT_MAJOR, CONTRACT_MINOR)


@pytest.mark.parametrize("bad", ["1", "1.2.3", "01.2", "1.02", "a.b", "", " 1.2", "-1.0"])
def test_parse_refuses_anything_but_two_integers(bad: str) -> None:
    with pytest.raises(ValueError, match=r"MAJOR\.MINOR"):
        ContractVersion.parse(bad)


@pytest.mark.parametrize(
    ("host", "wanted", "ok"),
    [
        ("1.0", "1.0", True),
        ("1.3", "1.0", True),  # an older pack on a newer host: the rule's whole point
        ("1.0", "1.3", False),  # the pack needs what this host does not have yet
        ("2.0", "1.0", False),  # another major, either way
        ("1.9", "2.0", False),
    ],
)
def test_satisfies(host: str, wanted: str, ok: bool) -> None:
    assert satisfies(ContractVersion.parse(host), ContractVersion.parse(wanted)) is ok
