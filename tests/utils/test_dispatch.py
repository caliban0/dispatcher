import argparse

from kombu import Connection


def send_sleep_msg(count: int) -> None:
    for _ in range(count):
        with Connection("amqp://guest:guest@localhost//") as conn:
            # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
            producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
            producer.publish(
                {
                    "job_name": "sleep",
                    "image": "alpine:3.21.3",
                    "cmd": ["sh", "-c"],
                    "args": ['echo "Starting"; sleep 10; echo "Done"'],
                },
                exchange="tasks",
                routing_key="tasks",
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, default=1)
    args = parser.parse_args()
    send_sleep_msg(args.count)
