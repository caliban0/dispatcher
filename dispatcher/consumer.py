from __future__ import annotations

import uuid
from typing import Any

from celery import bootsteps
from kombu import Consumer, Exchange, Queue

from dispatcher.settings import settings

_queue = Queue(
    settings.task_queue_name,
    Exchange(settings.task_exchange_name, type=settings.task_exchange_type),
    settings.task_routing_key,
)


class MyConsumerStep(bootsteps.ConsumerStep):
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
        job_id = uuid.uuid4()

        from .tasks import dispatch_job

        dispatch_job.delay(
            body["job_name"] + "-" + str(job_id),
            body["image"],
            body.get("args"),
            body.get("cmd"),
        )
        message.ack()
