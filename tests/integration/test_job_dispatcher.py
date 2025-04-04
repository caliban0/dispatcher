from __future__ import annotations

from kombu import Connection, Exchange, Queue
from kubernetes import client

from dispatcher.settings import settings


def test_happy_path(k8s_core_api: client.CoreV1Api) -> None:
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

    def process_return(body, message) -> None:
        assert body == "Starting"

    with Connection(str(settings.broker_url)) as conn:
        # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            {
                "job_name": "sleep",
                "image": "alpine:3.21.3",
                "cmd": ["sh", "-c"],
                "args": ['echo "Starting"; sleep 1; echo "Done"'],
            },
            exchange=_task_exchange,
            routing_key=settings.task_routing_key,
            declare=[_task_queue],
            retry=False,
        )

        received = False
        with conn.Consumer(_response_queue, callbacks=[process_return]) as _:
            while not received:
                conn.drain_events()
