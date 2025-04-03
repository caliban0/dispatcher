import logging
import re

from celery import Celery
from celery.utils.log import get_task_logger
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

# Kubernetes stubs issues.
from kubernetes import watch as k8s_watch  # type: ignore[attr-defined]

from dispatcher import constants
from dispatcher.consumer import MyConsumerStep
from dispatcher.settings import settings

logger = get_task_logger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

if settings.k8s_in_cluster == "true":
    # Kubernetes stubs issues, both should be exported.
    k8s_config.load_incluster_config()  # type: ignore[attr-defined]
else:
    k8s_config.load_kube_config() # type: ignore[attr-defined]

app = Celery(
    constants.APP_NAME, broker=str(settings.broker_url)
)

app.steps["consumer"].add(MyConsumerStep)


def _is_valid_dns_label(label: str) -> bool:
    p = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
    return bool(p.fullmatch(label))


class JobDispatcher:
    def __init__(
        self,
        core_api_instance: k8s_client.api.core_v1_api.CoreV1Api,
        batch_api_instance: k8s_client.api.batch_v1_api.BatchV1Api,
        watch: k8s_watch.Watch,
    ):
        self._core_api_instance = core_api_instance
        self._batch_api_instance = batch_api_instance
        self._watch = watch

    def build_job(
        self, image: str, name: str, args: list[str], cmd: list[str] | None = None
    ) -> k8s_client.V1Job:
        """Build the job object.

        Arguments:
            image: Container image name.
            name: Job name. Will also be the container name and is required to be a valid DNS label.
            args: Arguments to the entrypoint.
            cmd: Entrypoint list.
        """
        if not _is_valid_dns_label(name):
            raise ValueError(f"job name '{name}' is not a valid DNS label")

        container = k8s_client.V1Container(
            name=name,
            image=image,
            args=args,
            command=cmd,
        )

        pod_spec = k8s_client.V1PodSpec(
            containers=[container],
            restart_policy=constants.POD_RESTART_POLICY,
        )

        template = k8s_client.V1PodTemplateSpec(
            spec=pod_spec,
        )

        job_spec = k8s_client.V1JobSpec(
            template=template,
            ttl_seconds_after_finished=constants.TTL_AFTER_FINISHED,
        )

        return k8s_client.V1Job(
            api_version=constants.JOB_API_VERSION,
            kind="Job",
            metadata=k8s_client.V1ObjectMeta(name=name),
            spec=job_spec,
        )

    def run_job(self, job: k8s_client.V1Job, namespace: str) -> None:
        self._batch_api_instance.create_namespaced_job(namespace=namespace, body=job)

    def wait_for_job_completion(self, job_name: str, namespace: str) -> bool:
        """Wait for job completion.

        This is done via *watches*, where we monitor the event stream, until the job
        has a failed or successful pod. Will NOT work for jobs with parallelization.
        """
        for event in self._watch.stream(
            self._batch_api_instance.list_namespaced_job,
            namespace=namespace,
            field_selector=f"metadata.name={job_name}",
            timeout_seconds=constants.WATCH_SERVER_TIMEOUT,
            _request_timeout=constants.WATCH_CLIENT_TIMEOUT,
        ):
            job_obj = event["object"]

            if job_obj.status.succeeded is not None and job_obj.status.succeeded > 0:
                self._watch.stop()
                return True

            if job_obj.status.failed is not None and job_obj.status.failed > 0:
                self._watch.stop()
                return False

        return False

    def get_job_pod_logs(self, job_name: str, namespace: str) -> str:
        """Get logs of all the pods created by a job.

        Returns:
            The logs, separated by newlines.
        """
        pods = self._core_api_instance.list_namespaced_pod(
            namespace=namespace, label_selector=f"job-name={job_name}"
        )

        logs: list[str] = []

        for pod in pods.items:
            # In practice, this can only happen if we try to read a pod when we shouldn't
            # e.g. during create or update. Otherwise, 'metadata' is a required field.
            pod_name = pod.metadata.name if pod.metadata is not None else None
            if pod_name is None:
                logger.error(f"No metadata for pod created by job: '{job_name}'")
                continue

            log = self._core_api_instance.read_namespaced_pod_log(pod_name, namespace)
            logs.append(log)

        return "\n".join(logs)


@app.task(ignore_result=True)
def dispatch_job(
    job_name: str, image: str, args: list[str], cmd: list[str] | None = None
) -> None:
    batch_api = k8s_client.BatchV1Api()
    core_api = k8s_client.CoreV1Api()
    watcher = k8s_watch.Watch()

    job_dispatcher = JobDispatcher(core_api, batch_api, watcher)
    try:
        job = job_dispatcher.build_job(image, job_name, args, cmd)
        logger.info(f"Built job: '{job_name}'")

        job_dispatcher.run_job(job, constants.NAMESPACE)
        logger.info(f"Running job: '{job_name}'")

        job_status = job_dispatcher.wait_for_job_completion(
            job_name, constants.NAMESPACE
        )
        if job_status:
            logger.info(f"Job '{job_name}' completed successfully")
        else:
            logger.error(f"Job '{job_name}' failed")

        logs = job_dispatcher.get_job_pod_logs(job_name, constants.NAMESPACE)
        if not logs:
            logger.error(f"Job '{job_name}' pod logs empty")
    except Exception as e:
        logger.exception(e)
        return

    logger.info(logs)
