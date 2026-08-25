import asyncio
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from core.agent_framework.types import AgentMessage


class MessageBus:

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._history: list[dict] = []
        self._agent_map: dict[str, Any] = {}
        self._correlation_id: int = 0

    def _next_correlation_id(self) -> int:
        self._correlation_id += 1
        return self._correlation_id

    def register_agent(self, name: str, agent: Any):
        self._agent_map[name] = agent

    async def send(self, msg: AgentMessage):
        if not hasattr(msg, 'correlation_id') or msg.correlation_id is None:
            msg.correlation_id = self._next_correlation_id()
        await self._queues[msg.receiver].put(msg)
        self._history.append({
            "correlation_id": msg.correlation_id,
            "from": msg.sender, "to": msg.receiver,
            "type": msg.message_type, "time": datetime.now().isoformat(),
            "content_preview": str(msg.content)[:200],
        })

    async def receive(self, agent_name: str, timeout: float = 60.0,
                      correlation_id: int | None = None) -> AgentMessage | None:
        deadline = time.monotonic() + timeout

        retry_buf: list[AgentMessage] = []

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(
                    self._queues[agent_name].get(), timeout=min(remaining, 1.0)
                )
                if correlation_id is None or msg.correlation_id == correlation_id:
                    for m in retry_buf:
                        await self._queues[agent_name].put(m)
                    return msg
                retry_buf.append(msg)
                if len(retry_buf) > 100:
                    for m in retry_buf:
                        await self._queues[agent_name].put(m)
                    retry_buf.clear()
            except asyncio.TimeoutError:
                continue

        for m in retry_buf:
            await self._queues[agent_name].put(m)
        return None

    async def request_response(self, sender: str, receiver: str, content: Any,
                                timeout: float = 60.0) -> Any:
        corr_id = self._next_correlation_id()

        await self.send(AgentMessage(
            sender=sender, receiver=receiver,
            message_type="question", content=content,
            correlation_id=corr_id,
        ))

        if receiver in self._agent_map:
            agent = self._agent_map[receiver]
            question_msg = await self.receive(receiver, timeout=5.0,
                                               correlation_id=corr_id)
            if question_msg and question_msg.message_type == "question":
                answer = await agent.run(str(question_msg.content))
                await self.send(AgentMessage(
                    sender=receiver, receiver=sender,
                    message_type="answer", content=answer.data,
                    correlation_id=corr_id,
                ))

        response = await self.receive(sender, timeout=timeout,
                                       correlation_id=corr_id)
        return response.content if response else None
