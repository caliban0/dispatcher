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
