import logging
import os

import kubernetes
from celery import Celery
from kubernetes.client.exceptions import ApiException as KubernetesApiException

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


class ApiError(Exception):
    pass


class KubernetesAPIWrapper:
    def __init__(
        self,
        core_api: kubernetes.client.api.core_v1_api.CoreV1Api,
        batch_api: kubernetes.client.api.batch_v1_api.BatchV1Api,
        watch: kubernetes.watch.watch.Watch,
    ):
        self._core_api = core_api
        self._batch_api = batch_api
        self._watch = watch

    def get_job_pods(
        self, job_name: str, namespace: str
    ) -> kubernetes.client.V1PodList:
        """Get pods by job name.

        Raises:
            ApiError
        """
        try:
            return self._core_api.list_namespaced_pod(
                namespace=namespace, label_selector=f"job-name={job_name}"
            )
        except KubernetesApiException as e:
            raise ApiError(
                f"Failed to get pods for job '{job_name}' in namespace '{namespace}': {e}"
            ) from e

    def get_pod_log(self, pod_name: str, namespace: str) -> str:
        """Get pods logs by pod name.

        Raises:
            ApiError
        """
        try:
            return self._core_api.read_namespaced_pod_log(
                name=pod_name, namespace=namespace
            )
        except KubernetesApiException as e:
            raise ApiError(
                f"Failed to get logs for pod '{pod_name}' in namespace '{namespace}': {e}"
            ) from e

    # Need to add some kind of timeout.
    def wait_for_job_terminal(self, job_name: str, namespace: str) -> bool:
        """Wait for job to reach terminal status.

        Returns:
            True if the job is successful, False otherwise.
        """
        count = 6
        for event in self._watch.stream(
            self._batch_api.list_namespaced_job,
            namespace=namespace,
            field_selector=f"metadata.name={job_name}",
        ):
            job_obj = event["object"]
            count -= 1
            if count == 0:
                self._watch.stop()

            if job_obj.status.succeeded is not None and job_obj.status.succeeded > 0:
                self._watch.stop()
                return True

            if job_obj.status.failed is not None and job_obj.status.failed > 0:
                self._watch.stop()
                return False

        return False


class JobDispatcher:
    def __init__(
        self,
        k8s_api: KubernetesAPIWrapper,
        logger: logging.Logger,
    ):
        self._k8s_api = k8s_api
        self._logger = logger

    def get_job_pod_logs(self, job_name: str, namespace: str) -> str:
        """Get logs of all the pods created by a job.

        Returns:
            The logs, separated by newlines.

        Raises:
            ApiError
        """
        try:
            pods = self._k8s_api.get_job_pods(job_name, namespace)
        except ApiError as e:
            self._logger.error(e)
            raise

        logs: list[str] = []

        for pod in pods.items:
            # In practice, this can only happen if we try to read a pod when we shouldn't
            # e.g. during create or update. Otherwise, 'metadata' is a required field.
            pod_name = pod.metadata.name if pod.metadata is not None else None
            if pod_name is None:
                self._logger.error(f"No metadata for pod created by job: '{job_name}'")
                continue

            try:
                log = self._k8s_api.get_pod_log(pod_name, namespace)
                self._logger.info(f"Job '{job_name}' pod '{pod_name}' logs: '{log}'.")
                logs.append(log)
            except ApiError as e:
                self._logger.error(e)

        if not logs:
            self._logger.warning(f"No pod logs for job '{job_name}'")

        return "\n".join(logs)


@app.task
def dispatch_job(
    job_name: str, image: str, args: list[str], cmd: list[str] | None = None
) -> None:
    batch_api = client.BatchV1Api()
    core_api = client.CoreV1Api()

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

    batch_api.create_namespaced_job(namespace="dispatcher", body=job)
    logger.info(f"Created job: {job_name}")

    logs = _wait_for_job_terminal(job_name, core_api, batch_api)
