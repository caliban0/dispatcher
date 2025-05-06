from typing import Any

from kombu import Connection, Exchange, Queue

from dispatcher.settings import settings

_response_exchange = Exchange(
    settings.response_exchange_name, settings.response_exchange_type
)
_response_queue = Queue(
    settings.response_queue_name,
    exchange=_response_exchange,
    routing_key=settings.response_routing_key,
)


def process_return(body: Any, message: Any) -> None:
    print(body)
    message.ack()


with Connection("amqp://guest:guest@localhost:5672//") as conn:
    with conn.Consumer(_response_queue, callbacks=[process_return]) as _:  # type: ignore[attr-defined]
        conn.drain_events(timeout=20)  # type: ignore[attr-defined]
