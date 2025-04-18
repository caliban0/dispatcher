from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from kombu import Connection, Exchange, Queue

from dispatcher.producer import ErrorResponseModel, ResponseModel
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
        assert ResponseModel.model_validate_json(body) == ResponseModel.model_validate(
            {"id": job_name, "output": "hello", "exit": 0}
        )

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            json.dumps(
                {
                    "id": job_name,
                    "image": "alpine:3.21.3",
                    "cmd": ["cat", "username.txt"],
                    "working_dir": "/root",
                    "credentials_mount_path": "/root/",
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
        assert ResponseModel.model_validate_json(body) == ResponseModel.model_validate(
            {
                "id": job_name,
                "output": "sh: sleeeeep: not found\n",
                "exit": 127,
            }
        )

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            json.dumps(
                {
                    "id": job_name,
                    "image": "alpine:3.21.3",
                    "credentials_mount_path": "/root/",
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


test_cases: list[
    tuple[dict[str, int | str | list[str] | None], dict[str, int | str | None]]
] = [
    (
        {"no_existing": 1},
        {
            "id": None,
            "output": None,
            "exit": None,
            "error": "Invalid task arguments: '3 validation errors for TaskArgModel\nid\n"
            "  Field required [type=missing, input_value={'no_existing': 1}, input_type=dict]\n"
            "    For further information visit https://errors.pydantic.dev/2.11/v/missing\nimage\n"
            "  Field required [type=missing, input_value={'no_existing': 1}, input_type=dict]\n"
            "    For further information visit https://errors.pydantic.dev/2.11/v/missing\ncredentials_mount_path\n"
            "  Field required [type=missing, input_value={'no_existing': 1}, input_type=dict]\n"
            "    For further information visit https://errors.pydantic.dev/2.11/v/missing'",
        },
    ),
    (
        {"id": "-"},
        {
            "id": "-",
            "output": None,
            "exit": None,
            "error": "Invalid task arguments: '2 validation errors for TaskArgModel\n"
            "image\n  Field required [type=missing, input_value={'id': '-'},"
            " input_type=dict]\n"
            "    For further information visit https://errors.pydantic.dev/2.11/v/missing\n"
            "credentials_mount_path\n"
            "  Field required [type=missing, input_value={'id': '-'}, input_type=dict]\n"
            "    For further information visit https://errors.pydantic.dev/2.11/v/missing'",
        },
    ),
]


@pytest.mark.parametrize("task_req_msg,task_resp_msg", test_cases)
def test_invalid_path_no_id(
    consumer_broker_url: str,
    task_req_msg: dict[str, int | str | list[str] | None],
    task_resp_msg: dict[str, int | str | None],
) -> None:
    def process_return(body: Any, message: Any) -> None:
        message.ack()
        assert ErrorResponseModel.model_validate_json(
            body
        ) == ErrorResponseModel.model_validate(task_resp_msg)

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            json.dumps(task_req_msg),
            exchange=_task_exchange,
            routing_key=settings.task_routing_key,
            declare=[_task_queue],
            retry=False,
        )

        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]


def test_dispatcher_error_when_duplicate_job_names(consumer_broker_url: str) -> None:
    duplicate = False

    def process_return(body: Any, message: Any) -> None:
        message.ack()
        if duplicate:
            assert ErrorResponseModel.model_validate_json(
                body
            ) == ErrorResponseModel.model_validate({
                "id": "test-123",
                "output": None,
                "exit": None,
                "error": "Dispatcher error"
            })

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        def publish() -> None:
            producer.publish(
                json.dumps(
                    {
                        "id": "test-123",
                        "image": "alpine:3.21.3",
                        "cmd": ["cat", "username.txt"],
                        "working_dir": "/root",
                        "credentials_mount_path": "/root/",
                    }
                ),
                exchange=_task_exchange,
                routing_key=settings.task_routing_key,
                declare=[_task_queue],
                retry=False,
            )

        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
            publish()
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]
            duplicate = True
            publish()
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]
