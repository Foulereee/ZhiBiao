import time
from collections import defaultdict


class CircuitBreaker:
    """熔断器——防止ReAct无限循环或工具反复失败。

    自动恢复：工具连续失败达到阈值后熔断，经过 reset_timeout 秒后
    自动恢复到半开状态（允许重试），成功则完全恢复。
    """

    def __init__(self, max_consecutive_failures: int = 3, reset_timeout: float = 60.0):
        self.failure_counts: dict[str, int] = defaultdict(int)
        self.last_failure_time: dict[str, float] = {}
        self.max_failures = max_consecutive_failures
        self.reset_timeout = reset_timeout

    def can_execute(self, tool_name: str) -> bool:
        """检查工具是否可以执行（未熔断，或已超时自动恢复）"""
        count = self.failure_counts.get(tool_name, 0)
        if count < self.max_failures:
            return True
        last_fail = self.last_failure_time.get(tool_name, 0)
        if time.monotonic() - last_fail > self.reset_timeout:
            self.failure_counts[tool_name] = self.max_failures - 1
            return True
        return False

    def record_failure(self, tool_name: str):
        """记录工具执行失败"""
        self.failure_counts[tool_name] += 1
        self.last_failure_time[tool_name] = time.monotonic()

    def record_success(self, tool_name: str):
        """记录工具执行成功（完全重置）"""
        self.failure_counts[tool_name] = 0
        self.last_failure_time.pop(tool_name, None)