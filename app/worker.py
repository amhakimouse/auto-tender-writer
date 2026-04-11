"""
app/worker.py

Celery application instance for background task processing.

Why Celery?
  LLM calls are slow (2-30 seconds). If we called them synchronously in the
  FastAPI request handler, the HTTP response would hang and eventually timeout.
  Instead, the router enqueues a Celery task and immediately returns a
  202 Accepted with a task_id.  The client polls /tasks/{task_id}/status.

Architecture rule:
  - Tasks call service functions — they never touch the DB or LLM directly.
  - All DB mutations go through the service layer, which logs to audit_logger.
  - Tasks are idempotent: re-running a failed task must be safe.

Milestone mapping:
  - Milestone 2: compliance_check task
  - Milestone 3: technical_score task, financial_extract task
  - Milestone 4: notification_send task
"""

from celery import Celery

from app.core.config import settings

# Create the Celery app, pointed at Redis as both broker and result backend
celery_app = Celery(
    "auto_tender_writer",
    broker=settings.REDIS_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        # Task modules registered here will be auto-discovered by the worker.
        # Uncomment each as the corresponding Milestone is implemented:
        # "app.tasks.compliance_tasks",   # Milestone 2
        # "app.tasks.evaluation_tasks",   # Milestone 3
        # "app.tasks.notification_tasks", # Milestone 4
    ],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Retry policy defaults
    task_acks_late=True,           # Acknowledge AFTER completion, not on receipt
    task_reject_on_worker_lost=True,
    # Result expiry — keep task results for 1 hour
    result_expires=3600,
    # Routing — all tasks go to the "default" queue for now
    task_default_queue="default",
)
