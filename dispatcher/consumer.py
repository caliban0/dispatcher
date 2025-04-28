from __future__ import annotations

import logging
import re
from typing import Any

import celery
from celery import bootsteps
from kombu import Consumer, Exchange, Message, Queue
from pydantic import BaseModel, ValidationError, field_validator

from dispatcher.producer import ErrorResponseModel, produce_response_msg
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

    @field_validator("id", mode="after")
    @classmethod
    def is_valid_dns_label(cls, v: str) -> str:
        p = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
        if not bool(p.fullmatch(v)):
            raise ValueError(f"id '{v}' is not a valid DNS label")
        return v


def consumer_step_factory(
    _task: celery.app.task.Task[[TaskArgModel], None],
) -> type[bootsteps.ConsumerStep]:
    class ConsumerStep(bootsteps.ConsumerStep):
        task = _task

        # Using Any, because import 'Channel' gives an error.
        def get_consumers(self, channel: Any) -> list[Consumer]:
            return [
                Consumer(
                    channel,
                    queues=[_queue],
                    on_message=self.on_message,
                )
            ]

        def on_message(self, message: Message) -> None:
            message.ack()

            try:
                if message.body is None:
                    raise ValueError("Message body is None")
                args = TaskArgModel.model_validate_json(message.body)
            except ValidationError as e:
                error_str = f"Invalid task arguments: '{
                    [
                        {
                            'type': err.get('type', None),
                            'loc': err.get('loc', None),
                            'msg': err.get('msg', None),
                            'input': err.get('input', None),
                        }
                        for err in e.errors()
                    ]
                }'"
                logging.exception("Invalid task arguments")
                produce_response_msg(ErrorResponseModel(id=None, error=error_str))
                return
            except ValueError as e:
                error_str = str(e)
                logging.exception("Message body is None")
                produce_response_msg(ErrorResponseModel(id=None, error=error_str))
                return

            self.task.delay(args)

    return ConsumerStep
