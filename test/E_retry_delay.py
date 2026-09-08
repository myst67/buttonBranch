# Waits before retrying a rate-limited call.
#
# delay_min may be bound to a plain number, a numeric string, or - as it is
# now - the whole query_trend_micro_api object. All three are handled: the
# API's own Retry-After is used when it can be found, the input's number when
# it cannot, and exponential backoff when there is neither.
#
# Outputs: waited_seconds, requested_seconds, capped, retry_attempt,
#          next_attempt, source.

import time

MAX_SLEEP = 60   # this action's own ceiling. A longer wait belongs in a
                 # Delay action, not in a script that the sandbox may kill.
MIN_SLEEP = 1
BASE_DELAY = 2


def to_seconds(value):
    """A number from whatever was bound, or None.

    Only a wholly numeric string is accepted. Scraping digits out of arbitrary
    text would turn an HTTP-date into a plausible-looking wrong number, and a
    wrong sleep is worse than falling through to backoff.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            return None
    return None


def from_text(text):
    """Retry-After out of a stringified object.

    A text input stringifies whatever is bound to it, so the headers can
    arrive as "{'Retry-After': 30, ...}" rather than as a dict.
    """
    flat = text.lower()
    for name in ("retry-after", "retry_after", "retryafter"):
        at = flat.find(name)
        if at < 0:
            continue
        digits = ""
        for ch in text[at + len(name):]:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        if digits:
            return float(digits)
    return None


def find_retry_after(node, depth=0):
    """Retry-After anywhere in the response, cased however it arrived."""
    if depth > 6:
        return None
    if isinstance(node, dict):
        for key, value in node.items():
            flat = str(key).replace("-", "").replace("_", "").lower()
            if flat == "retryafter":
                found = to_seconds(value)
                if found is not None:
                    return found
        for value in node.values():
            found = find_retry_after(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, (list, tuple)):
        for value in node:
            found = find_retry_after(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, str):
        return from_text(node)
    return None


raw = action_inputs.get('delay_min')
attempt = int(to_seconds(action_inputs.get('attempt', 0)) or 0)

wait = find_retry_after(raw)
source = 'Retry-After'

if wait is None:
    wait = to_seconds(raw)
    source = 'delay_min'

if wait is None:
    # Nothing to go on. Back off exponentially, with the clock's fractional
    # part as jitter so retries running in parallel do not wake together.
    wait = BASE_DELAY * (2 ** attempt) + (time.time() % 1)
    source = 'backoff'

requested = wait
wait = max(MIN_SLEEP, min(MAX_SLEEP, wait))

time.sleep(wait)

action_outputs['waited_seconds'] = round(wait, 2)
action_outputs['requested_seconds'] = round(requested, 2)
# True means the API asked for longer than this action waited, so the retry
# will very likely be refused again. Branch on it rather than ignoring it.
action_outputs['capped'] = requested > MAX_SLEEP
action_outputs['retry_attempt'] = attempt
action_outputs['next_attempt'] = attempt + 1
action_outputs['source'] = source
