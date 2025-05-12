from __future__ import annotations

import json
import time
import uuid

from kombu import Connection, Consumer, Exchange, Queue, pools
from locust import User, constant_throughput, task
from locust.env import Environment

from dispatcher.settings import settings

connection = Connection("amqp://guest:guest@localhost:5672//")

_task_exchange = Exchange(
    settings.task_exchange_name,
    settings.task_exchange_type,
    durable=True,
    auto_delete=False,
    delivery_mode=2,
)
_task_queue = Queue(
    settings.task_queue_name,
    _task_exchange,
    settings.task_routing_key,
    durable=True,
    auto_delete=False,
)
_response_exchange = Exchange(
    settings.response_exchange_name,
    settings.response_exchange_type,
    durable=True,
    auto_delete=False,
    delivery_mode=2,
)
_response_queue = Queue(
    settings.response_queue_name,
    _response_exchange,
    settings.response_routing_key,
    durable=True,
    auto_delete=False,
)


class AmqpClient:
    def __init__(self, conn: Connection, environment: Environment) -> None:
        self.environment = environment
        self._conn = conn

    def publish(
        self,
        msg: str | bytes | bytearray,
        exchange: Exchange,
        queue: Queue,
        routing_key: str,
        name: str | None = None,
    ) -> None:
        name = name if name else routing_key

        with pools.producers[self._conn].acquire(block=True) as producer:  # type: ignore[attr-defined]
            start_time = time.time()
            start_perf_counter = time.perf_counter()

            producer.publish(
                msg,
                exchange=exchange,
                routing_key=routing_key,
                declare=[queue, exchange],
                retry=True,
                retry_policy={
                    "interval_start": 0,
                    "interval_step": 2,
                    "interval_max": 30,
                    "max_retries": 30,
                },
            )

            self.environment.events.request.fire(  # type: ignore[no-untyped-call]
                request_type="AMQP",
                request_method="publish",
                name=name,
                start_time=start_time,
                response_time=(time.perf_counter() - start_perf_counter) * 1000,
                response_length=0,
                context={},
                exception=None,
            )

    def consume(self, queue: Queue, name: str | None = None) -> None:
        with (
            pools.connections[self._conn].acquire(block=True) as conn,  # type: ignore[attr-defined]
            conn.channel() as channel,
            Consumer(channel, [queue], on_message=lambda msg: msg.ack()),  # type: ignore[attr-defined]
        ):
            start_time = time.time()
            start_perf_counter = time.perf_counter()
            name = name if name else queue.name

            conn.drain_events()

            self.environment.events.request.fire(  # type: ignore[no-untyped-call]
                request_type="AMQP",
                request_method="consume",
                name=name,
                start_time=start_time,
                response_time=(time.perf_counter() - start_perf_counter) * 1000,
                response_length=0,
                context={},
            )


class AmqpUser(User):
    abstract = True

    # abstraction hack
    broker_url: str = None  # type: ignore[assignment]

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)
        self.client = AmqpClient(Connection(self.broker_url), environment)


class QuickstartUser(AmqpUser):
    wait_time = constant_throughput(0.1)  # type: ignore[no-untyped-call]

    broker_url = "amqp://guest:guest@localhost:5672//"

    @task
    def print_ls(self) -> None:
        job_id = "test-ls-" + str(uuid.uuid4())
        print(f"Sending job {job_id}")

        self.client.publish(
            json.dumps(
                {
                    "id": job_id,
                    "image": "alpine:latest",
                    "volume_mount_path": "/root/",
                    "cmd": ["ls"],
                }
            ),
            _task_exchange,
            _task_queue,
            settings.task_routing_key,
        )

        self.client.consume(_response_queue)
