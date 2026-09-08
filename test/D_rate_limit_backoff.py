"""Decide whether to retry a rate-limited HTTP call, and how long to wait.

Turbine's Script action cannot make the HTTP call itself, so the retry has to
live in the playbook graph: HTTP Request -> this script -> Delay -> back to the
HTTP Request. What this script contributes is the arithmetic the graph cannot
do on its own - reading the server's own Retry-After, falling back to
exponential backoff with jitter when it is absent, capping the wait, and
counting attempts so the loop terminates.

Wire it as:

    HTTP Request (continue on error)
        |
    D_rate_limit_backoff        inputs: status_code, headers, attempt
        |
    Condition: should_retry == true
        |  true                     |  false
    Delay (wait_seconds)        carry on, or fail on give_up
        |
    back to HTTP Request

Inputs
------
status_code   int    the HTTP action's response status. Absent or 0 is read as
                     a transport failure, which is retryable.
headers       dict   the response headers, matched case-insensitively.
attempt       int    which attempt just finished. Starts at 1.
max_attempts  int    default 5. The loop's stop condition.
base_delay    num    default 2 seconds, the first backoff step.
max_delay     num    default 300 seconds, the ceiling on any single wait.
                     A Retry-After longer than this gives up rather than
                     retrying early, which would only earn another 429.
retry_on      list   status codes to retry. Defaults to the transient set.
now           num    epoch seconds, for deciding an absolute reset header.
                     Defaults to the clock.
rate_window   num    default 60, the seconds RateLimit-Limit is counted over.
calls_planned int    how many calls the playbook still intends to make. With
                     the quota, it turns into how long that will take.

Outputs
-------
should_retry  bool   true when the caller should wait and call again.
wait_seconds  int    how long to wait before that call.
next_attempt  int    pass back in as ``attempt`` on the retry.
give_up       bool   true when the call failed and no attempts are left.
succeeded     bool   true when the response was a 2xx.
reason        str    one line explaining the decision, for the run log.
wait_source   str    where wait_seconds came from: a header, or backoff.
rate_limit    int    RateLimit-Limit, the calls allowed per window, or null.
rate_remaining int   RateLimit-Remaining, calls left in this window, or null.
pace_seconds  num    how long to wait between calls to stay under the quota:
                     rate_window / rate_limit. Feed it to the Delay action
                     inside the loop that makes the calls.
pace_note     str    one line on what the quota implies for calls_planned.
"""

import random
import time


# Codes worth calling again. 429 is the rate limit; the 5xx entries are the
# transient server-side failures. Everything else - 400, 401, 403, 404, 422 -
# will fail again identically, so retrying only burns the quota further.
DEFAULT_RETRY_ON = [429, 500, 502, 503, 504]

# Headers that carry a wait, in the order they are trusted. Retry-After is the
# standard one and the only one Trend Micro documents for this response; the
# rest are here because gateways in front of an API often add their own.
WAIT_HEADERS = ["retry-after", "ratelimit-reset", "x-ratelimit-reset",
                "x-rate-limit-reset"]

# The quota itself, and how much of it is left. Trend Micro documents
# RateLimit-Limit on the 429 response; a gateway may also send it on a 2xx,
# which is the more useful place because it lets the playbook pace itself
# before it is blocked rather than after.
LIMIT_HEADERS = ["ratelimit-limit", "x-ratelimit-limit", "x-rate-limit-limit"]
REMAINING_HEADERS = ["ratelimit-remaining", "x-ratelimit-remaining",
                     "x-rate-limit-remaining"]

# A reset header holding a number larger than this is an absolute epoch time
# rather than a count of seconds to wait. Roughly a year in seconds: no API
# asks a client to wait longer than that, and no epoch timestamp is smaller.
EPOCH_THRESHOLD = 31536000


# ======================================================================
# Turbine plumbing
# ======================================================================

def get_inputs():
    """Turbine's Script action injects ``action_inputs``; a harness may not."""
    scope = globals()
    if isinstance(scope.get("action_inputs"), dict):
        return scope["action_inputs"]
    if isinstance(scope.get("inputs"), dict):
        return scope["inputs"]
    names = ["status_code", "headers", "attempt", "max_attempts", "base_delay",
             "max_delay", "retry_on", "now", "response"]
    return {name: scope[name] for name in names if name in scope}


