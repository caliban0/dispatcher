import logging
import re
from typing import Any

from celery import Celery
from celery.signals import worker_init
from celery.utils.log import get_task_logger
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

# Kubernetes stubs issues.
from kubernetes import watch as k8s_watch  # type: ignore[attr-defined]

from dispatcher import constants, producer
from dispatcher.consumer import ConsumerStep, TaskArgModel
from dispatcher.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


logger = get_task_logger(__name__)


@worker_init.connect
def setup_k8s(**kwargs: Any) -> None:
    if settings.k8s_in_cluster == "true":
        # Kubernetes stubs issues, both should be exported.
        k8s_config.load_incluster_config()  # type: ignore[attr-defined]
    else:
        k8s_config.load_kube_config()  # type: ignore[attr-defined]


app = Celery(constants.APP_NAME, broker=str(settings.broker_url))

app.steps["consumer"].add(ConsumerStep)


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
        self,
        args: TaskArgModel,
    ) -> k8s_client.V1Job:
        """Build the job object.

        Arguments:
            args: K8S parameters required for building the job.
        """
        # We're going to use the task ID as the job name.
        if not _is_valid_dns_label(args.id):
            raise ValueError(f"job name '{args.id}' is not a valid DNS label")

        volume_mount = k8s_client.V1VolumeMount(
            name=constants.CREDENTIALS_VOLUME_NAME,
            mount_path=args.credentials_mount_path,
            read_only=True,
        )

        container = k8s_client.V1Container(
            name=args.id,
            image=args.image,
            args=args.args,
            command=args.cmd,
            working_dir=args.working_dir,
            stdin=True,
            tty=True,
            volume_mounts=[volume_mount],
        )

        pod_spec = k8s_client.V1PodSpec(
            containers=[container],
            volumes=[
                k8s_client.V1Volume(
                    name=constants.CREDENTIALS_VOLUME_NAME,
                    secret=k8s_client.V1SecretVolumeSource(
                        secret_name=constants.CREDENTIALS_SECRET_NAME
                    ),
                )
            ],
            restart_policy=constants.POD_RESTART_POLICY,
        )

        template = k8s_client.V1PodTemplateSpec(
            spec=pod_spec,
        )

        job_spec = k8s_client.V1JobSpec(
            template=template,
            ttl_seconds_after_finished=constants.TTL_AFTER_FINISHED,
            backoff_limit=0,
        )

        return k8s_client.V1Job(
            api_version=constants.JOB_API_VERSION,
            kind="Job",
            metadata=k8s_client.V1ObjectMeta(name=args.id),
            spec=job_spec,
        )

    def run_job(self, job: k8s_client.V1Job, namespace: str) -> None:
        self._batch_api_instance.create_namespaced_job(namespace=namespace, body=job)

    def wait_for_job_completion(self, job_name: str, namespace: str) -> bool:
        """Wait for job completion.

        This is done via *watches*, where we monitor the event stream, until the job
        has a failed or successful pod. Will NOT work for jobs with parallelization
        or jobs that restart pods.
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

    def get_pod_container_exit_code(self, pod: k8s_client.V1Pod) -> int:
        if pod.status is not None and pod.status.container_statuses is not None:
            for container_status in pod.status.container_statuses:
                state = container_status.state

                if state is not None and state.terminated is not None:
                    return state.terminated.exit_code

        raise ValueError(
            f"Could not determine pod container exit code for pod: '{pod.to_dict()}'"
        )

    def get_job_result(self, job_name: str, namespace: str) -> tuple[str, int]:
        """Get logs and exit code of the first pod created by the job.

        The job MUST be in terminal state.
        """
        pods = self._core_api_instance.list_namespaced_pod(
            namespace=namespace, label_selector=f"job-name={job_name}"
        )

        logs: list[str] = []
        exit_codes: list[int] = []

        for pod in pods.items:
            exit_codes.append(self.get_pod_container_exit_code(pod))

            # In practice, this can only happen if we try to read a pod when we shouldn't
            # e.g. during create or update. Otherwise, 'metadata' is a required field.
            pod_name = pod.metadata.name if pod.metadata is not None else None
            if pod_name is None:
                logger.error(f"No metadata for pod created by job: '{job_name}'")
                continue

            log = self._core_api_instance.read_namespaced_pod_log(pod_name, namespace)
            logs.append(log)

        return logs[0], exit_codes[0]


@app.task(ignore_result=True, pydantic=True)
def dispatch_job(args: TaskArgModel) -> None:



    batch_api = k8s_client.BatchV1Api()
    core_api = k8s_client.CoreV1Api()
    watcher = k8s_watch.Watch()

    job_dispatcher = JobDispatcher(core_api, batch_api, watcher)

    # Use ID as job name.
    try:
        job = job_dispatcher.build_job(args)
        logger.info(f"Built job: '{args.id}'")

        job_dispatcher.run_job(job, constants.NAMESPACE)
        logger.info(f"Running job: '{args.id}'")

        job_status = job_dispatcher.wait_for_job_completion(
            args.id, constants.NAMESPACE
        )
        if job_status:
            logger.info(f"Job '{args.id}' completed successfully")
        else:
            logger.error(f"Job '{args.id}' failed")

        logs, exit_code = job_dispatcher.get_job_result(args.id, constants.NAMESPACE)
        if not logs:
            logger.error(f"Job '{args.id}' pod logs empty")
        else:
            logger.info(f"Job '{args.id}' pod logs: {logs}")

        producer.produce_response_msg(
            producer.ResponseModel(id=args.id, output=logs, exit=exit_code)
        )
    except Exception as e:
        logger.exception(e)
        return
