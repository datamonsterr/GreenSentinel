"""Cockpit motivation stage: preserve the service assessment verbatim."""

from typing import Any


def motivation_assessment_node(brief: dict[str, Any]) -> str:
    """Present the shared assessment without a second model inference or new verdict."""
    assessment = brief.get("motivation_assessment") or {}
    narrative = assessment.get("natural_vietnamese_narrative")
    if not narrative:
        return ""
    reward = assessment.get("economic_incentive_reward", 0)
    amount = f"{reward:,.0f}".replace(",", ".")
    return f"{narrative}\n\nLợi ích tăng thêm ước tính: {amount} đồng."
