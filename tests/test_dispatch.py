import argparse

from dispatcher.tasks import dispatch_job
from kombu import Connection

# No RabbitMQ, just Kubernetes part
dispatch_job(
    job_name="curl-test",
    image="curlimages/curl",
    args=["-sSLfD-", "-I", "https://example.com"]
)

# Use RabbitMQ
# dispatch_job.delay(
#     job_name="curl-test",
#     image="curlimages/curl",
#     args=["-sSLfD-", "-I", "https://example.com"]
# )

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
                exchange="my_exchange",
                routing_key="routing_key",
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, default=1)
    args = parser.parse_args()
    send_sleep_msg(args.count)
