from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import AmqpDsn, field_serializer
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_env_file_path() -> str:
    """Return the absolute path of the env file."""
    project_root = Path(__file__).resolve().parent.parent
    return str(project_root / ".env")


class Settings(BaseSettings):
    """Application settings.

    Provided defaults assume an in-cluster instance.
    A .env file in the project root and environment variables
    can be used to override the default values. Serializes to a [string, string] mapping.

    Attributes:
        amqp_scheme: AMQP broker URL scheme.
        amqp_user: AMQP broker URL username.
        amqp_password: AMQP broker URL password.
        amqp_host: AMQP broker URL host.
        amqp_port: AMQP broker URL port.
        amqp_vhost: AMQP broker vhost.
        task_queue_name: The queue for the consumer boot-step.
        task_exchange_name: The exchange for the consumer boot-step.
        task_exchange_type: The exchange type for the consumer boot-step.
        task_routing_key: The routing key for the consumer boot-step.
        response_queue_name: The queue for task response logs.
        response_exchange_name: The exchange for the task response logs.
        response_exchange_type: The exchange type for the task response logs.
        response_routing_key: The routing key for the task response logs.
        pvc_name: The name of the persistent volume claim.
        internal_service_account_name: The name of the service account that job pods will use.
        k8s_in_cluster: Whether the application is in a Kubernetes cluster.
         Accepted values are "true" or "false".

    """

    model_config = SettingsConfigDict(
        env_file=_get_env_file_path(), env_file_encoding="utf-8", frozen=True
    )
    amqp_scheme: str = "amqp"
    amqp_user: str = "guest"
    amqp_password: str = "guest"
    amqp_host: str = "rabbitmq.dispatcher.svc.cluster.local"
    amqp_port: int = 5672

    @field_serializer("amqp_port")
    def serialize_amqp_port(self, amqp_port: int) -> str:
        return str(amqp_port)

    amqp_vhost: str = "/"

    @property
    def broker_url(self) -> AmqpDsn:
        """The fully built and encoded broker URL."""
        return AmqpDsn.build(
            scheme=self.amqp_scheme,
            host=self.amqp_host,
            port=self.amqp_port,
            username=quote(self.amqp_user, safe="") if self.amqp_user else "",
            password=quote(self.amqp_password, safe="") if self.amqp_password else "",
            path=self.amqp_vhost,
        )

    task_queue_name: str = "tasks"
    task_exchange_name: str = "tasks"
    task_exchange_type: str = "direct"
    task_routing_key: str = "task"
    response_queue_name: str = "responses"
    response_exchange_name: str = "responses"
    response_exchange_type: str = "direct"
    response_routing_key: str = "response"
    pvc_name: str = "worker-pv-claim"
    internal_service_account_name: str = "job-internal"
    k8s_in_cluster: Literal["true", "false"] = "true"


settings = Settings()