def get_input(name, default=None):
    value = get_inputs().get(name, default)
    if value is None or value == "" or value == []:
        return default
    return value


def emit_outputs(result):
    """Publish the result the way Turbine's Script action collects it."""
    scope = globals()
    existing = scope.get("action_outputs")
    if isinstance(existing, dict):
        existing.update(result)
    else:
        scope["action_outputs"] = dict(result)
    scope["outputs"] = result
    scope["result"] = result
    return result


# ======================================================================
# Reading the response
# ======================================================================

def as_int(value, default=None):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def find_header(headers, name):
    """Look a header up without caring how the gateway cased it."""
    if not isinstance(headers, dict):
        return None
    target = name.replace("-", "").replace("_", "").lower()
    for key, value in headers.items():
        if str(key).replace("-", "").replace("_", "").lower() == target:
            return value
    return None


def parse_http_date(value):
    """Seconds until an RFC 7231 date, or None if it is not one.

    Retry-After is allowed to be either a count of seconds or a date, and a
    server may send either. Reading a date as a number would yield None and
    silently fall through to backoff, so it is worth handling.
    """
    try:
        from email.utils import parsedate_to_datetime
    except ImportError:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    try:
        return parsed.timestamp() - time.time()
    except (AttributeError, ValueError, OSError):
        return None


def wait_from_headers(headers, now):
    """The server's own instruction, in seconds, and which header gave it.

    Three shapes are covered: a count of seconds, an absolute epoch time, and
    an HTTP date. A header the server sent always beats a guess, because it is
    the only value that knows when the window actually resets.
    """
    for name in WAIT_HEADERS:
        raw = find_header(headers, name)
        if raw is None or raw == "":
            continue

        seconds = as_int(raw)
        if seconds is not None:
            if seconds > EPOCH_THRESHOLD:
                # An absolute reset time, not a duration.
                return max(0, seconds - now), name
            return max(0, seconds), name

        by_date = parse_http_date(raw)
        if by_date is not None:
            return max(0, int(round(by_date))), name

    return None, None


def leading_int(value):
    """The first integer in a header value.

    RFC 9239 allows a compound form - ``100, 100;w=60`` - so the quota can
    arrive with the window appended. Reading only the leading number keeps
    both the bare and the compound shapes working.
    """
    digits = ""
    for ch in str(value).strip():
        if ch.isdigit():
            digits += ch
        elif digits:
            break
        elif ch not in "+ ":
            break
    return int(digits) if digits else None


def first_header_int(headers, names):
    for name in names:
        raw = find_header(headers, name)
        if raw is None or raw == "":
            continue
        found = leading_int(raw)
        if found is not None:
            return found
    return None


def pacing(headers, window, calls_planned):
    """Turn the quota into a delay to put between calls.

    RateLimit-Limit answers a different question from Retry-After. Retry-After
    says when this blocked call may be repeated; the quota says how fast the
    playbook is allowed to go in the first place. Spacing calls evenly at
    window/limit keeps it under the ceiling instead of bursting into it and
    then waiting, which is what produced the 429.
    """
    limit = first_header_int(headers, LIMIT_HEADERS)
    remaining = first_header_int(headers, REMAINING_HEADERS)

    if not limit or limit <= 0:
        return {"rate_limit": limit, "rate_remaining": remaining,
                "pace_seconds": None,
                "pace_note": "No RateLimit-Limit header on this response. Check "
                             "a successful call's headers; if the quota is only "
                             "sent on a 429, read it once and pass it in."}

    pace = round(float(window) / limit, 3)
    note = "{} calls per {}s, so {}s between calls.".format(limit, window, pace)
    if calls_planned:
        minutes = round(calls_planned * pace / 60.0, 1)
        note += (" {} planned calls need about {} minute(s) at that pace"
                 .format(calls_planned, minutes))
        if calls_planned > limit:
            note += (", and exceed the quota in a single window: batch them or "
                     "spread the run.")
        else:
            note += "."
    if remaining is not None:
        note += " {} left in the current window.".format(remaining)
    return {"rate_limit": limit, "rate_remaining": remaining,
            "pace_seconds": pace, "pace_note": note}


