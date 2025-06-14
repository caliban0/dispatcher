import pytest
from kubernetes import client, config

from dispatcher import constants
from dispatcher.settings import settings


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--dispatcher-image",
        action="store",
        default="dispatcher:test",
        help="Dispatcher image to use for tests. Defaults to 'dispatcher:test'.",
    )
    parser.addoption(
        "--in-cluster-broker",
        action="store",
        default="false",
        help="Whether the message broker is in-cluster. Defaults to 'false'.",
    )
    parser.addoption(
        "--service-account-name",
        action="store",
        default="dispatcher",
        help="Service account name to use for the dispatcher deployment. Defaults to 'dispatcher'.",
    )
    parser.addoption(
        "--image-secret-name",
        action="store",
        default="test-image-pull-secret",
        help="Name of the image pull secret that is assigned to job pod internal service account."
        " Defaults to 'test-image-pull-secret'.",
    )


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
def credentials_secret(k8s_core_api: client.CoreV1Api) -> None:
    """Read the cluster credentials from settings and create a Kubernetes secret."""
    secret = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=client.V1ObjectMeta(name="credentials-secret"),
        string_data=settings.model_dump(),
    )

    k8s_core_api.create_namespaced_secret(namespace=constants.NAMESPACE, body=secret)


@pytest.fixture(scope="session", autouse=True)
def dispatcher_deployment(
    k8s_app_api: client.AppsV1Api,
    credentials_secret: None,
    pytestconfig: pytest.Config,
) -> None:
    container = client.V1Container(
        name=constants.APP_NAME,
        image=pytestconfig.getoption("--dispatcher-image"),
        image_pull_policy="Never",
        env_from=[
            client.V1EnvFromSource(
                secret_ref=client.V1SecretEnvSource(name="credentials-secret")
            )
        ],
    )

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": constants.APP_NAME}),
        spec=client.V1PodSpec(
            containers=[container],
            service_account_name=pytestconfig.getoption("--service-account-name"),
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
    """Set up a persistent volume for later use in the tests.

    Creates a persistent volume with the file "hello.txt" and content
    "hello world!".
    """
    volume = client.V1Volume(
        name="init-volume",
        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
            claim_name=settings.pvc_name
        ),
    )

    volume_mount = client.V1VolumeMount(
        mount_path="/root",
        name="init-volume",
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


@pytest.fixture(scope="session", autouse=True)
def image_pull_secret_patch(
    dispatcher_deployment: None, k8s_core_api: client.CoreV1Api, image_pull_secret: str
) -> None:
    sa = k8s_core_api.read_namespaced_service_account(
        name=settings.internal_service_account_name, namespace=constants.NAMESPACE
    )
    sa.image_pull_secrets = [client.V1LocalObjectReference(name=image_pull_secret)]

    k8s_core_api.patch_namespaced_service_account(
        name=settings.internal_service_account_name,
        namespace=constants.NAMESPACE,
        body=sa,
    )


@pytest.fixture(scope="session")
def consumer_broker_url(pytestconfig: pytest.Config) -> str:
    if pytestconfig.getoption("--in-cluster-broker") == "true":
        return "amqp://guest:guest@localhost:5672//"
    else:
        return str(settings.broker_url)


@pytest.fixture(scope="session")
def image_pull_secret(pytestconfig: pytest.Config) -> str:
    val = pytestconfig.getoption("--image-secret-name")
    if isinstance(val, str):
        return val
    raise RuntimeError("--image-secret-name must be a string.")
