from __future__ import annotations

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


def publish_msg(
    producer: Any, msg: dict[str, int | str | list[str] | None] | str
) -> None:
    producer.publish(
        msg,
        exchange=_task_exchange,
        routing_key=settings.task_routing_key,
        declare=[_task_queue],
        retry=False,
    )


test_cases_valid_params: list[
    tuple[dict[str, int | str | list[str] | None] | str, dict[str, int | str | None]]
] = [
    (
        {
            "id": "sleep-b5ea55ff-27cf-48f7-a2c9-b5412597159d",
            "image": "alpine:latest",
            "cmd": ["cat", "hello.txt"],
            "working_dir": "/root",
            "volume_mount_path": "/root/",
        },
        {
            "id": "sleep-b5ea55ff-27cf-48f7-a2c9-b5412597159d",
            "output": "hello world!\n",
            "exit": 0,
            "error": None,
        },
    ),
    (
        {
            "id": "sleep-30216d7a-0061-4c24-b029-394fda8834f5",
            "image": "alpine:latest",
            "volume_mount_path": "/root/",
            "cmd": ["sh", "-c", "sleeeeep 1"],
        },
        {
            "id": "sleep-30216d7a-0061-4c24-b029-394fda8834f5",
            "output": "sh: sleeeeep: not found\n",
            "exit": 127,
            "error": None,
        },
    ),
]


@pytest.mark.parametrize("task_req_msg,task_resp_msg", test_cases_valid_params)
def test_valid_params(
    consumer_broker_url: str,
    task_req_msg: dict[str, int | str | list[str] | None] | str,
    task_resp_msg: dict[str, int | str | None],
) -> None:
    def process_return(body: Any, message: Any) -> None:
        message.ack()
        assert ResponseModel.model_validate_json(body) == ResponseModel.model_validate(
            task_resp_msg
        )

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        publish_msg(producer, task_req_msg)

        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]


test_cases_invalid_params: list[
    tuple[dict[str, int | str | list[str] | None] | str, dict[str, int | str | None]]
] = [
    (
        {"no_existing": 1},
        {
            "id": None,
            "output": None,
            "exit": None,
            "error": "Invalid task arguments: '[{'type': 'missing', 'loc': ('id',),"
            " 'msg': 'Field required', 'input': {'no_existing': 1}},"
            " {'type': 'missing', 'loc': ('image',),"
            " 'msg': 'Field required', 'input': {'no_existing': 1}},"
            " {'type': 'missing', 'loc': ('volume_mount_path',),"
            " 'msg': 'Field required', 'input': {'no_existing': 1}}]'",
        },
    ),
    (
        {"id": "-"},
        {
            "id": None,
            "output": None,
            "exit": None,
            "error": "Invalid task arguments: '[{'type': 'value_error', 'loc': ('id',), 'msg':"
            " \"Value error, id '-' is not a valid DNS label\", 'input':"
            " '-'}, {'type': 'missing', 'loc': ('image',), 'msg':"
            " 'Field required', 'input': {'id': '-'}},"
            " {'type': 'missing', 'loc': ('volume_mount_path',), 'msg':"
            " 'Field required', 'input': {'id': '-'}}]'",
        },
    ),
    (
        "invalid-json",
        {
            "id": None,
            "output": None,
            "exit": None,
            "error": "Invalid task arguments: "
            "'[{'type': 'model_type', 'loc': (), "
            "'msg': 'Input should be an object', 'input': 'invalid-json'}]'",
        },
    ),
    (
        "unserializable",
        {
            "id": None,
            "output": None,
            "exit": None,
            "error": "Invalid task arguments: '[{'type': 'json_invalid', 'loc': (),"
            " 'msg': 'Invalid JSON: expected value at line 1 column 1',"
            " 'input': b'\\x80\\x04\\x95\\x12\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x8c\\x0eunserializable\\x94.'}]'",
        },
    ),
]


@pytest.mark.parametrize("task_req_msg,task_resp_msg", test_cases_invalid_params)
def test_invalid_params(
    consumer_broker_url: str,
    task_req_msg: dict[str, int | str | list[str] | None] | str,
    task_resp_msg: dict[str, int | str | None],
) -> None:
    def process_return(body: Any, message: Any) -> None:
        message.ack()
        assert ErrorResponseModel.model_validate_json(
            body
        ) == ErrorResponseModel.model_validate(task_resp_msg)

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        if task_req_msg == "unserializable":
            producer = conn.Producer(serializer="pickle")  # type: ignore[attr-defined]
        else:
            producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]

        publish_msg(producer, task_req_msg)

        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]


def test_dispatcher_error_when_duplicate_job_names(consumer_broker_url: str) -> None:
    duplicate = False

    def process_return(body: Any, message: Any) -> None:
        message.ack()
        if duplicate:
            assert ErrorResponseModel.model_validate_json(
                body
            ) == ErrorResponseModel.model_validate(
                {
                    "id": "test-123",
                    "output": None,
                    "exit": None,
                    "error": "Duplicate job ID",
                }
            )

    with Connection(consumer_broker_url) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]

        def publish() -> None:
            publish_msg(
                producer,
                {
                    "id": "test-123",
                    "image": "alpine:latest",
                    "cmd": ["cat", "username.txt"],
                    "working_dir": "/root",
                    "volume_mount_path": "/root/",
                },
            )

        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
            publish()
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]
            duplicate = True
            publish()
            conn.drain_events(timeout=60)  # type: ignore[attr-defined]
