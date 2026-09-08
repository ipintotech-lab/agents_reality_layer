from reality_layer.actions.models import ActionEventRecord
from reality_layer.demo import demo_transcript, run_agent_demo
from reality_layer.reality_git import validate_event_chain


def test_scripted_agent_demo_completes_through_public_contracts() -> None:
    run = run_agent_demo(tenant_id="demo", order_id="demo-2002")

    # Policy-control path: an observer write is denied with no approval path.
    assert run.denied["status"] == "denied"
    assert run.denied["matched_rule"] == "deny.observer.write"

    # Proposal-only path: hold_order is evaluated but never executed.
    assert run.proposal_only["status"] == "approval_required"
    assert run.proposal_only["matched_rule"] == "approval.mvp.proposal_only"

    # Happy path ends verified with a hash-linked proof bundle.
    assert run.verified
    assert run.proof["status"] == "verified"
    assert run.proof["verification"]["observed_status"] == "cancelled"
    validate_event_chain([ActionEventRecord(**e) for e in run.proof["events"]])

    names = [step.name for step in run.steps]
    assert names == [
        "observe",
        "agent_query",
        "policy_denied",
        "proposal_only",
        "propose",
        "approve",
        "execute",
        "verify",
        "proof",
        "diff",
    ]
    # The agent side only ever touches the MCP channel.
    assert {s.channel for s in run.steps if s.actor == "agent"} == {"mcp"}


def test_demo_cli_command_runs_and_can_emit_the_proof() -> None:
    from typer.testing import CliRunner

    from reality_layer.cli import app

    result = CliRunner().invoke(app, ["demo", "--order", "cli-4004", "--proof"])

    assert result.exit_code == 0
    assert '"assurance_level": "verified"' in result.stdout


def test_demo_transcript_is_readable() -> None:
    run = run_agent_demo(order_id="demo-3003")
    text = demo_transcript(run)

    assert "agent demo" in text
    assert "[agent/mcp] propose" in text
    assert "assurance_level=verified" in text
