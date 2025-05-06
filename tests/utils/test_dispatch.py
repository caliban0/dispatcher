import argparse
import uuid

from kombu import Connection

from dispatcher.settings import settings


def send_sleep_msg(count: int) -> None:
    for _ in range(count):
        with Connection("amqp://guest:guest@localhost:5672//") as conn:
            # Ignore mypy error, the stub doesn't properly cover kombu.Connection.
            producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
            job_name = "sleep-" + str(uuid.uuid4())
            producer.publish(
                {
                    "id": job_name,
                    "image": "alpine:latest",
                    "volume_mount_path": "/root/",
                    # "cmd": ["sh", "-c"],
                    # "args": ['echo "Starting"; sleep 10; echo "Done"'],
                    "cmd": ["ls"],
                },
                exchange=settings.task_exchange_name,
                routing_key=settings.task_routing_key,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, default=1)
    args = parser.parse_args()
    send_sleep_msg(args.count)
