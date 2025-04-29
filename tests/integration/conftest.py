import os

import pytest
from kubernetes import client, config

from dispatcher import constants
from dispatcher.settings import settings


@pytest.fixture(scope="session", autouse=True)
def _load_kube_config() -> None:
    config.load_kube_config(context="kind-test-cluster")  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def k8s_core_api(_load_kube_config: None) -> client.CoreV1Api:
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def k8s_app_api(_load_kube_config: None) -> client.AppsV1Api:
    return client.AppsV1Api()


@pytest.fixture(scope="session")
def _env_vars() -> list[client.V1EnvVar]:
    """Set the environment to deploy in-cluster, with default routing params."""
    return [
        client.V1EnvVar(name="AMQP_SCHEME", value=settings.amqp_scheme),
        client.V1EnvVar(name="AMQP_USER", value=settings.amqp_user),
        client.V1EnvVar(name="AMQP_PASSWORD", value=settings.amqp_password),
        client.V1EnvVar(name="AMQP_HOST", value=settings.amqp_host),
        client.V1EnvVar(name="AMQP_PORT", value=str(settings.amqp_port)),
        client.V1EnvVar(name="AMQP_VHOST", value=settings.amqp_vhost),
        client.V1EnvVar(name="TASK_QUEUE_NAME", value=settings.task_queue_name),
        client.V1EnvVar(name="TASK_EXCHANGE_NAME", value=settings.task_exchange_name),
        client.V1EnvVar(name="TASK_EXCHANGE_TYPE", value=settings.task_exchange_type),
        client.V1EnvVar(name="TASK_ROUTING_KEY", value=settings.task_routing_key),
        client.V1EnvVar(name="RESPONSE_QUEUE_NAME", value=settings.response_queue_name),
        client.V1EnvVar(
            name="RESPONSE_EXCHANGE_NAME", value=settings.response_exchange_name
        ),
        client.V1EnvVar(
            name="RESPONSE_EXCHANGE_TYPE", value=settings.response_exchange_type
        ),
        client.V1EnvVar(
            name="RESPONSE_ROUTING_KEY", value=settings.response_routing_key
        ),
        client.V1EnvVar(name="K8S_IN_CLUSTER", value=settings.k8s_in_cluster),
    ]


@pytest.fixture(scope="session", autouse=True)
def dispatcher_deployment(
    k8s_app_api: client.AppsV1Api, _env_vars: list[client.V1EnvVar]
) -> None:
    container = client.V1Container(
        name=constants.APP_NAME,
        image="dispatcher:test",
        image_pull_policy="Never",
        env=_env_vars,
    )

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": constants.APP_NAME}),
        spec=client.V1PodSpec(
            containers=[container], service_account_name=constants.APP_NAME
        ),
    )

    spec = client.V1DeploymentSpec(
        replicas=1,
        template=template,
        selector=client.V1LabelSelector(
            match_labels={"app": constants.APP_NAME},
        ),
    )

    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(
            name=constants.APP_NAME, namespace=constants.NAMESPACE
        ),
        spec=spec,
    )

    k8s_app_api.create_namespaced_deployment(
        body=deployment, namespace=constants.NAMESPACE
    )


@pytest.fixture(scope="session", autouse=True)
def pv_setup(k8s_core_api: client.CoreV1Api, dispatcher_deployment: None) -> None:
    volume = client.V1Volume(
        name=constants.PV_NAME,
        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
            claim_name=constants.PVC_NAME
        ),
    )

    volume_mount = client.V1VolumeMount(
        mount_path="/root",
        name=constants.PV_NAME,
    )

    container = client.V1Container(
        name=constants.APP_NAME + "-pv-setup",
        image="alpine:latest",
        command=["/bin/ash", "-c"],
        args=['echo "hello world!" > /root/hello.txt'],
        volume_mounts=[volume_mount],
    )

    pod_spec = client.V1PodSpec(
        containers=[container], volumes=[volume], restart_policy="Never"
    )

    pod = client.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=client.V1ObjectMeta(name="pv-setup"),
        spec=pod_spec,
    )

    k8s_core_api.create_namespaced_pod(namespace=constants.NAMESPACE, body=pod)


@pytest.fixture(scope="session")
def consumer_broker_url() -> str:
    url = os.environ.get("PORT_FORWARDED_BROKER")
    if url in ("yes", "YES", "true", "True", "TRUE"):
        return "amqp://guest:guest@localhost:5672//"
    return str(settings.broker_url)
