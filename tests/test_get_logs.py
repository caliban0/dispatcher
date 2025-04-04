from __future__ import annotations

from kombu import Connection, Exchange, Queue

log_exchange = Exchange("responses", "direct", durable=True)
log_queue = Queue("responses", exchange=log_exchange, routing_key="response")


def process_log(body, message) -> None:
    print(body)
    message.ack()


def consume_logs() -> None:
    with Connection("amqp://guest:guest@localhost//") as conn:
        with conn.Consumer(log_queue, callbacks=[process_log]) as _:
            while True:
                conn.drain_events()


if __name__ == "__main__":
    consume_logs()
