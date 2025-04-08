from __future__ import annotations

from collections.abc import Sequence

from kombu import Connection, Exchange, Queue
from pydantic import BaseModel

from dispatcher.settings import settings

_response_exchange = Exchange(
    settings.response_exchange_name, settings.response_exchange_type
)
_response_queue = Queue(
    settings.response_queue_name,
    exchange=_response_exchange,
    routing_key=settings.response_routing_key,
)


class ResponseModel(BaseModel):
    """Message response model.

    Attributes:
        job_name: Job name. RFC 1035 DNS label compliant.
        image: The image that was used for the job pod container.
        args: Arguments passed to the job pod container. Corresponds to CMD in Docker.
        cmd: Commands passed to the job pod container. Corresponds to ENTRYPOINT in Docker.
        logs: Logs of job pods.
    """

    job_name: str
    image: str
    args: Sequence[str] | None
    cmd: Sequence[str] | None
    logs: list[str]


def produce_response_msg(resp: ResponseModel) -> None:
    with Connection(str(settings.broker_url)) as conn:
        # Connection does have the Producer attribute, a celery type stub issue.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            resp.model_dump(),
            exchange=_response_exchange,
            routing_key=settings.response_routing_key,
            declare=[_response_queue],
            retry=True,
            retry_policy={
                "interval_start": 0,
                "interval_step": 2,
                "interval_max": 30,
                "max_retries": 30,
            },
        )
