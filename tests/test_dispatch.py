from dispatcher.tasks import dispatch_job

# No RabbitMQ, just Kubernetes part
dispatch_job(
    job_name="curl-test",
    image="curlimages/curl",
    args=["-sSLfD-", "-I", "https://example.com"]
)

# Use RabbitMQ
# dispatch_job.delay(
#     job_name="curl-test",
#     image="curlimages/curl",
#     args=["-sSLfD-", "-I", "https://example.com"]
# )
