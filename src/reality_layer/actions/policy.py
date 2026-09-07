from reality_layer.actions.models import ActionDecision, ActionProposal, ActionStatus

#: Every action type in the MVP is an effective write.
OBSERVE_ONLY_MODE = "observe_only"


def evaluate_policy(
    *,
    action_id: str,
    proposal: ActionProposal,
    role: str,
    workspace_mode: str = "demo_proposal",
    order_value: float | None = None,
    value_limit: float | None = None,
    policy_version: str = "mvp-1",
) -> ActionDecision:
    if role not in {"observer", "operations", "finance", "system"}:
        return ActionDecision(
            action_id=action_id,
            status=ActionStatus.denied,
            reason="Unknown roles cannot propose actions.",
            policy_version=policy_version,
        )

    if role == "observer":
        return ActionDecision(
            action_id=action_id,
            status=ActionStatus.denied,
            reason="Observers cannot propose write actions.",
            matched_rule="deny.observer.write",
            policy_version=policy_version,
        )

    if workspace_mode == OBSERVE_ONLY_MODE:
        return ActionDecision(
            action_id=action_id,
            status=ActionStatus.denied,
            reason=(
                "Workspace is in observe-only mode; enable demo proposal mode before "
                "proposing writes."
            ),
            matched_rule="deny.workspace.observe_only",
            policy_version=policy_version,
        )

    if value_limit is not None and order_value is not None and order_value > value_limit:
        return ActionDecision(
            action_id=action_id,
            status=ActionStatus.denied,
            reason=(
                f"Order value {order_value:g} exceeds the configured write threshold "
                f"{value_limit:g}."
            ),
            matched_rule="deny.threshold.value",
            policy_version=policy_version,
        )

    if proposal.action_type == "cancel_order" and role == "operations":
        return ActionDecision(
            action_id=action_id,
            status=ActionStatus.approval_required,
            reason="Cancelling an order requires Operations approval.",
            matched_rule="approval.operations.cancel_order",
            policy_version=policy_version,
            required_role="operations",
        )

    if proposal.action_type in {"hold_order", "update_shipping_address"}:
        return ActionDecision(
            action_id=action_id,
            status=ActionStatus.approval_required,
            reason="This action is proposal-only in the MVP.",
            matched_rule="approval.mvp.proposal_only",
            policy_version=policy_version,
            required_role="operations",
        )

    return ActionDecision(
        action_id=action_id,
        status=ActionStatus.denied,
        reason="No explicit policy permits this action.",
        matched_rule="deny.default",
        policy_version=policy_version,
    )
