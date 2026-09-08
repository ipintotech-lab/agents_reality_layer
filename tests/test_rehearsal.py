from reality_layer.actions.models import ActionStatus
from reality_layer.rehearsal import run_local_rehearsal


def test_local_rehearsal_reaches_verified_proof() -> None:
    proof = run_local_rehearsal()

    assert proof.status is ActionStatus.verified
    assert proof.assurance_level == "verified"
    assert proof.verification is not None
    assert proof.verification.result is ActionStatus.verified
    assert proof.projection is not None
    assert proof.projection.semantic_diff["attributes_changed"] == ["status"]
    assert [event.event_type for event in proof.events][-1] == "verified"
