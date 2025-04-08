from __future__ import annotations

from typing import Any

from celery import bootsteps
from kombu import Consumer, Exchange, Queue
from pydantic import BaseModel

from dispatcher.settings import settings

_queue = Queue(
    settings.task_queue_name,
    Exchange(settings.task_exchange_name, type=settings.task_exchange_type),
    settings.task_routing_key,
)


class TaskArgModel(BaseModel):
    job_name: str
    image: str
    args: list[str] | None
    cmd: list[str] | None


class ConsumerStep(bootsteps.ConsumerStep):
    def get_consumers(self, channel: Any) -> list[Consumer]:
        return [
            Consumer(
                channel,
                queues=[_queue],
                callbacks=[self.handle_message],
                accept=["json"],
            )
        ]

    def handle_message(self, body: Any, message: Any) -> None:
        # To avoid circular import.
        from .tasks import dispatch_job

        dispatch_job.delay(
            body["job_name"],
            body["image"],
            body.get("args"),
            body.get("cmd"),
        )
        message.ack()
