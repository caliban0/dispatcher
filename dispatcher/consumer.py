from __future__ import annotations

import logging
from typing import Any

from celery import bootsteps
from kombu import Consumer, Exchange, Queue
from pydantic import BaseModel, ValidationError

from dispatcher.settings import settings

_queue = Queue(
    settings.task_queue_name,
    Exchange(settings.task_exchange_name, type=settings.task_exchange_type),
    settings.task_routing_key,
)

class TaskArgModel(BaseModel):
    id: str
    image: str
    working_dir: str | None = None
    args: list[str] | None = None
    cmd: list[str] | None = None


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

        try:
            args = TaskArgModel.model_validate_json(body)
        except ValidationError as e:
            logging.error(e.errors())
            message.reject()
            return

        dispatch_job.delay(
            args.id,
            args.image,
            args.working_dir,
            args.args,
            args.cmd,
        )
        message.ack()
