import logging

from apps.agentic.analysis.analysis import run_case_analysis
from apps.agentic.services.cases import (
    claim_pending_case_analysis_job,
    complete_case_analysis_job,
    fail_case_analysis_job,
    reap_stale_case_analysis_jobs,
)
from apps.agentic.services.playbooks import (
    claim_pending_playbook_run,
    find_playbook_class,
    mark_playbook_failed,
    mark_playbook_success,
    reap_stale_playbook_runs,
)

logger = logging.getLogger(__name__)


def run_playbook_once(*, scripts_dir=None):
    reap_stale_playbook_runs()
    playbook_run = claim_pending_playbook_run()
    if playbook_run is None:
        return False

    try:
        playbook_class = find_playbook_class(playbook_run.name, scripts_dir=scripts_dir)
        result = playbook_class(playbook_run=playbook_run).run()
    except Exception as exc:
        _record_outcome(mark_playbook_failed, playbook_run, exc, "playbook")
        return True

    # Recorded outside the try: a failure in the success path must not fall through to
    # mark_playbook_failed, which would then raise on a row that is no longer Running.
    _record_outcome(mark_playbook_success, playbook_run, str(result), "playbook")
    return True


def _record_outcome(recorder, job, payload, label):
    """Bookkeeping must never raise: an error here would strand the row in Running."""
    try:
        recorder(job, payload)
    except Exception:
        logger.exception(
            "Failed to record %s outcome; row stays Running until reaped: pk=%s",
            label,
            job.pk,
        )


def run_case_analysis_once():
    reap_stale_case_analysis_jobs()
    job = claim_pending_case_analysis_job()
    if job is None:
        return False

    try:
        result = run_case_analysis(case=job.case, trigger=job.trigger, source=job)
    except Exception as exc:
        _record_outcome(fail_case_analysis_job, job, str(exc), "case analysis")
        return True

    _record_outcome(
        lambda target, payload: complete_case_analysis_job(target, result_json=payload),
        job,
        result.analysis_record,
        "case analysis",
    )
    return True
