import structlog

from app.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(bind=True, max_retries=0)
def run_real_eval_task(self, days: int = 7, sample_size: int = 100):
    """Celery 任务：对最近真实查询日志执行自动评估。"""
    import asyncio

    from eval.real_eval import run_real_eval

    task_id = self.request.id or "real-eval-local"
    logger.info("real_eval_task_started", task_id=task_id, days=days, sample_size=sample_size)
    try:
        report = asyncio.run(run_real_eval(days=days, sample_size=sample_size))
        logger.info(
            "real_eval_task_completed",
            task_id=task_id,
            sampled=report.get("sampled"),
            evaluated=report.get("evaluated"),
            summary=report.get("summary"),
        )
        return report
    except Exception as exc:
        logger.error("real_eval_task_failed", task_id=task_id, error=str(exc))
        raise
