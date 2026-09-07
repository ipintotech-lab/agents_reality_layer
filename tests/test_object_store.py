import pytest

from reality_layer.storage import LocalObjectStore


def test_local_object_store_round_trips_tenant_scoped_payload(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)

    stored = store.put_raw_payload("tenant_a", b'{"id":1}', "application/json")

    assert stored.ref.startswith("local://tenant_a/raw_payloads/")
    assert stored.payload_hash.startswith("sha256:")
    assert stored.size_bytes == 8
    assert store.get_raw_payload(stored.ref) == b'{"id":1}'


def test_local_object_store_rejects_unsafe_refs(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)

    with pytest.raises(ValueError):
        store.get_raw_payload("local://../secret")
