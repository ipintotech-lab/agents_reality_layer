from reality_layer.actions.models import ActionDecision, ActionProposal, ActionStatus


def evaluate_policy(
    *,
    action_id: str,
    proposal: ActionProposal,
    role: str,
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
