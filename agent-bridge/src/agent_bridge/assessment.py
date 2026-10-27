"""One classifier and one home for stall/slow thresholds, independent of renderers."""

from .status_model import Assessment

SILENCE_SECONDS = 15 * 60
COMMAND_GRACE_SECONDS = 10 * 60
WAIT_GRACE_FACTOR = 1.25
MAX_DECLARED_WAIT_SECONDS = 2 * 60 * 60
DEFAULT_DECLARED_WAIT_SECONDS = 20 * 60
BUSY_WINDOW = 60
BUSY_CPU = 3.0
BUSY_BYTES = 16 * 1024
BUSY_STALL_FACTOR = 3
PACE_RECENT, PACE_BASELINE = 5, 10
PACE_SLOW, PACE_FLOOR = 5, 60


def assess(state, reason, quiet, threshold=SILENCE_SECONDS, working=False, steps=None,
           *, waiting=None, in_flight=None, now=0, declared_at=None, peer_running=False,
           critical=False, reported=()):
    """Wait deadlines use wall-clock age, never the watch's observation warmup."""
    limit = threshold * (BUSY_STALL_FACTOR if working else 1)
    if state != "running":
        return Assessment(
            "known" if state in {"waiting_for_heavy", "paused", "retrying", "blocked_on_question",
                                 "waiting_for_root"} else "inactive", reason, quiet, limit)
    if critical:
        return Assessment("known", "unacknowledged failure, question or urgent message", quiet, limit)
    # An explicit declaration bounds even a native command containing that declaration.
    wait_age = max(0, int(now - declared_at)) if waiting and declared_at is not None else None
    if wait_age is not None and wait_age >= waiting.expected_seconds * WAIT_GRACE_FACTOR:
        identifier = f"wait:{waiting.declared_at}"
        return Assessment("overdue-wait", f"overdue waiting on {waiting.peer or waiting.kind}"
                          + (f": {waiting.note}" if waiting.note else ""), quiet, limit,
                          activity_age_seconds=wait_age, waiting_on_job=waiting.peer,
                          notice_id=identifier if identifier not in reported else None)
    if in_flight:
        long = in_flight.age_seconds >= COMMAND_GRACE_SECONDS
        return Assessment("long-command" if long else "known",
                          f"{'long command' if long else 'tool in flight'}: {in_flight.kind}",
                          quiet, limit, activity_age_seconds=in_flight.age_seconds,
                          notice_id=in_flight.id if long and in_flight.id not in reported else None)
    if waiting and wait_age is not None:
        return Assessment("known", f"waiting-on {waiting.peer}" if peer_running else
                          f"declared wait on {waiting.peer or waiting.kind}"
                          + (f": {waiting.note}" if waiting.note else ""), quiet, limit,
                          activity_age_seconds=wait_age, waiting_on_job=waiting.peer)
    if quiet >= limit:
        return Assessment("stalled", "processes busy" if working else "silence past threshold", quiet, limit)
    if steps and steps[0] >= max(PACE_FLOOR, PACE_SLOW * steps[1]) and steps[2] >= PACE_RECENT:
        recent, usual = round(steps[0]), round(steps[1])
        return Assessment("slow", f"model steps take {recent}s, usually {usual}s", quiet, limit,
                          recent, usual)
    return Assessment("ok", "processes busy" if working else "within silence threshold", quiet, limit)
