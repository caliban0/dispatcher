from __future__ import annotations

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
        id: Task id. RFC 1035 DNS label compliant.
        output: Logs of job pods.
        exit: Container exit code.
    """

    id: str
    output: str
    exit: int


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
