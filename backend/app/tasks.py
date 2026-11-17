"""Background job runner. The API enqueues `run_job(job_id)`; an RQ worker executes it."""
import logging
import traceback

from . import db

log = logging.getLogger("viral.tasks")


class Progress:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def __call__(self, fraction: float | None, message: str):
        log.info("[%s] %s %s", self.job_id, "" if fraction is None else f"{int(fraction * 100)}%", message)
        if fraction is None:
            db.update_job(self.job_id, message=message)
        else:
            db.update_job(self.job_id, progress=max(0.0, min(1.0, fraction)), message=message)


def _pipeline(kind: str):
    if kind == "clips":
        from .pipelines.clips import run
    elif kind == "ugc":
        from .pipelines.ugc import run
    elif kind == "publish":
        from .publish import run
    else:
        raise ValueError(f"Unknown job kind: {kind}")
    return run


def run_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return
    db.update_job(job_id, status="running", progress=0.01, message="Starting…", error=None)
    try:
        output = _pipeline(job["kind"])(job_id, job["input"], Progress(job_id))
        db.update_job(job_id, status="done", progress=1.0, message="Done", output=output)
    except Exception as e:  # surface any failure to the dashboard
        log.exception("Job %s failed", job_id)
        db.update_job(job_id, status="error", message=str(e)[:500], error=traceback.format_exc()[-4000:])
        raise


def enqueue(job_id: str):
    from redis import Redis
    from rq import Queue

    from .config import settings

    q = Queue("viral", connection=Redis.from_url(settings.REDIS_URL))
    q.enqueue(run_job, job_id, job_timeout="4h", result_ttl=3600, failure_ttl=86400)
