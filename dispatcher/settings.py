from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AmqpDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_env_file_path() -> str:
    """Return absolute path of env file."""
    project_root = Path(__file__).resolve().parent.parent
    return str(project_root / ".env")


class Settings(BaseSettings):
    """Application settings.

    Provided defaults assume an in-cluster instance.
    A .env file in the project root and environment variables
    can be used to override the default values.

    Attributes:
        broker_url: AMQP broker URL.
        task_queue_name: The queue for the consumer boot-step.
        task_exchange_name: The exchange for the consumer boot-step.
        task_exchange_type: The exchange type for the consumer boot-step.
        task_routing_key: The routing key for the consumer boot-step.
        response_queue_name: The queue for task response logs.
        response_exchange_name: The exchange for the task response logs.
        response_exchange_type: The exchange type for the task response logs.
        response_routing_key: The routing key for the task response logs.
        k8s_in_cluster: Whether the application is in a Kubernetes cluster.
         Accepted values are "true" or "false".

    """

    model_config = SettingsConfigDict(
        env_file=_get_env_file_path(), env_file_encoding="utf-8", frozen=True
    )
    broker_url: AmqpDsn = AmqpDsn(
        "amqp://guest@rabbitmq.dispatcher.svc.cluster.local//"
    )
    task_queue_name: str = "tasks"
    task_exchange_name: str = "tasks"
    task_exchange_type: str = "direct"
    task_routing_key: str = "task"
    response_queue_name: str = "responses"
    response_exchange_name: str = "responses"
    response_exchange_type: str = "direct"
    response_routing_key: str = "response"
    k8s_in_cluster: Literal["true", "false"] = "true"


settings = Settings()
