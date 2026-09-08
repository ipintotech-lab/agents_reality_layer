from typer.testing import CliRunner

from reality_layer.actions.models import ActionStatus
from reality_layer.cli import app
from reality_layer.rehearsal import (
    RehearsalFault,
    rehearsal_scenario_summary,
    rehearsal_summary,
    run_local_rehearsal,
    run_local_rehearsals,
    run_rehearsal,
    run_rehearsals,
)


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


def test_rehearsal_summary_reports_verified_runs() -> None:
    proofs = run_local_rehearsals(runs=2)

    summary = rehearsal_summary(proofs, 1.23456)

    assert summary["total_runs"] == 2
    assert summary["verified_runs"] == 2
    assert summary["failed_runs"] == 0
    assert summary["all_verified"] is True
    assert summary["elapsed_seconds"] == 1.235


def test_rehearsal_captures_per_step_latency() -> None:
    result = run_rehearsal()

    assert result.verified
    assert result.protected
    assert set(result.step_latencies_ms) == {"propose", "approve", "execute", "verify", "proof"}
    assert all(value >= 0.0 for value in result.step_latencies_ms.values())


def test_provider_error_fault_never_claims_a_write() -> None:
    result = run_rehearsal(fault=RehearsalFault.provider_error)

    assert not result.verified
    assert result.protected
    assert result.terminal_status == ActionStatus.approved.value
    assert result.proof is None


def test_verification_divergence_fault_reaches_state_diverged() -> None:
    result = run_rehearsal(fault=RehearsalFault.verification_divergence)

    assert not result.verified
    assert result.protected
    assert result.terminal_status == ActionStatus.state_diverged.value
    assert result.proof is not None
    assert result.proof.status is ActionStatus.state_diverged


def test_scenario_summary_reports_protection_and_latency() -> None:
    results = run_rehearsals(runs=3, fault=RehearsalFault.verification_divergence)

    summary = rehearsal_scenario_summary(results, 2.0)

    assert summary["total_runs"] == 3
    assert summary["all_protected"] is True
    assert summary["faults"] == ["verification_divergence"] * 3
    assert set(summary["slowest_step_ms"]) == {"propose", "approve", "execute", "verify", "proof"}


def test_rehearse_cli_fault_injection_reports_failing_safe(tmp_path) -> None:
    result = CliRunner().invoke(app, ["rehearse", "--runs", "3", "--fault", "provider_error"])

    assert result.exit_code == 0, result.output
    assert '"all_protected": true' in result.output
    assert '"terminal_statuses"' in result.output


def test_rehearse_cli_rejects_unknown_fault() -> None:
    result = CliRunner().invoke(app, ["rehearse", "--fault", "explode"])

    assert result.exit_code == 2, result.output


def test_rehearse_cli_can_write_static_proof_bundle(tmp_path) -> None:
    output = tmp_path / "fallback" / "proof.json"

    result = CliRunner().invoke(
        app,
        ["rehearse", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert '"assurance_level": "verified"' in output.read_text(encoding="utf-8")


def test_rehearse_cli_can_emit_summary(tmp_path) -> None:
    output = tmp_path / "summary.json"

    result = CliRunner().invoke(
        app,
        ["rehearse", "--runs", "2", "--summary", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    body = output.read_text(encoding="utf-8")
    assert '"all_verified": true' in body
    assert '"total_runs": 2' in body
