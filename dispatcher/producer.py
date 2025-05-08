from __future__ import annotations

from kombu import Connection, Exchange, Queue
from pydantic import BaseModel

from dispatcher.settings import settings

_response_exchange = Exchange(
    settings.response_exchange_name,
    settings.response_exchange_type,
    durable=True,
    auto_delete=False,
    delivery_mode=2,
)
_response_queue = Queue(
    settings.response_queue_name,
    exchange=_response_exchange,
    routing_key=settings.response_routing_key,
    durable=True,
    auto_delete=False,
)


class ResponseModel(BaseModel):
    """Message response model.

    Attributes:
        id: Task id. RFC 1035 DNS label compliant.
        output: Logs of job pods.
        exit: Container exit code.
        error: Protocol required null error field.
    """

    id: str
    output: str
    exit: int
    error: None = None


class ErrorResponseModel(BaseModel):
    """Message error response model

    Attributes:
        id: Task id. RFC 1035 DNS label compliant. Null if not provided by the task request message.
        output: Protocol required container output field, set to null, since the container didn't run.
        exit: Protocol required container exit code, set to null, since the container didn't run.
        error: Error message.

    """

    id: str | None
    output: None = None
    exit: None = None
    error: str


def produce_response_msg(resp: ResponseModel | ErrorResponseModel) -> None:
    with Connection(str(settings.broker_url), ssl=settings.ssl) as conn:
        # Connection does have the Producer attribute, a celery type stub issue.
        producer = conn.Producer(serializer="json")  # type: ignore[attr-defined]
        producer.publish(
            resp.model_dump_json(),
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
