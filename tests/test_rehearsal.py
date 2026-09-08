from typer.testing import CliRunner

from reality_layer.actions.models import ActionStatus
from reality_layer.cli import app
from reality_layer.rehearsal import run_local_rehearsal, run_local_rehearsals


def test_local_rehearsal_reaches_verified_proof() -> None:
    proof = run_local_rehearsal()

    assert proof.status is ActionStatus.verified
    assert proof.assurance_level == "verified"
    assert proof.verification is not None
    assert proof.verification.result is ActionStatus.verified
    assert proof.projection is not None
    assert proof.projection.semantic_diff["attributes_changed"] == ["status"]
    assert [event.event_type for event in proof.events][-1] == "verified"


def test_rehearsal_runs_are_isolated_and_all_verified() -> None:
    proofs = run_local_rehearsals(runs=5)

    assert len(proofs) == 5
    assert all(proof.status is ActionStatus.verified for proof in proofs)
    assert len({proof.action_id for proof in proofs}) == 5
    assert len({proof.verification_commit_id for proof in proofs}) == 5


def test_rehearse_cli_can_write_static_proof_bundle(tmp_path) -> None:
    output = tmp_path / "fallback" / "proof.json"

    result = CliRunner().invoke(
        app,
        ["rehearse", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert '"assurance_level": "verified"' in output.read_text(encoding="utf-8")
