# Kubernetes job dispatcher

Celery-AMQP-based kubernetes job dispatcher.

```sh
# Image bulding
tag=zalmarge/dispatcher:latest
docker image build -f Dockerfile --platform linux/amd64 -t "${tag}" .
docker image push "${tag}"
```

```sh
# In case you need an in-cluster RabbitMQ
kubectl apply -f manifests/rabbitmq.yaml
# Access RabbitMQ port locally
kubectl -n dispatcher port-forward services/rabbitmq 5672:5672
# Same thing with RabbitMQ management port
kubectl -n dispatcher port-forward services/rabbitmq 15672:15672
```

```sh
# Deploy application
kubectl apply -f manifests/namespace.yaml
kubectl apply -f manifests/rbac.yaml
kubectl apply -f manifests/deployment.yaml
```

## Local development environment

First off, make sure you have a kubernetes cluster running, [kind](https://kind.sigs.k8s.io/) is a good option for local
testing and development.

1. Apply the namespace, RBAC, and PVC manifests:

```sh
kubectl apply -f manifests/namespace.yaml
kubectl apply -f manifests/rbac.yaml
kubectl apply -f manifests/pv-volume-claim.yaml
```

2. If you want to use an in-cluster RabbitMQ instance, deploy and port-forward with:

```sh
kubectl apply -f manifests/rabbitmq.yaml
kubectl -n dispatcher port-forward services/rabbitmq 5672:5672
kubectl -n dispatcher port-forward services/rabbitmq 15672:15672
```

3. Build and make the Docker image accessible to the kubelet. If using `kind`, an easy way to do so is with
   `kind load docker-image <image:tag> --name <cluster-name>`. Pushing to a public repository also works.
4. Modify `manifests/deployment.yaml` according to your needs and apply it.

Here are the configuration options that can be passed as container env vars:

| Env Var                       | Description                                                                                                                                 | Default                               |
|-------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------|
| AMQP_USER                     | AMQP credential username                                                                                                                    | guest                                 |
| AMQP_PASSWORD                 | AMQP credential password                                                                                                                    | guest                                 |
| AMQP_HOST                     | AMQP host                                                                                                                                   | rabbitmq.dispatcher.svc.cluster.local |
| AMQP_PORT                     | AMQP port                                                                                                                                   | 5672                                  |
| AMQP_VHOST                    | AMQP virtual host                                                                                                                           | /                                     |
| TASK_QUEUE_NAME               | The queue from which task messages will be consumed                                                                                         | tasks                                 |
| TASK_EXCHANGE_NAME            | The exchange from which task messages will be consumed                                                                                      | tasks                                 |
| TASK_EXCHANGE_TYPE            | The type of the task exchange                                                                                                               | direct                                |
| TASK_ROUTING_KEY              | Routing key for the task queue                                                                                                              | task                                  |
| RESPONSE_QUEUE_NAME           | The queue to which response messages will be sent                                                                                           | responses                             |
| RESPONSE_EXCHANGE_NAME        | The exchange to which response messages will be sent                                                                                        | responses                             |
| RESPONSE_EXCHANGE_TYPE        | The type of the response exchange                                                                                                           | direct                                |
| RESPONSE_ROUTING_KEY          | Routing key for the response queue                                                                                                          | response                              | | worker-pv-volume                      |
| PVC_NAME                      | Persistent Volume Claim name                                                                                                                | worker-pv-claim                       |
| INTERNAL_SERVICE_ACCOUNT_NAME | The name of the service account that job pods will use (`imagePullSecrets` for job pod container images should be assigned to this account) | job-internal                          |
| K8S_IN_CLUSTER                | Whether the job dispatcher is running inside a kubernetes cluster                                                                           | true                                  |

## Usage

A custom celery consumer bootstep will consume AMQP messages from the `TASK` queue, validate them,
and, invoke a celery task, with the same AMQP URL as the message broker back-end. The message body should be in the form
of:

| Field             | Type          | Required | Description                                                                      |
|-------------------|---------------|----------|----------------------------------------------------------------------------------|
| id                | string        | Yes      | Task ID. Will be used as the kubernetes job name, so must be RFC 1035 compliant. |
| image             | string        | Yes      | Full container image name.                                                       |
| volume_mount_path | string        | Yes      | The path where the `PVC_NAME` volume will be mounted in the job pods.            |
| working_dir       | string        | No       | The working directory for the container.                                         |
| args              | Array[string] | No       | Container args. CMD is the Dockerfile equivalent.                                |
| cmd               | Array[string] | No       | Container commands. ENTRYPOINT is the Dockerfile equivalent.                     |

Example:

```json
{
    "id": "test-123",
    "image": "alpine:latest",
    "volume_mount_path": "/root/",
    "cmd": [
        "ls"
    ]
}
```

Responses containing pod logs or error messages will be sent to the `RESPONSE` queue in the form of:

| Field  | Type   | Required | Description                                                        |
|--------|--------|----------|--------------------------------------------------------------------|
| id     | string | No       | Task ID. Not guaranteed for messages that fail to pass validation. |
| output | string | No       | Logs of job pods.                                                  |
| exit   | number | No       | Container exit code.                                               |
| error  | string | No       | Error message, if one occurred.                                    |

The `error` field is meant for failed message content validation or kubernetes related errors, for containers with a
non-zero exit code, parse the `output` logs for errors.

## Message acknowledgement

The dispatcher will acknowledge task messages immediately after consuming them,
before the job is dispatched or the message content is validated. The motivation being that
even if the message is invalid, we don't want it to stay in the queue, but to respond with
an error as quickly as possible.

## Job parallelism and pod duplication

Although the jobs are run in a non-parallel, non-restarting fashion (a single pod with `restartPolicy=Never`),
kubernetes doesn't guarantee that the workload will only be run once. Ideally, that should be accounted for.
