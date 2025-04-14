from __future__ import annotations

import json
import uuid
from typing import Any

from kombu import Connection, Exchange, Queue

from dispatcher.settings import settings

_task_exchange = Exchange(settings.task_exchange_name, settings.task_exchange_type)
_task_queue = Queue(
    settings.task_queue_name,
    exchange=_task_exchange,
    routing_key=settings.task_routing_key,
)

_response_exchange = Exchange(
    settings.response_exchange_name, settings.response_exchange_type
)
_response_queue = Queue(
    settings.response_queue_name,
    exchange=_response_exchange,
    routing_key=settings.response_routing_key,
)


def test_happy_path(consumer_broker_url: str) -> None:
    job_name = "sleep-" + str(uuid.uuid4())

    def process_return(body: Any, message: Any) -> None:
        message.ack()
        assert body == {"id": job_name, "output": "/opt\n", "exit": 0}

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            json.dumps(
                {
                    "id": job_name,
                    "image": "alpine:3.21.3",
                    "cmd": ["pwd"],
                    "working_dir": "/opt"
                }
            ),
            exchange=_task_exchange,
            routing_key=settings.task_routing_key,
            declare=[_task_queue],
            retry=False,
        )

        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]


def test_sad_path(consumer_broker_url: str) -> None:
    job_name = "sleep-" + str(uuid.uuid4())

    def process_return(body: Any, message: Any) -> None:
        message.ack()
        assert body == {
            "id": job_name,
            "output": "sh: sleeeeep: not found\n",
            "exit": 127,
        }

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            json.dumps(
                {
                    "id": job_name,
                    "image": "alpine:3.21.3",
                    "cmd": ["sh", "-c", "sleeeeep 1"],
                }
            ),
            exchange=_task_exchange,
            routing_key=settings.task_routing_key,
            declare=[_task_queue],
            retry=False,
        )

        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]