def backoff(attempt, base_delay, max_delay):
    """Exponential backoff with full jitter.

    Jitter matters more than the exponent here. Several playbooks that hit the
    same rate limit and back off by a fixed schedule wake up together and
    collide again; spreading each wait over the whole window breaks that up.
    """
    window = min(max_delay, base_delay * (2 ** max(0, attempt - 1)))
    return int(round(random.uniform(base_delay, max(base_delay, window))))


# ======================================================================
# The decision
# ======================================================================

def decide():
    headers = get_input("headers") or {}
    response = get_input("response")
    # The HTTP action may hand over the whole response rather than its parts.
    if isinstance(response, dict):
        if not headers:
            headers = response.get("headers") or {}
        if get_input("status_code") is None:
            status = as_int(response.get("status_code"), 0)
        else:
            status = as_int(get_input("status_code"), 0)
    else:
        status = as_int(get_input("status_code"), 0)

    attempt = as_int(get_input("attempt", 1), 1)
    max_attempts = as_int(get_input("max_attempts", 5), 5)
    base_delay = as_int(get_input("base_delay", 2), 2)
    max_delay = as_int(get_input("max_delay", 300), 300)
    retry_on = get_input("retry_on") or DEFAULT_RETRY_ON
    retry_on = [as_int(code) for code in retry_on if as_int(code) is not None]
    now = as_int(get_input("now"), int(time.time()))

    window = as_int(get_input("rate_window", 60), 60)
    calls_planned = as_int(get_input("calls_planned"), 0)

    base = {"status_code": status, "attempt": attempt,
            "next_attempt": attempt + 1, "wait_seconds": 0,
            "should_retry": False, "give_up": False, "succeeded": False,
            "wait_source": None}
    # The quota is read from every response, not only the failures, so a
    # successful call still tells the playbook how fast it may go.
    base.update(pacing(headers, window, calls_planned))

    if 200 <= status < 300:
        base.update(succeeded=True, next_attempt=attempt,
                    reason="{} succeeded on attempt {}.".format(status, attempt))
        return base

    # A missing status means the request never reached the API - a timeout or a
    # dropped connection. That is transient, so it is treated like a 5xx.
    transient = status in retry_on or status == 0

    if not transient:
        base.update(give_up=True, next_attempt=attempt,
                    reason="{} is not retryable: the same call will fail the "
                           "same way. Fix the request or the credentials."
                           .format(status))
        return base

    if attempt >= max_attempts:
        base.update(give_up=True, next_attempt=attempt,
                    reason="{} after {} of {} attempts. Out of retries."
                           .format(status, attempt, max_attempts))
        return base

    header_wait, source = wait_from_headers(headers, now)
    if header_wait is not None:
        # Waiting less than the server asked for is not a shorter retry, it is
        # a guaranteed second 429. When its window is longer than this action
        # is allowed to sit, the honest answer is to stop and let the playbook
        # reschedule rather than to spend the remaining attempts early.
        if header_wait > max_delay:
            base.update(give_up=True, next_attempt=attempt, wait_seconds=header_wait,
                        wait_source=source,
                        reason="{} on attempt {}. The API asked for {}s via {}, "
                               "longer than the {}s limit on a single wait. "
                               "Retrying sooner would fail again: reschedule "
                               "the run instead.".format(status, attempt,
                                                         header_wait, source,
                                                         max_delay))
            return base
        wait = header_wait
        reason = ("{} on attempt {}. The API asked for {}s via {}."
                  .format(status, attempt, header_wait, source))
    else:
        wait = backoff(attempt, base_delay, max_delay)
        source = "backoff"
        reason = ("{} on attempt {}. No wait header, backing off {}s."
                  .format(status, attempt, wait))

    base.update(should_retry=True, wait_seconds=wait, wait_source=source,
                reason=reason)
    return base


def main(_context=None):
    return decide()


script = main
run = main
execute = main
handler = main


def run_on_import(entry):
    try:
        return emit_outputs(entry())
    except Exception as error:  # never fail silently
        message = "{}: {}".format(type(error).__name__, error)
        scope = globals()
        existing = scope.get("action_error")
        if isinstance(existing, dict):
            existing["message"] = message
        else:
            scope["action_error"] = {"message": message}
        # A crash here must not strand the playbook in its retry loop, so the
        # safe answer is to stop retrying rather than to spin.
        return emit_outputs({"should_retry": False, "give_up": True,
                             "wait_seconds": 0, "reason": message})


run_on_import(main)
