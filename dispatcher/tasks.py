import functools
import logging
from collections.abc import Callable
from typing import Any

from celery import Celery
from celery.signals import worker_init
from celery.utils.log import get_task_logger
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

# Kubernetes stubs issues.
from kubernetes import watch as k8s_watch  # type: ignore[attr-defined]

from dispatcher import constants, producer
from dispatcher.consumer import TaskArgModel, consumer_step_factory
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


class KubernetesError(Exception):
    pass


class DuplicateJobError(Exception):
    pass


def kubernetes_action[T, **P](name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator for Kubernetes actions.

    Wraps a Kubernetes action in a try-except block so that if an error occurs,
    a KubernetesError is raised.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                raise KubernetesError(
                    f"Kubernetes action '{name}' failed: {e.__class__.__name__}, {e}"
                ) from e

        return wrapper

    return decorator


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

    @kubernetes_action(name="build job")
    def build_job(
        self,
        args: TaskArgModel,
    ) -> k8s_client.V1Job:
        """Build the job object.

        Arguments:
            args: K8S parameters required for building the job.
        """
        # We're going to use the task ID as the job name.

        volume = k8s_client.V1Volume(
            name=settings.pv_name,
            persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                claim_name=settings.pvc_name
            ),
        )

        volume_mount = k8s_client.V1VolumeMount(
            mount_path=args.volume_mount_path,
            name=settings.pv_name,
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
            volumes=[volume],
            restart_policy=constants.POD_RESTART_POLICY,
            service_account_name=settings.internal_service_account_name
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

    @kubernetes_action(name="run job")
    def run_job(self, job: k8s_client.V1Job, namespace: str) -> None:
        try:
            self._batch_api_instance.create_namespaced_job(
                namespace=namespace, body=job
            )
        except k8s_client.exceptions.ApiException as e:
            if e.body is not None and '"reason":"AlreadyExists"' in e.body:
                raise DuplicateJobError() from e

    @kubernetes_action(name="wait for job completion")
    def wait_for_job_completion(self, job_name: str, namespace: str) -> bool:
        """Wait for job completion.

        This is done via *watches*, where we monitor the event stream until the job
        has a failed or successful pod. Will NOT work for jobs with parallelization
        or jobs that restart pods.
        """
        success: bool | None = None

        try:
            for event in self._watch.stream(
                self._batch_api_instance.list_namespaced_job,
                namespace=namespace,
                field_selector=f"metadata.name={job_name}",
                timeout_seconds=constants.WATCH_SERVER_TIMEOUT,
                _request_timeout=constants.WATCH_CLIENT_TIMEOUT,
            ):
                job_obj = event["object"]

                if (
                    job_obj.status.succeeded is not None
                    and job_obj.status.succeeded > 0
                ):
                    success = True
                    break

                if job_obj.status.failed is not None and job_obj.status.failed > 0:
                    success = False
                    break
        finally:
            self._watch.stop()

        if success is not None:
            return success
        raise KubernetesError(f"Couldn't wait for job {job_name} completion")

    def get_pod_container_exit_code(self, pod: k8s_client.V1Pod) -> int:
        if pod.status is not None and pod.status.container_statuses is not None:
            for container_status in pod.status.container_statuses:
                state = container_status.state

                if state is not None and state.terminated is not None:
                    return state.terminated.exit_code

        raise RuntimeError(
            f"Could not determine container exit code for pod: '{pod.to_dict()}'"
        )

    @kubernetes_action(name="get job result")
    def get_job_result(self, job_name: str, namespace: str) -> tuple[str, int]:
        """Get logs and exit code of the pod created by the job.

        The job MUST be in a terminal state.

        Raises:
            RuntimeError: If the job has more than one pod, or if the pod doesn't exist.
             If the pod doesn't have metadata or the container exit code cannot be determined.
        """
        pods = self._core_api_instance.list_namespaced_pod(
            namespace=namespace, label_selector=f"job-name={job_name}"
        )

        if len(pods.items) != 1:
            raise RuntimeError(
                f"Expected 1 pod, got {len(pods.items)} for job '{job_name}'"
            )

        pod = pods.items[0]

        exit_code = self.get_pod_container_exit_code(pod)

        # In practice, this can only happen if we try to read a pod when we shouldn't,
        # e.g., during create or update. Otherwise, 'metadata' is a required field.
        pod_name = pod.metadata.name if pod.metadata is not None else None
        if pod_name is None:
            raise RuntimeError(f"No metadata for pod created by job: '{job_name}'")

        log = self._core_api_instance.read_namespaced_pod_log(pod_name, namespace)

        return log, exit_code


def log_job_result(job_name: str, exit_code: int, logs: str) -> None:
    logger.debug("Job %s exit code: %d", job_name, exit_code)
    truncated = (
        (logs[: constants.MAX_POD_LOG_SIZE - 3] + "…")
        if len(logs) > constants.MAX_POD_LOG_SIZE
        else logs
    )
    logger.debug(
        "Job %s pod logs (%d bytes): %s",
        job_name,
        len(logs),
        truncated,
    )


@app.task(ignore_result=True)
def dispatch_job(args: TaskArgModel) -> None:
    batch_api = k8s_client.BatchV1Api()
    core_api = k8s_client.CoreV1Api()
    watcher = k8s_watch.Watch()

    job_dispatcher = JobDispatcher(core_api, batch_api, watcher)

    try:
        job = job_dispatcher.build_job(args)
        logger.info("Built job: %s", args.id)

        job_dispatcher.run_job(job, constants.NAMESPACE)
        logger.info("Started job: %s", args.id)

        job_status = job_dispatcher.wait_for_job_completion(
            args.id, constants.NAMESPACE
        )
        if job_status:
            logger.info("Job %s succeeded", args.id)
        else:
            logger.error("Job %s failed", args.id)

        logs, exit_code = job_dispatcher.get_job_result(args.id, constants.NAMESPACE)
        log_job_result(args.id, exit_code, logs)

        producer.produce_response_msg(
            producer.ResponseModel(id=args.id, output=logs, exit=exit_code)
        )
    except KubernetesError as e:
        logger.exception("Kubernetes action error for job %s", args.id)
        if e.__cause__ is not None and isinstance(e.__cause__, DuplicateJobError):
            producer.produce_response_msg(
                producer.ErrorResponseModel(id=args.id, error="Duplicate job ID")
            )
        else:
            producer.produce_response_msg(
                producer.ErrorResponseModel(id=args.id, error="Dispatcher error")
            )


app.steps["consumer"].add(consumer_step_factory(dispatch_job))

app.conf.update(accept_content=["json", "pickle"], task_serializer="pickle")
