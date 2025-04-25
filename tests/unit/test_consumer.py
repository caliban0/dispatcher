from __future__ import annotations

from typing import Any
from unittest import mock

import kombu
import pytest

from dispatcher import consumer, tasks


@pytest.fixture(autouse=True)
def consumer_step() -> Any:
    return consumer.consumer_step_factory(
        mock.create_autospec(tasks.dispatch_job, spec_set=True)
    )(mock.MagicMock())


@mock.patch("dispatcher.consumer.logging", autospec=True)
def test_on_message_with_simple_message_should_dispatch_job(
    consumer_step: Any,
) -> None:
    message = mock.create_autospec(kombu.Message, spec_set=True)

    consumer_step.on_message(message)

    message.ack.assert_called_once()
