import pytest

from reality_layer.actions.models import ActionEventRecord
from reality_layer.reality_git import validate_event_chain


def test_event_chain_validation_detects_payload_tampering() -> None:
    event = ActionEventRecord(
        event_id="evt_1",
        tenant_id="tenant",
        action_id="act_1",
        event_type="policy_evaluated",
        actor_role="operations",
        payload={"status": "approval_required"},
        event_hash="",
    )
    from reality_layer.reality_git import hash_json

    event = event.model_copy(
        update={
            "event_hash": hash_json(
                {
                    "event_id": event.event_id,
                    "tenant_id": event.tenant_id,
                    "action_id": event.action_id,
                    "event_type": event.event_type,
                    "actor_role": event.actor_role,
                    "payload": event.payload,
                    "previous_event_hash": None,
                }
            )
        }
    )
    validate_event_chain([event])

    tampered = event.model_copy(update={"payload": {"status": "verified"}})
    with pytest.raises(ValueError, match="Event hash mismatch"):
        validate_event_chain([tampered])
