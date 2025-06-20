from __future__ import annotations

from collections.abc import Iterator
from unittest import mock
from unittest.mock import MagicMock, create_autospec

import pytest
from kubernetes import client as k8s_client

# Kubernetes stubs issues.
from kubernetes import watch as k8s_watch  # type: ignore[attr-defined]
from pydantic import ValidationError

from dispatcher import tasks
from dispatcher.consumer import TaskArgModel


@pytest.fixture
def job_dispatcher() -> tasks.JobDispatcher:
    return tasks.JobDispatcher(
        create_autospec(k8s_client.api.core_v1_api.CoreV1Api, spec_set=True),
        create_autospec(k8s_client.api.batch_v1_api.BatchV1Api, spec_set=True),
        create_autospec(k8s_watch.Watch, spec_set=True),
    )


def test_build_job_returns_job_when_k8s_success(
    job_dispatcher: tasks.JobDispatcher,
) -> None:
    job = job_dispatcher.build_job(
        TaskArgModel(
            image="alpine:3.21.3",
            id="sleep-100d92ab-e9b4-4cd4-9fbf-4213c00bda84b",
            args=['echo "Starting"; sleep 10; echo "Done"'],
            working_dir="/opt",
            volume_mount_path="/root/",
            cmd=["sh", "-c"],
        )
    )

    assert job is not None
    assert job.metadata is not None
    assert job.metadata.name == "sleep-100d92ab-e9b4-4cd4-9fbf-4213c00bda84b"
    assert job.spec is not None
    assert job.spec.template.spec is not None
    assert job.spec.template.spec.containers[0].image == "alpine:3.21.3"
    assert (
        job.spec.template.spec.containers[0].name
        == "sleep-100d92ab-e9b4-4cd4-9fbf-4213c00bda84b"
    )
    assert job.spec.template.spec.containers[0].args == [
        'echo "Starting"; sleep 10; echo "Done"'
    ]
    assert job.spec.template.spec.containers[0].command == ["sh", "-c"]
    assert job.spec.template.spec.containers[0].working_dir == "/opt"
    assert job.spec.template.spec.containers[0].volume_mounts is not None
    assert job.spec.template.spec.containers[0].volume_mounts[0].mount_path == "/root/"


def _inject_watch_stream(
    job_dispatcher: tasks.JobDispatcher, success: bool
) -> tasks.JobDispatcher:
    # Arrange mock for the Job object.
    job_obj_mock = create_autospec(k8s_client.V1Job, spec_set=True)
    if success:
        job_obj_mock.status.succeeded = 1
        job_obj_mock.status.failed = 0
    else:
        job_obj_mock.status.failed = 1
        job_obj_mock.status.succeeded = 0

    # Arrange mock for the streamed event.
    event_mock = mock.MagicMock()
    event_mock.__getitem__.return_value = job_obj_mock

    # Arrange mock for the event stream.
    def event_stream() -> Iterator[mock.MagicMock]:
        yield event_mock

    job_dispatcher._watch.stream.return_value = event_stream()

    return job_dispatcher


def test_wait_for_job_completion_returns_true_when_job_succeeds(
    job_dispatcher: tasks.JobDispatcher,
) -> None:
    job_dispatcher = _inject_watch_stream(job_dispatcher, True)

    assert job_dispatcher.wait_for_job_completion("my_job", "my_namespace") is True


def test_wait_for_job_completion_returns_false_when_job_fails(
    job_dispatcher: tasks.JobDispatcher,
) -> None:
    job_dispatcher = _inject_watch_stream(job_dispatcher, False)

    assert job_dispatcher.wait_for_job_completion("my_job", "my_namespace") is False


def test_get_result_returns_logs_exit_code_when_k8s_success(
    job_dispatcher: tasks.JobDispatcher,
) -> None:
    # Arrange for log read to return log stub on expected params.
    assert isinstance(job_dispatcher._core_api_instance, MagicMock)
    job_dispatcher._core_api_instance.read_namespaced_pod_log.side_effect = (
        lambda pod_name, namespace: "test_log"
        if pod_name == "test_pod" and namespace == "my_namespace"
        else "bad"
    )

    # Arrange the pod list mock.
    container_status = MagicMock()
    container_status.state.terminated.exit_code = 0
    pod_mock = create_autospec(k8s_client.V1Pod, spec_set=True)
    pod_mock.metadata.name = "test_pod"
    pod_mock.status.container_statuses = [container_status]
    pod_list_mock = create_autospec(k8s_client.V1PodList, spec_set=True)
    pod_list_mock.items = [pod_mock]

    job_dispatcher._core_api_instance.list_namespaced_pod.return_value = pod_list_mock

    assert job_dispatcher.get_job_result("my_job", "my_namespace") == ("test_log", 0)


valid_labels: list[str] = [
    "a",
    "z",
    "a0",
    "z9",
    "a-0",
    "z-9",
    "k-------------------------------------------------------------5",
    "ab",
    "abc",
]


@pytest.mark.parametrize("label", valid_labels)
def test_validate_task_args_succeeds_when_id_valid_dns_label(label: str) -> None:
    TaskArgModel.model_validate(
        {
            "image": "alpine:3.21.3",
            "id": label,
            "args": ['echo "Starting"; sleep 10; echo "Done"'],
            "cmd": ["sh", "-c"],
            "volume_mount_path": "/root/",
        }
    )


invalid_labels: list[str] = [
    "",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "-",
    "1",
    "z-g5-",
]


@pytest.mark.parametrize("label", invalid_labels)
def test_validate_task_args_fails_when_id_not_dns_label(label: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        TaskArgModel.model_validate(
            {
                "image": "alpine:3.21.3",
                "id": label,
                "args": ['echo "Starting"; sleep 10; echo "Done"'],
                "cmd": ["sh", "-c"],
                "volume_mount_path": "/root/",
            }
        )
    for error in excinfo.value.errors():
        assert error["msg"] == f"Value error, id '{label}' is not a valid DNS label"
