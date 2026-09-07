from decimal import Decimal

import pytest

from reality_layer.reality_git import canonical_json, hash_json


def test_canonical_json_sorts_keys_and_removes_whitespace() -> None:
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_hash_json_is_stable_for_equivalent_objects() -> None:
    left = {"actor": {"id": "agent:ops", "type": "agent"}, "parents": ["cmt_1"]}
    right = {"parents": ["cmt_1"], "actor": {"type": "agent", "id": "agent:ops"}}

    assert hash_json(left) == hash_json(right)


def test_hash_json_changes_when_commit_metadata_changes() -> None:
    base = {
        "commit_id": "cmt_1",
        "parent_ids": [],
        "author": {"type": "agent", "id": "agent:ops"},
        "cause": "observation",
        "diff": {"entities_changed": ["order:1"]},
    }
    changed_author = base | {"author": {"type": "user", "id": "user:ops"}}

    assert hash_json(base) != hash_json(changed_author)


def test_canonical_json_normalizes_integral_decimals() -> None:
    assert canonical_json({"amount": Decimal("12.0")}) == '{"amount":12}'


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json({"score": float("nan")})
