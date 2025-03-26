import logging
import os

from celery import Celery
from kubernetes import client, config

from .consumer import MyConsumerStep

TTL_AFTER_FINISHED = 60

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

if os.getenv("K8S_IN_CLUSTER"):
    config.load_incluster_config()
else:
    config.load_kube_config()

app = Celery(
    "dispatcher", broker="pyamqp://guest@rabbitmq.dispatcher.svc.cluster.local//"
)

app.steps["consumer"].add(MyConsumerStep)


@app.task
def dispatch_job(job_name: str, image: str, args: list[str], cmd: list[str] | None = None) -> None:
    api = client.BatchV1Api()

    container = client.V1Container(
        name="task",
        image=image,
        args=args,
        command=cmd,
    )

    pod_spec = client.V1PodSpec(
        containers=[container],
        restart_policy="Never",
    )

    template = client.V1PodTemplateSpec(
        spec=pod_spec,
    )

    job_spec = client.V1JobSpec(
        template=template,
        ttl_seconds_after_finished=TTL_AFTER_FINISHED,
    )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=job_name),
        spec=job_spec,
    )

    api.create_namespaced_job(namespace="dispatcher", body=job)

    logger.info(f"Created job: {job_name}")
