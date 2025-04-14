from __future__ import annotations

import json
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
    """The K8s parameters required for building a job.

    Attributes:
        id: The id of the task. Will be used as the job name, so must be RFC 1035 compliant.
        image: Full container image name.
        credentials_mount_path: The path where the credentials will be mounted in the container.
        working_dir: The working directory of the container.
        args: Container args. CMD is the Dockerfile equivalent.
        cmd: Container command. ENTRYPOINT is the Dockerfile equivalent.
    """

    id: str
    image: str
    credentials_mount_path: str
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

        # Kind of clunky, since 'delay' only accepts JSON
        # serializable objects, we have to dump into a dict pre-call.
        dispatch_job.delay(json.loads(body))
        message.ack()
