from typing import TypedDict, Any


class PipelineState(TypedDict, total=False):
    project_id: str
    current_stage: str
    stage_results: dict[str, Any]
    gate_passed: dict[str, bool]
    errors: list[str]
    warnings: list[str]
    tokens_consumed: int
