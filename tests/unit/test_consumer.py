from __future__ import annotations

import json
from typing import Any
from unittest import mock

import kombu
import pytest

from dispatcher import consumer, producer, tasks


@pytest.fixture()
def consumer_step() -> Any:
    return consumer.consumer_step_factory(
        mock.create_autospec(tasks.dispatch_job, spec_set=True)
    )(mock.MagicMock())


@mock.patch("dispatcher.consumer.produce_response_msg", autospec=True)
@mock.patch("dispatcher.consumer.logging", autospec=True)
def test_on_message_with_simple_message_should_dispatch_job(
    _logging: mock.MagicMock,
    _produce_response_msg: mock.MagicMock,
    consumer_step: Any,
) -> None:
    message = mock.create_autospec(kombu.Message, spec_set=True)

    body = consumer.TaskArgModel(
        id="test-123", image="test-image:latest", volume_mount_path="/"
    )
    message.body = body.model_dump_json()

    consumer_step.on_message(message)

    message.ack.assert_called_once()
    consumer_step.task.delay.assert_called_once_with(body)


@mock.patch("dispatcher.consumer.produce_response_msg", autospec=True)
@mock.patch("dispatcher.consumer.logging", autospec=True)
def test_on_message_with_none_message_body_should_fail(
    _logging: mock.MagicMock, _produce_response_msg: mock.MagicMock, consumer_step: Any
) -> None:
    message = mock.create_autospec(kombu.Message, spec_set=True)

    message.body = None

    consumer_step.on_message(message)

    message.ack.assert_called_once()
    consumer_step.task.delay.assert_not_called()

    _logging.exception.assert_called_once_with("Message body is None")
    _produce_response_msg.assert_called_once_with(
        producer.ErrorResponseModel(id=None, error="Message body is None")
    )


@mock.patch("dispatcher.consumer.produce_response_msg", autospec=True)
@mock.patch("dispatcher.consumer.logging", autospec=True)
def test_on_message_with_invalid_message_body_should_fail(
    _logging: mock.MagicMock, _produce_response_msg: mock.MagicMock, consumer_step: Any
) -> None:
    message = mock.create_autospec(kombu.Message, spec_set=True)

    body = {"id": 1}

    message.body = json.dumps(body)

    consumer_step.on_message(message)

    message.ack.assert_called_once()
    consumer_step.task.delay.assert_not_called()

    _logging.exception.assert_called_once_with("Invalid task arguments")
    _produce_response_msg.assert_called_once_with(
        producer.ErrorResponseModel(
            id=None,
            error="Invalid task arguments: "
            "'[{'type': 'string_type', 'loc': ('id',),"
            " 'msg': 'Input should be a valid string', 'input': 1},"
            " {'type': 'missing', 'loc': ('image',),"
            " 'msg': 'Field required', 'input': {'id': 1}},"
            " {'type': 'missing', 'loc': ('volume_mount_path',),"
            " 'msg': 'Field required', 'input': {'id': 1}}]'",
        )
    )
