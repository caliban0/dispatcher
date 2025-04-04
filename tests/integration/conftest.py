import pytest
from kubernetes import client, config, utils

from dispatcher import constants

from dispatcher.settings import settings

pytest_plugins = ("celery.contrib.pytest",)

@pytest.fixture(scope="session", autouse=True)
def _load_kube_config() -> None:
    config.load_kube_config(context="kind-dispatcher-test")


@pytest.fixture(scope="session", autouse=True)
def _load_manifests(_load_kube_config: None) -> None:
    k8s_client = client.ApiClient()
    utils.create_from_yaml(k8s_client, "manifests/namespace.yaml")
    utils.create_from_yaml(k8s_client, "manifests/rbac.yaml")
    utils.create_from_yaml(k8s_client, "manifests/rabbitmq.yaml")


@pytest.fixture(scope="session")
def k8s_core_api(_load_kube_config: None) -> client.CoreV1Api:
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def k8s_app_api(_load_kube_config: None) -> client.AppsV1Api:
    return client.AppsV1Api()

@pytest.fixture(scope="session")
def celery_config() -> dict[str, str]:
    return {
        "broker_url": str(settings.broker_url),
    }

#
# @pytest.fixture(scope="session", autouse=True)
# def dispatcher_deployment(_load_manifests: None, k8s_app_api: client.AppsV1Api) -> None:
#     container = client.V1Container(
#         name=constants.APP_NAME,
#         # Test image name is defined in the integration test script in pyproject.toml
#         image="dispatcher:test",
#         image_pull_policy="Never",
#         env=[client.V1EnvVar(name="K8S_IN_CLUSTER", value="true")],
#     )
#
#     template = client.V1PodTemplateSpec(
#         metadata=client.V1ObjectMeta(labels={"app": constants.APP_NAME}),
#         spec=client.V1PodSpec(
#             containers=[container], service_account_name=constants.APP_NAME
#         ),
#     )
#
#     spec = client.V1DeploymentSpec(
#         replicas=1,
#         template=template,
#         selector=client.V1LabelSelector(
#             match_labels={"app": constants.APP_NAME},
#         ),
#     )
#
#     deployment = client.V1Deployment(
#         api_version="apps/v1",
#         kind="Deployment",
#         metadata=client.V1ObjectMeta(
#             name=constants.APP_NAME, namespace=constants.NAMESPACE
#         ),
#         spec=spec,
#     )
#
#     k8s_app_api.create_namespaced_deployment(
#         body=deployment, namespace=constants.NAMESPACE
#     )
