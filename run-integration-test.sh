#!/bin/bash
set +x
set -euo pipefail

## Requires "kind" and "kubectl".
## Requires a running "kind" cluster.
## Set "deploy_rabbit" to "true" to deploy an in-cluster RabbitMQ service.


# All Supported Arguments
ARGUMENT_LIST=(
    "cluster-name"
    "deploy-rabbit"
)


# Read Arguments
opts=$(getopt \
    --longoptions "$(printf "%s:," "${ARGUMENT_LIST[@]}")" \
    --name "$(basename "$0")" \
    --options "" \
    -- "$@"
)

# Assign Values from Arguments
eval set -- "$opts"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cluster-name)
            CLUSTER_NAME=$2
            shift 2
            ;;
        --deploy-rabbit)
            DEPLOY_RABBIT=$2
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

# Assign Defaults
CLUSTER_NAME=${CLUSTER_NAME:-"test-cluster"}
DEPLOY_RABBIT=${DEPLOY_RABBIT:-"false"}

docker build -f Dockerfile -t dispatcher:test .

kind load docker-image dispatcher:test --name "${CLUSTER_NAME}"

kubectl --context "kind-${CLUSTER_NAME}" apply -f manifests/namespace.yaml
kubectl --context "kind-${CLUSTER_NAME}" apply -f manifests/rbac.yaml
kubectl --context "kind-${CLUSTER_NAME}" apply -f manifests/pv-volume-claim.yaml

if [ "$DEPLOY_RABBIT" = "true" ]; then
    kubectl --context "kind-${CLUSTER_NAME}" apply -f manifests/rabbitmq.yaml
    sleep 10
    kubectl --context "kind-${CLUSTER_NAME}" -n dispatcher port-forward services/rabbitmq 5672:5672 &
    pf_pid=$!

    PORT_FORWARDED_BROKER="true" pdm run pytest tests/integration -vv || true
    kill "$pf_pid"
else
    sleep 5
    pdm run pytest tests/integration -vv || true
fi

kubectl --context "kind-${CLUSTER_NAME}" delete -f manifests/namespace.yaml
