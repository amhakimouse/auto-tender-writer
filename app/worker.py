"""
app/worker.py

Celery application instance for background task processing.

Why Celery?
  LLM calls take 2-30 seconds. If called synchronously in a FastAPI handler,
  the HTTP response hangs and eventually times out.
  Instead, routers enqueue a Celery task and immediately return HTTP 202 Accepted
  with a task_id. The client polls GET /tasks/{task_id}/status.

Architecture Rules:
  - Tasks call service functions — they NEVER touch the DB or LLM directly.
  - All DB mutations go through the service layer (which logs to audit_logger).
  - Tasks are idempotent: re-running a failed task must be safe.
  - Every task result is stored in Redis for 1 hour (result_expires).

Queue Strategy:
  - "default"  → general LLM processing tasks
  - "priority" → future: high-urgency re-evaluations, committee deadlines
"""

from celery import Celery

from app.core.config import settings

# Create the Celery app, pointed at Redis as both broker and result backend
celery_app = Celery(
    "auto_tender_writer",
    broker=settings.REDIS_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.evaluation_tasks",    # Phase 2-5: compliance, technical, financial, combined
        "app.tasks.notification_tasks",  # Phase 7-8: award/rejection letters, appeal acks
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
    # Retry policy: acknowledge AFTER task completes, not on receipt
    # This ensures tasks are not lost if a worker crashes mid-execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result expiry — keep task results for 1 hour
    result_expires=3600,
    # Routing
    task_default_queue="default",
    task_routes={
        "app.tasks.evaluation_tasks.*": {"queue": "default"},
        "app.tasks.notification_tasks.*": {"queue": "default"},
    },
    # Retry defaults for transient LLM failures
    task_max_retries=3,
    task_default_retry_delay=30,  # seconds between retries
)
