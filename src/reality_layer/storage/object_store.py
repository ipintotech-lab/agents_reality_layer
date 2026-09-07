from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reality_layer.reality_git import hash_json


@dataclass(frozen=True)
class StoredObject:
    ref: str
    payload_hash: str
    size_bytes: int


class ObjectStore(Protocol):
    def put_raw_payload(self, tenant_id: str, payload: bytes, content_type: str) -> StoredObject:
        raise NotImplementedError

    def get_raw_payload(self, ref: str) -> bytes:
        raise NotImplementedError


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put_raw_payload(self, tenant_id: str, payload: bytes, content_type: str) -> StoredObject:
        payload_hash = hash_json(
            {
                "content_type": content_type,
                "payload_hex": payload.hex(),
                "tenant_id": tenant_id,
            }
        )
        digest = payload_hash.removeprefix("sha256:")
        relative_path = Path(tenant_id) / "raw_payloads" / digest[:2] / digest
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return StoredObject(
            ref=f"local://{relative_path.as_posix()}",
            payload_hash=payload_hash,
            size_bytes=len(payload),
        )

    def get_raw_payload(self, ref: str) -> bytes:
        if not ref.startswith("local://"):
            raise ValueError(f"Unsupported object ref: {ref}")
        relative_path = Path(ref.removeprefix("local://"))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Unsafe object ref: {ref}")
        return (self.root / relative_path).read_bytes()
