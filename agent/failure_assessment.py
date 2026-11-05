"""Classify operational setbacks without treating an unproved result as learning."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureAssessment:
    category: str
    count_attempt: bool
    origin: str


def assess_failure(status: str, reason: str) -> FailureAssessment:
    """Known local execution failures spend the bounded goal retry budget.

    None of these reasons proves that a material, skill or strategy is bad. Such
    learning would need action-specific causal evidence that is not supplied by
    the current failure result contract.
    """
    if status == 'cancelled':
        return FailureAssessment('control', False, 'client_result')
    if status == 'unverified' or reason == 'evidence_mismatch':
        return FailureAssessment('inconclusive', False, 'backend_validation')
    if reason == 'backend_command_timeout':
        return FailureAssessment('timeout', False, 'backend_watchdog')
    if 'timeout' in reason:
        return FailureAssessment('timeout', True, 'client_result')
    if reason in {'path_obstructed', 'no_safe_path', 'item_not_collected', 'no_path'}:
        return FailureAssessment('navigation', True, 'client_result')
    if reason in {'inventory_full', 'missing_ingredients', 'missing_fuel', 'missing_tool', 'missing_item'}:
        return FailureAssessment('resource', False, 'client_result')
    if reason == 'item_entity_changed':
        return FailureAssessment('stale_state', True, 'client_result')
    if reason in {'item_missing_before_pickup', 'block_changed', 'target_changed'}:
        return FailureAssessment('stale_state', False, 'client_result')
    if reason in {'unsafe', 'danger', 'unsafe_target'}:
        return FailureAssessment('risk', False, 'client_result')
    if reason in {'inventory_busy', 'interaction_failed', 'screen_mismatch', 'craft_failed'}:
        return FailureAssessment('interaction', True, 'client_result')
    return FailureAssessment('inconclusive', False, 'client_result')
