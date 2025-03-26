from __future__ import annotations

import uuid
from typing import Any

from celery import bootsteps
from kombu import Consumer, Exchange, Queue

_queue = Queue(
    "",
    # Exchange(os.environ.get("EXCHANGE_NAME"), type="direct"),
    Exchange("my_exchange", type="direct"),
    # os.environ.get("ROUTING_KEY"),
    "routing_key",
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
