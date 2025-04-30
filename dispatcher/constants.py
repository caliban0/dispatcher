from __future__ import annotations

APP_NAME = "dispatcher"
POD_RESTART_POLICY = "Never"
TTL_AFTER_FINISHED = 60
JOB_API_VERSION = "batch/v1"
WATCH_SERVER_TIMEOUT = 3600
WATCH_CLIENT_TIMEOUT = 60
NAMESPACE = "dispatcher"
MAX_POD_LOG_SIZE = 4_096
PV_NAME = "worker-pv-volume"
PVC_NAME = "worker-pv-claim"
SERVICE_ACCOUNT_NAME = "job-internal"
