"""SentinelOne unified alerts -> Swimlane 10.x case management records.

Two modes, set by DISCOVERY below.

  DISCOVERY = True   Calls the API, prints exactly what came back, and writes
                     nothing. Run this first: it answers "what data am I
                     actually getting" and prints the app's field names beside
                     the alert's keys so the mapping can be filled in from
                     evidence rather than guessed.

  DISCOVERY = False  Normal run: creates a record for a new alert, updates the
                     record for one already stored, and reports a count of
                     each at the end.

Inputs expected on the task
---------------------------
swimlane_user, swimlane_pwd, sentinelone_api_token   (required)
s1_console_url    e.g. "https://xyz.sentinelone.net"  (required)
app_name          overrides APP_NAME below           (optional)
lookback_hours    default 2                          (optional)
page_size         default 100, max 1000              (optional)
max_pages         default 10, a stop on runaway paging (optional)
"""

import json
import time
from datetime import datetime, timedelta, timezone

import requests
from swimlane import Swimlane
from swimlane.core.search import EQ

# ======================================================================
# Settings
# ======================================================================

#: True inspects and prints; False writes records. Start with True.
DISCOVERY = False

#: The Swimlane application alerts are stored in. Pass app_name as an input to
#: override it, so the same script can serve dev and prod without an edit.
APP_NAME = "Test | SentinelOne Case Management Application"

#: The field on the application holding the SentinelOne alert id. This is the
#: key the script de-duplicates on, so it must be unique per alert.
KEY_FIELD = "Alert ID"

#: A multi-line field on the application to hold the whole alert, formatted.
#: Everything the API returned is stored, including the fields FIELD_MAP does
#: not break out, so nothing is lost even where no column exists for it.
#: Set to None to store nothing.
DETAILS_FIELD = "ssa.sentinelone-siem-alert-details"

#: How to render it: "json" indented, "paths" as one a.b.c = value per line,
#: or "both" with the paths first and the JSON after.
DETAILS_FORMAT = "both"

#: Swimlane text fields have a size limit and a very long alert can exceed it.
#: The text is cut at this length with a line saying so, rather than the write
#: failing and losing the record.
DETAILS_MAX_CHARS = 30000

#: Alert key -> Swimlane field. The right side is either a display name, a
#: field key, or a tuple of candidates tried in order - the first one the
#: application actually has wins. Candidates exist because a field is
#: addressable by display name but is usually referred to by its key, and
#: getting it wrong writes nothing and raises nothing.
#:
#: An unmapped alert key is ignored rather than crashing the run. Discovery
#: prints both names for every field, which is what to fill this in from.
FIELD_MAP = {
    "id": "Alert ID",
    "name": "Alert_Name",
    "description": "Alert_Description",
    "status": ("alert-status", "Alert Status"),
    "severity": ("alert-severity", "Alert Severity"),
    "classification": ("alert-classification", "Alert Classification"),
    "confidenceLevel": ("confidence-level", "Confidence Level"),
    "externalId": "External ID",
    "storylineId": "StoryLine ID",
    "attackSurfaces": "Attack Surfaces",
    "dataSources": "Data Sources",
    "detectedAt": "Detected At",
    "createdAt": "Created At",
    "updatedAt": "Updated At",
    "fileName": "File_Name",
    "fileHash": "File Hash",
    "filePath": "File Path",
    "ticketId": "Ticket ID",
    # Commented out in the original because a null timestamp crashed the run.
    # to_datetime() returns None for those now, so they can come back.
    "firstSeenAt": "First Seen At",
    "lastSeenAt": "Last Seen At",
    "noteExists": "Note Exists",
    "detectionProduct": "Detection Product",
    "detectionVendor": "Detection Vendor",

    # Who the console has the alert assigned to. assignee is a nested object,
    # so these come from flatten rather than from the top level - the email is
    # under assignee.email, not an assigneeEmail field on the alert.
    "assigneeEmail": ("na.offense-assigned-to", "Offense Assigned To",
                      "offense-assigned-to"),
    "assigneeName": ("Assignee Name", "assignee-name"),
    "assigneeId": ("Assignee Id", "Assignee ID", "assignee-id"),
    "assetId": ("Asset Id", "Asset ID", "asset-id"),
    "assetName": ("Asset Name", "asset-name"),
    "assetCategory": ("Asset Category", "asset-category"),
    "assetType": ("Asset Type", "asset-type"),
    "assetOsType": ("Asset Os Type", "Asset OS Type", "asset-os-type"),
    "assetStatus": ("Asset Status", "asset-status"),

    # Clock fields. The two timestamps go in as datetimes; the durations are
    # numbers in DURATION_UNIT.
    "detectionTime": ("Detection Time", "detection-time"),
    "openedTime": ("Opened Time", "opened-time"),
    "resolvedTime": ("Resolved Time", "resolved-time"),
    "timeToDetect": ("Time To Detect", "time-to-detect"),
    "timeToRespond": ("Time To Respond", "time-to-respond"),
    "timeToResolve": ("Time To Resolve", "time-to-resolve"),
    "slaRespondMinutes": ("SLA Time Respond", "sla-time-respond"),
    "slaResolveMinutes": ("SLA Time Resolve", "sla-time-resolve"),
    "sevTag": ("Sev Tag", "sev-tag"),
    "rbpMax": ("rbp-max", "RBP Max", "Rbp Max"),
    # The console's severity again, for a dropdown rather than a text field.
    # Three fields carry the same fact in different shapes: severity as the
    # console sends it, sevTag and severityDropdown as options. They are kept
    # separate because a text field and a dropdown want different spellings,
    # and a tenant may have any one of the three.
    "severityDropdown": ("severity-dropdown", "Severity Dropdown",
                         "Severity DropDown"),
    "tiTag": ("Ti Tag", "TI Tag", "ti-tag"),
    "tiType": ("Ti Type", "TI Type", "ti-type"),

    # Verdict and outcome, which drive the tags above and are worth storing
    # in their own right.
    "result": ("Result", "result"),
    "analystVerdict": ("Analyst Verdict", "analyst-verdict"),
}

if DETAILS_FIELD:
    # Keyed on a name no SentinelOne field uses, so it cannot collide with one.
    FIELD_MAP["_details"] = DETAILS_FIELD

#: Sent to SentinelOne so informational alerts are never fetched at all - no
#: bandwidth, no page spent on them, no record. The operator name has to match
#: your console's FilterInput; discovery prints what it accepts, and the three
#: shapes below are the usual ones. Set to None to filter client-side only.
#:
#:   {"fieldId": "severity", "stringNotIn": {"values": ["INFO"]}}
#:   {"fieldId": "severity", "stringNotEqual": {"value": "INFO"}}
#:   {"fieldId": "severity", "stringIn": {"values": ["LOW","MEDIUM","HIGH","CRITICAL"]}}
#:
#: A rejected filter is detected on the first call and dropped, so a wrong
#: guess costs one retry rather than the run - EXCLUDE_SEVERITIES below still
#: catches the alerts either way.
#:
#: stringEqual is the shape this console is known to accept; it is what the
#: HIGH-only filter used. An exclusion needs a different operator, and which
#: one this console has is not yet known - so the guess below falls back
#: cleanly and the client-side exclusion does the work regardless.
SEVERITY_FILTER = {"fieldId": "severity", "stringNotEqual": {"value": "INFO"}}

#: Keep ONLY these severities, matched case-insensitively. An allow-list,
#: because a severity the console adds later slips through a deny-list.
#: Empty, as here, falls back to EXCLUDE_SEVERITIES.
#:
#: To go back to high only:  ONLY_SEVERITIES = {"high"}
#: High and above:           ONLY_SEVERITIES = {"high", "critical"}
ONLY_SEVERITIES = set()

#: Severities to drop, used only when ONLY_SEVERITIES is empty. Informational
#: alerts are the bulk of most consoles and each one stored is a Record Create
#: Event, so excluding them is the cheapest filter there is.
EXCLUDE_SEVERITIES = {"info", "informational"}

#: Statuses to drop, same treatment. Empty by default.
EXCLUDE_STATUSES = set()

#: Print the first response body exactly as SentinelOne sent it, before any
#: parsing or flattening. This is the only view that shows what the API really
#: returned rather than what this script made of it.
RAW_RESPONSE = True

#: How much of a raw dump to print. The task log truncates eventually; raise
#: this if an alert is cut off mid-object.
RAW_CHARS = 20000

#: How many "a.b.c = value" lines to print from the response. One alert with
#: every nested object expanded runs to a few hundred.
RAW_LINES = 400

#: SLA targets in minutes, by severity, lowercased. These are policy: nothing
#: in a SentinelOne alert says what your targets are, so they are declared
#: here and the clock is measured against them.
SLA_MINUTES = {
    "critical": {"respond": 15, "resolve": 240},
    "high": {"respond": 30, "resolve": 480},
    "medium": {"respond": 120, "resolve": 1440},
    "low": {"respond": 480, "resolve": 4320},
    "info": {"respond": None, "resolve": None},
}

#: severity -> Sev Tag. This is a SELECTION field on the application, and a
#: selection field ignores anything that is not already one of its options -
#: no error, no value. So these must match the dropdown's entries exactly,
#: including their casing. The ones below mirror what the field displays;
#: change them if your options are named differently.
SEVERITY_TAGS = {
    "critical": "Critical", "high": "High", "medium": "Medium",
    "low": "Low", "info": "Info",
}

#: severity -> rbp-max, the numeric weight of the severity. This is the field
#: a dashboard sums or averages, so the scale matters more than the numbers:
#:
#:   - 0 to 100, because an average over a mixed queue reads directly as a
#:     percentage of worst case, and there is room between bands to insert one
#:     later without renumbering.
#:   - info is 0, not 1. An informational alert carries no risk, and a nonzero
#:     floor means a quiet day of nothing but info still shows a score.
#:   - the gaps widen towards the top rather than being evenly spaced, so one
#:     critical outweighs two mediums in a sum. Evenly spaced weights make a
#:     queue of mediums look like an emergency.
#:
#: For a 0-10 scale instead, use {critical: 10, high: 7, medium: 4, low: 1,
#: info: 0}; nothing else needs changing. A severity not listed here leaves
#: the field empty rather than scoring 0, so an unrecognised severity is
#: visible as a gap instead of looking like a harmless alert.
SEVERITY_WEIGHTS = {
    "critical": 100,
    "high": 70,
    "medium": 40,
    "low": 10,
    "info": 0,
    "informational": 0,
}

#: SentinelOne's verdict -> ti-tag, also a selection field. result is BENIGN
#: on a resolved false positive; analystVerdict carries the analyst's own call
#: where one was made, and is preferred when both exist.
TI_TAGS = {
    "benign": "Benign",
    "false_positive": "Benign",
    "suspicious": "Suspicious",
    "true_positive": "Malicious",
    "malicious": "Malicious",
    "undefined": None,
}

#: ti-type is the source this record came from - constant for every alert this
#: script writes. Set to None to leave the field alone.
TI_TYPE = "SentinelOne SIEM"

#: Values for SELECTION fields, which ignore anything that is not already one
#: of their options - no error, no value. Keyed by the flattened alert key,
#: then by the console's value lowercased, giving the option to write.
#:
#: A value not listed here is passed through unchanged, so an unexpected status
#: either matches an option or shows up in the "stored nothing" report rather
#: than disappearing. Add a dropdown by adding its key: nothing else changes.
SELECTION_VALUES = {
    # This tenant's dropdown is exactly: New, In Progress, On Hold, Closed.
    # SentinelOne has no On Hold - that is an analyst state, set in Swimlane
    # and never sent by the console - so nothing maps onto it and a record
    # sitting On Hold is left alone by ON_HOLD_IS_STICKY below.
    # RESOLVED and MITIGATED both mean the console is finished with the alert,
    # which is what Closed means here.
    "status": {
        "new": "New",
        "unresolved": "New",
        "in_progress": "In Progress",
        "inprogress": "In Progress",
        "resolved": "Closed",
        "closed": "Closed",
        "mitigated": "Closed",
    },
    "analystVerdict": {
        "undefined": None,
        "true_positive": "True Positive",
        "false_positive": "False Positive",
        "suspicious": "Suspicious",
        "benign": "Benign",
    },
    "classification": {
        "unknown": None,
        "manual": "Manual",
        "malware": "Malware",
        "ransomware": "Ransomware",
        "pua": "PUA",
    },
    "confidenceLevel": {
        "suspicious": "Suspicious",
        "malicious": "Malicious",
    },
    "result": {
        "benign": "Benign",
        "malicious": "Malicious",
        "mitigated": "Mitigated",
        "undefined": None,
    },
    # Critical, High, Medium and Low differ from the console's CRITICAL, HIGH,
    # MEDIUM and LOW only in spelling, so they are matched against the
    # dropdown's own options and need no entries here. INFO is a different
    # word from Informational, which no amount of normalising will bridge, so
    # it is the one entry this dropdown needs.
    "severityDropdown": {
        "info": "Informational",
        "informational": "Informational",
    },
}

#: Source values seen that SELECTION_VALUES does not name, reported once at
#: the end so the dropdown can be extended rather than quietly missing them.
UNMAPPED_SELECTIONS = {}

#: When a field's options cannot be read from the application, a dropdown
#: value has to be guessed at. SCREAMING_SNAKE is how SentinelOne writes
#: these and is almost never how a Swimlane dropdown displays them, so the
#: console's value is retitled - CRITICAL becomes Critical, IN_PROGRESS
#: becomes In Progress - rather than being sent as it arrived. It is a guess,
#: so it is reported, and it is only ever used where nothing better exists:
#: a field whose options were read is matched against them instead.
#:
#: Set False to send the console's wording unchanged.
TITLE_CASE_UNKNOWN_OPTIONS = True

#: field -> "console value -> guess", for each value retitled this way.
RETITLED = {}

#: alert key -> the option to use when nothing else matches, including when
#: the alert carries no value at all. This is for a dropdown that has an
#: option for exactly that case: a severity dropdown offering Unknown means an
#: unplaceable severity belongs in Unknown, not in an empty field, because an
#: empty dropdown disappears from a report's grouping while Unknown is a row
#: that can be seen and chased.
#:
#: Used only after the table and the spelling match have both failed, and only
#: when the fallback is itself one of the field's options. Every use is
#: reported, so a severity the console started sending is still visible rather
#: than being quietly swept into Unknown.
SELECTION_FALLBACK = {
    "severityDropdown": "Unknown",
}

#: field -> "value -> fallback" for each use of SELECTION_FALLBACK.
FELL_BACK = {}

#: Alert keys whose field is cleared when the console sends nothing, rather
#: than keeping what it last held. Everywhere else an empty value means "no
#: news, leave the field alone", which is right for a timestamp or a hash: it
#: never changes once set. An assignee does change. An alert handed back to
#: the queue arrives with assignee null, and a field that only ever gets
#: written would go on naming the previous owner - so the stale value is worse
#: than an empty one, and work gets sent to someone who no longer has it.
#:
#: Only applied to a record that already exists; a new record simply has
#: nothing to clear. Remove a key to have that field keep its last value.
CLEAR_WHEN_EMPTY = {"assigneeEmail", "assigneeName", "assigneeId"}

#: Dropdown options that belong to the analyst, not to SentinelOne. A record
#: already showing one of these keeps it: the console knows nothing about On
#: Hold and would otherwise push the record back to New on the next sync,
#: undoing the triage every ten minutes. Keyed by alert key -> options.
ANALYST_OWNED = {
    "status": {"on hold"},
}

#: Stamp a response time when a sync first sees an alert that has been acted
#: on, having previously seen it untouched.
#:
#: SentinelOne records that an analyst acted - analystVerdict leaves UNDEFINED,
#: status leaves NEW, a note appears - but never when. The only honest reading
#: available here is "between the previous sync and this one", so the figure is
#: accurate to the interval this script runs on: hourly runs give hourly
#: resolution. A tighter number has to come from the Swimlane record's own
#: status change, or from the first note's timestamp via the notes API.
#:
#: Nothing is stamped for an alert that already shows a response the first
#: time it is seen: the response happened before this script was watching, and
#: an invented duration is worse than an empty field.
DETECT_RESPONSE_ON_SYNC = True

#: Values meaning "nobody has acted yet". Anything else counts as a response.
UNTOUCHED_VERDICTS = {"undefined", "", "none"}
UNTOUCHED_STATUSES = {"new", "", "none"}

#: How a duration is written: "minutes", "seconds" or "milliseconds".
#: A Swimlane time-span field stores milliseconds; a numeric or text field is
#: easier to read in minutes. Match this to the field type you created - a
#: time-span field handed 0.51 rounds it to nothing and shows blank.
DURATION_UNIT = "minutes"

#: (start, end) for time to detect. firstSeenAt is when the activity began and
#: detectedAt is when it was caught, which is the usual definition - but
#: firstSeenAt is null on a good share of alerts, and the gap is then
#: unmeasurable rather than zero.
#:
#: ("detectedAt", "createdAt") measures console ingest lag instead: always
#: available, but a different thing. Choose deliberately.
TIME_TO_DETECT_FROM = ("firstSeenAt", "detectedAt")

#: (start, end) for time to respond, or None to leave it empty.
#:
#: There is no analyst-action timestamp in an alert. analystVerdict moves from
#: UNDEFINED without recording when, so the honest answer is None and the gap
#: has to be measured from the Swimlane record's own state changes instead.
#:
#: ("createdAt", "updatedAt") is available and tempting, and on a resolved
#: alert updatedAt lands a second before resolvedAt - it tracks the last edit
#: of any kind, automated ones included, so it measures time to resolve with
#: extra steps rather than time to respond.
TIME_TO_RESPOND_FROM = None

#: Where a value really lives when the obvious key is null. The first entry
#: that holds something wins, so the mapped field gets the value wherever the
#: console happens to put it.
#:
#: fileName and fileHash exist at the top level of an alert but come back null
#: on this tenant - the file is described under process.file instead, which is
#: what the flattener reads into the process* keys.
FALLBACKS = {
    "fileName": ("fileName", "processFileName"),
    "fileHash": ("fileHash", "processSha256", "processSha1", "processMd5"),
    "filePath": ("processFilePath",),
}

#: Keys whose value is an ISO timestamp and must reach Swimlane as a datetime.
DATE_KEYS = {"detectedAt", "createdAt", "updatedAt", "firstSeenAt", "lastSeenAt",
             "detectionTime", "openedTime", "resolvedTime"}

#: Build the query from the schema the console actually exposes, rather than
#: from a fixed list. GraphQL rejects the whole query when one field is
#: undefined and names only the first, so a hand-written selection costs a
#: round trip per missing field. Set False to use STATIC_QUERY_FIELDS below.
AUTO_QUERY = True

#: How deep to follow object fields when building the selection. 2 covers
#: assets, detectionSource, process.file and the rest; deeper risks a very
#: large response for little gain.
AUTO_QUERY_DEPTH = 2

#: Used only when AUTO_QUERY is False, or introspection is not permitted.
STATIC_QUERY_FIELDS = """
  id name description status severity analystVerdict classification
  confidenceLevel externalId storylineId detectedAt createdAt updatedAt
  firstSeenAt lastSeenAt noteExists fileHash fileName ticketId
  assets { id name osType status category type agentUuid agentVersion }
  detectionSource { engine product vendor }
  assignee { userId fullName email }
"""

#: Status codes worth calling again. 429 is the rate limit; the 5xx entries are
#: transient. A 4xx other than 429 will fail again identically.
RETRY_ON = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BASE_DELAY = 2
MAX_DELAY = 60


# ======================================================================
# Inputs
# ======================================================================

def _input(name, default=None, required=False):
    value = sw_context.inputs.get(name, default)
    if value in (None, "", []):
        if required:
            raise ValueError(
                "Input '{}' is required but was empty. Add it to the task's "
                "inputs and bind it.".format(name))
        return default
    return value


swimlane_user = _input("swimlane_user", required=True)
swimlane_pwd = _input("swimlane_pwd", required=True)
api_token = _input("sentinelone_api_token", required=True)
console_url = str(_input("s1_console_url", required=True)).rstrip("/")

app_name = _input("app_name", APP_NAME)
lookback_hours = int(_input("lookback_hours", 2))
page_size = min(int(_input("page_size", 100)), 1000)
max_pages = int(_input("max_pages", 10))

API_URL = "{}/web/api/v2.1/unifiedalerts/graphql".format(console_url)

# Printed every run. A 404 here is almost always the URL rather than the
# token, and the only way to tell is to see the one that was actually called -
# a base URL that already carries the path doubles it.
print("POST {}".format(API_URL))
if API_URL.count("/web/api/") > 1:
    raise ValueError(
        "The API path appears twice in {!r}. s1_console_url takes the console's "
        "base address only, e.g. https://your-tenant.sentinelone.net - the path "
        "is appended for you.".format(API_URL))

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": "ApiToken {}".format(api_token),
}

# One window, used by the filter. The original script computed both a 24-hour
# window and a separate 2-hour cutoff and then filtered on the 24-hour one, so
# the comment and the behaviour disagreed. One value now decides it.
end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(hours=lookback_hours)
start_ms = int(start_time.timestamp() * 1000)
end_ms = int(end_time.timestamp() * 1000)


# ======================================================================
# The query
# ======================================================================

def build_query(node_fields):
    """The listAlerts query, around whatever selection the schema allows."""
    return """
query listAlerts($filters: [FilterInput!], $sortBy: String!, $sortOrder: SortOrderType!,
                 $first: Int, $after: String) {
  alerts(filters: $filters, sort: {by: $sortBy, order: $sortOrder},
         first: $first, after: $after) {
    totalCount
    pageInfo { hasNextPage endCursor }
    edges { cursor node { %s } }
  }
}
""" % node_fields


INTROSPECT = """
query IntrospectType($name: String!) {
  __type(name: $name) {
    name
    fields {
      name
      args { name type { kind name ofType { kind name } } }
      type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
    }
  }
}
"""


def base_type(node):
    """Unwrap NON_NULL and LIST to the kind and name underneath."""
    kind, name = None, None
    while isinstance(node, dict):
        kind, name = node.get("kind"), node.get("name")
        if kind in ("NON_NULL", "LIST"):
            node = node.get("ofType")
            continue
        break
    return kind, name


def needs_arguments(field):
    """True when a field cannot be selected without supplying an argument."""
    for arg in field.get("args") or []:
        kind, _ = arg.get("type", {}).get("kind"), None
        if arg.get("type", {}).get("kind") == "NON_NULL":
            return True
    return False


_type_cache = {}


def type_fields(name, post):
    if name not in _type_cache:
        payload = post(INTROSPECT, {"name": name})
        info = (payload.get("data") or {}).get("__type") or {}
        _type_cache[name] = info.get("fields") or []
    return _type_cache[name]


def selection_for(type_name, post, depth=0, seen=None):
    """Every selectable field on a type, following objects to AUTO_QUERY_DEPTH.

    Fields requiring an argument are skipped: they cannot be selected bare, and
    guessing an argument is how a query starts returning the wrong thing.
    """
    seen = set(seen or ())
    if type_name in seen:
        return ""
    seen.add(type_name)

    parts = []
    for field in type_fields(type_name, post):
        if needs_arguments(field):
            continue
        kind, name = base_type(field.get("type"))
        if kind in ("SCALAR", "ENUM"):
            parts.append(field["name"])
        elif kind in ("OBJECT", "INTERFACE") and depth < AUTO_QUERY_DEPTH and name:
            inner = selection_for(name, post, depth + 1, seen)
            if inner:
                parts.append("{} {{ {} }}".format(field["name"], inner))
    return " ".join(parts)


#: The raw dump is worth seeing once, not once per page and not for the
#: introspection call that happens first.
_raw_printed = False


def paths(value, prefix=""):
    """Every leaf in a nested structure as "a.b[0].c = value", one per line.

    The task log stores stdout as a JSON string, so a pretty-printed block
    comes back with its newlines and quotes escaped and reads as one long
    line. A flat list of paths survives that: each line is short, and nothing
    in it needs unescaping to be understood.
    """
    if isinstance(value, dict):
        if not value:
            yield "{} = {{}}".format(prefix or "(root)")
        for key in sorted(value):
            child = "{}.{}".format(prefix, key) if prefix else key
            for line in paths(value[key], child):
                yield line
    elif isinstance(value, list):
        if not value:
            yield "{} = []".format(prefix or "(root)")
        for index, item in enumerate(value):
            for line in paths(item, "{}[{}]".format(prefix, index)):
                yield line
    else:
        yield "{} = {!r}".format(prefix or "(root)", value)


def dump_response(text):
    """The response body, printed so it can actually be read in the task log."""
    try:
        parsed = json.loads(text)
    except ValueError:
        print("\n=== raw response body (not JSON) ===")
        print(text[:RAW_CHARS])
        print("=== end ===\n")
        return

    print("\n=== response, field by field ===")
    shown = 0
    for line in paths(parsed):
        print("  " + line)
        shown += 1
        if shown >= RAW_LINES:
            print("  ... stopped at {} lines; raise RAW_LINES".format(RAW_LINES))
            break

    print("\n=== the same response as indented JSON ===")
    pretty = json.dumps(parsed, indent=2, sort_keys=True)
    print(pretty[:RAW_CHARS])
    if len(pretty) > RAW_CHARS:
        print("... truncated at {} of {} characters; raise RAW_CHARS"
              .format(RAW_CHARS, len(pretty)))
    print("=== end response ===\n")


def post_graphql(query, variables):
    """One GraphQL call, retrying the transient failures.

    The original called response.json() straight off the request. A 429 or a
    gateway error returns a body that is not the expected shape - sometimes not
    JSON at all - so the failure surfaced as a confusing parse error rather
    than as the rate limit it was.
    """
    body = {"query": query, "variables": variables}
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(API_URL, headers=HEADERS,
                                     data=json.dumps(body), timeout=60)
        except requests.RequestException as error:
            last_error = "transport: {}".format(error)
            status = 0
        else:
            status = response.status_code
            if 200 <= status < 300:
                global _raw_printed
                if RAW_RESPONSE and not _raw_printed:
                    _raw_printed = True
                    dump_response(response.text)
                try:
                    payload = response.json()
                except ValueError:
                    raise RuntimeError(
                        "{} but the body was not JSON. First 300 characters: {}"
                        .format(status, response.text[:300]))
                # GraphQL reports its own errors inside a 200. A validation
                # error names one undefined field at a time, so say which and
                # point at the setting that stops it recurring.
                if payload.get("errors"):
                    raise RuntimeError(graphql_message(payload["errors"]))
                return payload
            last_error = "{}: {}".format(status, response.text[:300])

        if status not in RETRY_ON and status != 0:
            # 404 against an HTML body means the path is wrong, not the token:
            # the API answers JSON even when it rejects you. Say which it is,
            # rather than listing every possible cause.
            html = "<html" in (last_error or "").lower()
            if status == 404 and html:
                hint = ("Nothing is served at this path. The response is a web "
                        "server's own error page, not the API. Check "
                        "s1_console_url is the console base address with no path, "
                        "and that this tenant exposes "
                        "/web/api/v2.1/unifiedalerts/graphql.")
            elif status in (401, 403):
                hint = ("The path is right but the token was rejected. Check "
                        "sentinelone_api_token and the role behind it.")
            else:
                hint = "Check the token, the console URL and the query."
            raise RuntimeError("POST {} returned {}. {} Body: {}"
                               .format(API_URL, status, hint, (last_error or "")[:300]))

        if attempt == MAX_ATTEMPTS:
            break

        # The server's own Retry-After beats a guess, because it is the only
        # value that knows when the window actually resets.
        wait = BASE_DELAY * (2 ** (attempt - 1))
        if status == 429:
            header = response.headers.get("Retry-After") if status else None
            try:
                wait = max(wait, int(float(header)))
            except (TypeError, ValueError):
                pass
        wait = min(wait, MAX_DELAY)
        print("attempt {}/{} failed ({}); waiting {}s"
              .format(attempt, MAX_ATTEMPTS, last_error, wait))
        time.sleep(wait)

    raise RuntimeError("SentinelOne call failed after {} attempts. Last: {}"
                       .format(MAX_ATTEMPTS, last_error))


def graphql_message(errors):
    """A GraphQL error list, read back as something actionable."""
    lines = []
    for error in errors if isinstance(errors, list) else [errors]:
        message = (error or {}).get("message", str(error))
        lines.append(message)
    text = " | ".join(lines)
    if "FieldUndefined" in text or "is undefined" in text:
        text += ("  --  this field is not on your console's schema. With "
                 "AUTO_QUERY = True the query is built from the schema itself "
                 "and this cannot happen; check that introspection is enabled "
                 "for this token.")
    return "GraphQL errors: {}".format(text)


#: Cleared when the console rejects SEVERITY_FILTER, so the retry and every
#: later page go without it instead of failing the same way repeatedly.
_server_filter = SEVERITY_FILTER


def build_filters():
    """The filters sent with each page."""
    filters = [{
        "fieldId": "createdAt",
        "dateTimeRange": {
            "start": start_ms, "end": end_ms,
            "startInclusive": True, "endInclusive": True,
        },
    }]
    if _server_filter:
        filters.append(_server_filter)
    return filters


def fetch_page(after=None):
    """One page of alerts, with the severity filter applied server-side.

    If the console rejects the filter - the operator differs between versions -
    it is dropped and the page is fetched again without it. The client-side
    EXCLUDE_SEVERITIES check then does the same job a little later.
    """
    global _server_filter

    def call():
        variables = {
            "filters": build_filters(),
            "sortBy": "createdAt",
            "sortOrder": "DESC",
            "first": page_size,
        }
        if after:
            variables["after"] = after
        return post_graphql(QUERY, variables)

    try:
        return call()
    except RuntimeError as error:
        text = str(error)
        rejected = _server_filter and any(
            word in text for word in ("FilterInput", "fieldId", "severity",
                                      "WrongType", "ValidationError",
                                      "Unknown field", "is undefined"))
        if not rejected:
            raise
        print("the console rejected the severity filter ({}); fetching without "
              "it and excluding on this side instead. Set SEVERITY_FILTER to a "
              "shape its FilterInput accepts - discovery prints the list."
              .format(text[:160]))
        _server_filter = None
        return call()


#: Set once by resolve_query() before the first page is fetched.
QUERY = None


def resolve_query():
    """The node selection this console will actually accept.

    Introspection is the only way to know, and it is cheap: one call, cached.
    If the token is not allowed to introspect, fall back to the static list and
    say so, rather than failing before a single alert is read.
    """
    if not AUTO_QUERY:
        print("AUTO_QUERY off: using the static field list.")
        return build_query(STATIC_QUERY_FIELDS)
    global _raw_printed
    try:
        _raw_printed = True          # the schema dump is not what was asked for
        selection = selection_for("UnifiedAlert", post_graphql)
        _raw_printed = not RAW_RESPONSE
    except Exception as error:
        _raw_printed = not RAW_RESPONSE
        print("Could not introspect the schema ({}); falling back to the "
              "static field list. If this run then fails on an undefined "
              "field, remove it from STATIC_QUERY_FIELDS.".format(error))
        return build_query(STATIC_QUERY_FIELDS)
    if not selection:
        print("Introspection returned no fields for UnifiedAlert; falling back "
              "to the static field list.")
        return build_query(STATIC_QUERY_FIELDS)
    print("schema: built the selection from UnifiedAlert itself "
          "({} characters). No field in it can be undefined."
          .format(len(selection)))
    return build_query(selection)


def fetch_alerts():
    """Every alert in the window, following the cursor.

    The original asked for pageInfo and then ignored it, so anything past the
    first 100 alerts was silently dropped.
    """
    nodes, cursor, pages, total = [], None, 0, None

    while pages < max_pages:
        payload = fetch_page(cursor)
        alerts = (payload.get("data") or {}).get("alerts") or {}
        if total is None:
            total = alerts.get("totalCount")
        for edge in alerts.get("edges") or []:
            node = edge.get("node")
            if isinstance(node, (bytes, str)):
                node = json.loads(node.decode("utf-8")
                                  if isinstance(node, bytes) else node)
            if isinstance(node, dict):
                nodes.append(node)
        pages += 1
        info = alerts.get("pageInfo") or {}
        cursor = info.get("endCursor")
        if not info.get("hasNextPage") or not cursor:
            break
    else:
        print("WARNING: stopped at the {}-page limit; raise max_pages if the "
              "window really holds this many alerts.".format(max_pages))

    print("window {} to {} ({}h): API reports {} alert(s), {} fetched over {} page(s)"
          .format(start_time.isoformat(timespec="seconds"),
                  end_time.isoformat(timespec="seconds"),
                  lookback_hours, total, len(nodes), pages))
    return nodes


# ======================================================================
# Flattening
# ======================================================================

def first_of(value):
    """The first entry of a list, or the value itself.

    ``assets`` comes back as a list. The original read ``node.get("asset")``,
    singular, which is not a key the query asks for, so it was always empty and
    every asset field landed null.
    """
    if isinstance(value, list):
        return value[0] if value else {}
    return value or {}


def flatten(node):
    """One alert as a flat dict of scalars, ready for FIELD_MAP."""
    asset = first_of(node.get("assets"))
    source = node.get("detectionSource") or {}
    assignee = node.get("assignee") or {}
    incident = node.get("incident") or {}
    resolve = node.get("resolveData") or {}
    process = node.get("process") or {}
    pfile = (process.get("file") or {}) if isinstance(process, dict) else {}

    # Observed on a live tenant: the alert carries analytics, a detectionTime
    # object holding the account/group/site scope, and primaryIndicatorType.
    # None of these were in the hand-written query.
    analytics = node.get("analytics") or {}
    detection_time = node.get("detectionTime") or {}
    attacker = (detection_time.get("attacker") or {}) if isinstance(detection_time, dict) else {}
    cloud_scope = (attacker.get("scope") or {}) if isinstance(attacker, dict) else {}

    flat = {key: node.get(key) for key in (
        "id", "name", "description", "status", "severity", "analystVerdict",
        "classification", "confidenceLevel", "externalId", "storylineId",
        "attackSurfaces", "dataSources", "labels", "detectedAt", "createdAt",
        "updatedAt", "firstSeenAt", "lastSeenAt", "noteExists", "fileHash",
        "fileName", "exclusionHash", "ticketId", "result", "attackPathExists",
        "availableActionIds", "aiInvestigationStatus", "primaryIndicatorType")}

    flat.update({
        "assetId": asset.get("id"),
        "assetName": asset.get("name"),
        "assetOsType": asset.get("osType"),
        "assetStatus": asset.get("status"),
        "assetCategory": asset.get("category"),
        "assetType": asset.get("type"),
        "agentUuid": asset.get("agentUuid"),
        "agentVersion": asset.get("agentVersion"),
        "detectionEngine": source.get("engine"),
        "detectionProduct": source.get("product"),
        "detectionVendor": source.get("vendor"),
        "assigneeId": assignee.get("userId"),
        "assigneeName": assignee.get("fullName"),
        "assigneeEmail": assignee.get("email"),
        "incidentId": incident.get("id"),
        "incidentName": incident.get("name"),
        "resolvedAt": resolve.get("resolvedAt"),
        "resolvedDuration": resolve.get("resolvedDuration"),
        "processCmdLine": process.get("cmdLine"),
        "processParentName": process.get("parentName"),
        "processFileName": pfile.get("name"),
        "processFilePath": pfile.get("path"),
        "processSha256": pfile.get("sha256"),
        "processSha1": pfile.get("sha1"),
        "processMd5": pfile.get("md5"),
        "processCertSubject": pfile.get("certSubject"),
        # The rule that fired.
        "analyticsCategory": analytics.get("category"),
        "analyticsName": analytics.get("name"),
        "analyticsType": analytics.get("typeValue"),
        "analyticsUid": analytics.get("uid"),
        # Which account, group and site the alert belongs to - the fields a
        # multi-tenant console needs to route an alert to the right queue.
        "accountId": cloud_scope.get("accountId"),
        "accountName": cloud_scope.get("accountName"),
        "groupId": cloud_scope.get("groupId"),
        "groupName": cloud_scope.get("groupName"),
        "siteId": cloud_scope.get("siteId"),
        "siteName": cloud_scope.get("siteName"),
        # Asset detail beyond id and name.
        "assetSubcategory": asset.get("subcategory"),
        "assetTypeClassifier": asset.get("assetTypeClassifier"),
        "assetRole": asset.get("role"),
        "assetOrigin": asset.get("origin"),
        "assetOsVersion": asset.get("osVersion"),
        "assetLastLoggedInUser": asset.get("lastLoggedInUser"),
    })

    # tags sit on the asset, not on the alert - the hand-written query asked
    # for them at the top level, which is the field that failed validation.
    asset_tags = asset.get("tags") if isinstance(asset, dict) else None
    flat["assetTags"] = ", ".join(
        "{}={}".format(t.get("key"), t.get("value"))
        for t in (asset_tags or []) if isinstance(t, dict))

    # Lists of objects are joined rather than dropped, so a text field can hold
    # them and nothing silently disappears.
    flat["tags"] = ", ".join(
        "{}={}".format(t.get("key"), t.get("value"))
        for t in (node.get("tags") or []) if isinstance(t, dict))
    flat["attackPaths"] = ", ".join(
        str(p.get("name")) for p in (node.get("attackPaths") or [])
        if isinstance(p, dict))

    # Resolve the fallbacks last, so they can draw on every key above. The
    # target is always set, even to None: a key that exists only when it has a
    # value is invisible to the discovery listing and raises on direct access.
    for target, sources in FALLBACKS.items():
        if flat.get(target) in (None, "", []):
            flat[target] = next(
                (flat.get(s) for s in sources if flat.get(s) not in (None, "", [])),
                flat.get(target))

    flat.update(timings(node, flat))

    if DETAILS_FIELD:
        flat["_details"] = format_details(node)
    return flat


def format_details(node):
    """The whole alert as text for a multi-line field.

    Stored in full rather than only the mapped fields: the console returns far
    more than the application has columns for, and an analyst reading a record
    should not have to go back to SentinelOne for the rest of it.
    """
    parts = []
    if DETAILS_FORMAT in ("paths", "both"):
        parts.append("\n".join(paths(node)))
    if DETAILS_FORMAT in ("json", "both"):
        if parts:
            parts.append("")
            parts.append("-" * 60)
            parts.append("")
        parts.append(json.dumps(node, indent=2, sort_keys=True, default=str))
    text = "\n".join(parts)
    if len(text) > DETAILS_MAX_CHARS:
        text = (text[:DETAILS_MAX_CHARS]
                + "\n\n... truncated at {} of {} characters "
                  "(raise DETAILS_MAX_CHARS)".format(DETAILS_MAX_CHARS, len(text)))
    return text


def aware(value):
    """A datetime that can be subtracted from another.

    to_datetime returns an aware datetime for a timestamp carrying Z or an
    offset and a naive one otherwise. Subtracting one from the other raises,
    so everything is pulled to UTC before any arithmetic.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def duration(start, end):
    """end - start in DURATION_UNIT, or None if either end is missing.

    A negative result is returned as None rather than as a negative duration:
    clocks between a sensor and a console do drift, and a "time to detect" of
    minus four seconds is noise, not a measurement.
    """
    first, last = aware(to_datetime(start)), aware(to_datetime(end))
    if not first or not last:
        return None
    seconds = (last - first).total_seconds()
    if seconds < 0:
        return None
    if DURATION_UNIT == "seconds":
        return round(seconds, 3)
    if DURATION_UNIT == "milliseconds":
        return int(seconds * 1000)
    return round(seconds / 60.0, 2)


def timings(node, flat):
    """The clock fields, from what the alert actually carries.

    Only three timestamps are available: when the activity was first seen,
    when SentinelOne detected it, and when the alert was created. Time to
    detect falls out of the first two. Time to resolve needs resolveData,
    which is null until somebody resolves the alert.

    Time to respond is deliberately absent. It measures the gap to the first
    analyst action, and nothing in this payload records when that happened -
    analystVerdict changes but carries no timestamp. Computing it from
    updatedAt would measure any edit, including an automated one, and a
    plausible wrong number is worse than an empty field.
    """
    resolve = node.get("resolveData") or {}
    resolved_at = resolve.get("resolvedAt")
    severity = str(flat.get("severity") or "").strip().lower()
    sla = SLA_MINUTES.get(severity) or {}
    # The console's own SLA block. Null on every alert seen so far, but if it
    # ever populates it beats anything computed here, so it is carried through
    # rather than ignored.
    slo = node.get("sloDetails") or {}

    values = {
        "detectionTime": flat.get("detectedAt"),
        "openedTime": flat.get("createdAt"),
        "resolvedTime": resolved_at,
        # first seen -> detected: how long the activity ran before it was caught
        "timeToDetect": duration(flat.get(TIME_TO_DETECT_FROM[0]),
                                 flat.get(TIME_TO_DETECT_FROM[1])),
        # Empty unless TIME_TO_RESPOND_FROM names a pair. See the setting.
        "timeToRespond": (duration(flat.get(TIME_TO_RESPOND_FROM[0]),
                                   flat.get(TIME_TO_RESPOND_FROM[1]))
                          if TIME_TO_RESPOND_FROM else None),
        # created -> resolved: the whole case, end to end
        "timeToResolve": duration(flat.get("createdAt"), resolved_at),
        "slaRespondMinutes": sla.get("respond"),
        "slaResolveMinutes": sla.get("resolve"),
        "sevTag": SEVERITY_TAGS.get(severity),
        # Passed through as the console sends it. for_selection matches it
        # against the dropdown's own options, so no table is needed unless
        # this tenant words an option differently from the console.
        "severityDropdown": flat.get("severity"),
        # The weight of the severity, for the dashboard to sum or average.
        "rbpMax": SEVERITY_WEIGHTS.get(severity),
        "tiType": TI_TYPE,
    }

    # The analyst's own call beats the engine's where one has been made;
    # analystVerdict is UNDEFINED until somebody decides.
    for source in (flat.get("analystVerdict"), flat.get("result")):
        tag = TI_TAGS.get(str(source or "").strip().lower())
        if tag:
            values["tiTag"] = tag
            break
    values.setdefault("tiTag", None)

    if isinstance(slo, dict) and slo:
        for key, value in slo.items():
            values["slo_{}".format(key)] = value

    # The console reports its own figure in SECONDS, measured created ->
    # resolved. Confirmed against a resolved alert: created 15:01:47.351,
    # resolved 18:51:02.688, resolvedDuration 13755 - the same 13755.337s.
    # Converted to our unit so the two are comparable rather than one being
    # seconds and the other minutes.
    reported = resolve.get("resolvedDuration")
    if reported is not None:
        try:
            seconds = float(reported)
        except (TypeError, ValueError):
            seconds = None
        if seconds is not None:
            if DURATION_UNIT == "seconds":
                values["resolvedDurationReported"] = round(seconds, 3)
            elif DURATION_UNIT == "milliseconds":
                values["resolvedDurationReported"] = int(seconds * 1000)
            else:
                values["resolvedDurationReported"] = round(seconds / 60.0, 2)

            # Ours and theirs should agree. A gap means one of the timestamps
            # is not what it appears, which is worth knowing before the number
            # reaches a report.
            ours = values.get("timeToResolve")
            if ours is not None:
                scale = {"seconds": 1.0, "milliseconds": 1000.0}.get(
                    DURATION_UNIT, 1 / 60.0)
                drift = abs(ours - seconds * scale)
                if drift > max(2 * scale, abs(ours) * 0.01):
                    print("  {}: time to resolve {} disagrees with the "
                          "console's {} - check which timestamps each measures"
                          .format(flat.get("id"), ours,
                                  values["resolvedDurationReported"]))

    # Whether the resolve landed inside its target, once both exist.
    if values["timeToResolve"] is not None and sla.get("resolve"):
        as_minutes = values["timeToResolve"]
        if DURATION_UNIT == "seconds":
            as_minutes = as_minutes / 60.0
        elif DURATION_UNIT == "milliseconds":
            as_minutes = as_minutes / 60000.0
        values["resolveSlaMet"] = as_minutes <= sla["resolve"]
    return values


def excluded_reason(flat):
    """Why this alert is not being stored, or None to store it.

    Applied after fetching rather than in the query: the GraphQL filter
    operators differ between console versions, and a filter that silently
    matches nothing is worse than one that costs a little bandwidth. Discovery
    prints what this schema's FilterInput accepts, so it can move server-side
    once the operator name is known.
    """
    severity = str(flat.get("severity") or "").strip().lower()
    if ONLY_SEVERITIES:
        # The allow-list wins: anything not named is dropped, including a
        # severity this console starts returning tomorrow.
        if severity not in {s.lower() for s in ONLY_SEVERITIES}:
            return "severity {} (not in {})".format(
                flat.get("severity"), sorted(ONLY_SEVERITIES))
    elif severity in {s.lower() for s in EXCLUDE_SEVERITIES}:
        return "severity {}".format(flat.get("severity"))
    status = str(flat.get("status") or "").strip().lower()
    if status in {s.lower() for s in EXCLUDE_STATUSES}:
        return "status {}".format(flat.get("status"))
    return None


def to_datetime(value):
    """An ISO timestamp as a datetime, or None.

    The original did value.split('.') with no guard, so a null timestamp -
    which this API does return for firstSeenAt and lastSeenAt - raised
    AttributeError and killed the whole run on one alert. It also assumed a
    trailing Z, so an offset like +00:00 failed to parse.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    head = text.split(".")[0].split("+")[0]
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(head, pattern)
        except ValueError:
            continue
    print("could not parse timestamp {!r}; stored as empty".format(value))
    return None


def as_text(value):
    """Anything Swimlane cannot take as-is, rendered readably."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None)
    if isinstance(value, dict):
        return json.dumps(value)
    return value


# ======================================================================
# Discovery
# ======================================================================

def describe(alerts, app):
    """Print what came back, and what the application can hold.

    This is the step the mapping should be written from. It lists every key the
    API actually populated, every key that came back null across all alerts,
    and the application's own field names, so the two can be matched by eye
    instead of by assumption.
    """
    if not alerts:
        print("No alerts in the window. Widen lookback_hours and run again - "
              "an empty window tells you nothing about the shape.")
        return

    print("\n=== one alert, field by field ===")
    shown = 0
    for line in paths(alerts[0]):
        print("  " + line)
        shown += 1
        if shown >= RAW_LINES:
            print("  ... stopped at {} lines; raise RAW_LINES".format(RAW_LINES))
            break

    flats = [flatten(a) for a in alerts]
    keys = sorted({k for f in flats for k in f if k != "_details"})
    populated, always_null = [], []
    for key in keys:
        sample = next((f[key] for f in flats if f.get(key) not in (None, "", [])), None)
        (populated if sample is not None else always_null).append((key, sample))

    print("\n=== keys with data ({} of {}) ===".format(len(populated), len(keys)))
    for key, sample in populated:
        text = str(sample)
        print("  {:<24} {:<10} {}".format(
            key, type(sample).__name__, text[:60] + ("..." if len(text) > 60 else "")))

    print("\n=== keys that were null in all {} alert(s) ===".format(len(flats)))
    print("  " + (", ".join(k for k, _ in always_null) or "none"))

    # A blank duration has two quite different causes - the timestamps it
    # needs were missing, or it was computed and the field did not take it -
    # and only the first is visible from here. Say which.
    print("\n=== why a duration is blank ===")
    total = len(flats)
    for stamp in ("firstSeenAt", "detectedAt", "createdAt", "updatedAt",
                  "lastSeenAt", "resolvedTime"):
        have = sum(1 for f in flats if f.get(stamp))
        print("  {:<16} present on {} of {} alert(s)".format(stamp, have, total))

    for label, computed, sources in (
            ("timeToDetect", "timeToDetect", TIME_TO_DETECT_FROM),
            ("timeToRespond", "timeToRespond", TIME_TO_RESPOND_FROM),
            ("timeToResolve", "timeToResolve", ("createdAt", "resolvedTime"))):
        got = sum(1 for f in flats if f.get(computed) is not None)
        if sources is None:
            print("  {:<16} not computed - TIME_TO_RESPOND_FROM is None, and "
                  "no alert carries an analyst-action timestamp".format(label))
            continue
        missing = [s for s in sources
                   if not any(f.get(s) for f in flats)]
        note = ""
        if got == 0 and missing:
            note = "  <- {} is null on every alert".format(" and ".join(missing))
        print("  {:<16} computed on {} of {} ({} -> {}){}".format(
            label, got, total, sources[0], sources[1], note))
    print("  durations are written in {}; a Swimlane time-span field expects "
          "milliseconds".format(DURATION_UNIT))

    counts = {}
    for f in flats:
        key = str(f.get("severity"))
        counts[key] = counts.get(key, 0) + 1
    print("\n=== severity distribution ===")
    keeping = 0
    scored = []
    for value, count in sorted(counts.items(), key=lambda i: -i[1]):
        dropped = excluded_reason({"severity": value}) is not None
        keeping += 0 if dropped else count
        weight = SEVERITY_WEIGHTS.get(str(value).strip().lower())
        if not dropped and weight is not None:
            scored.append((weight, count))
        print("  {:<14} {:>4}   rbp-max {:<6}{}".format(
            value, count,
            "-" if weight is None else weight,
            "   <- excluded" if dropped else "   kept"))
    if scored:
        # What the dashboard will actually read, so the scale can be judged
        # against a real queue rather than in the abstract.
        total = sum(w * c for w, c in scored)
        alerts_scored = sum(c for _, c in scored)
        print("  rbp-max over the kept alerts: total {}, mean {:.1f}, peak {}"
              .format(total, total / alerts_scored, max(w for w, _ in scored)))
    unweighted = [v for v in counts
                  if SEVERITY_WEIGHTS.get(str(v).strip().lower()) is None]
    if unweighted:
        print("  no SEVERITY_WEIGHTS entry, so rbp-max stays empty: {}"
              .format(", ".join(sorted(unweighted))))
    rule = ("ONLY_SEVERITIES = {}".format(sorted(ONLY_SEVERITIES)) if ONLY_SEVERITIES
            else "EXCLUDE_SEVERITIES = {}".format(sorted(EXCLUDE_SEVERITIES) or "nothing"))
    print("  {} keeps {} of {} alert(s)".format(rule, keeping, len(flats)))

    print("\n=== FilterInput accepts ===")
    try:
        names = [f.get("name") for f in type_fields("FilterInput", post_graphql)]
        print("  " + (", ".join(n for n in names if n) or "none reported"))
        print("  (to filter server-side instead, add a clause to fetch_page's "
              "filters list using one of these)")
    except Exception as error:
        print("  could not read FilterInput ({})".format(error))

    global KEY_NAMES, KNOWN_NAMES, SELECTION_OPTIONS, BARE_KEYS
    KEY_NAMES = key_to_name(app)
    KNOWN_NAMES = set(app_field_names(app))
    SELECTION_OPTIONS = selection_options(app)
    BARE_KEYS = bare_keys(app)
    dump_field_defs(app)

    print("\n=== fields on '{}' (display name <- key) ===".format(app_name))
    pairs = field_pairs(app)
    if pairs:
        for name, key in pairs:
            print("  {:<34} {}".format(name, key or "(no key reported)"))
        print("  FIELD_MAP must use the display name on the left. A key on the "
              "right is accepted by records.create and silently ignored.")
    else:
        print("  could not read the field list from this SDK version")
    print("\n=== dropdowns, and the options they will accept ===")
    if SELECTION_OPTIONS:
        for name in sorted(SELECTION_OPTIONS):
            print("  {:<26} {}".format(name, ", ".join(SELECTION_OPTIONS[name])))
        print("  SELECTION_VALUES must map each SentinelOne value to one of "
              "these, spelled exactly. A dropdown stores nothing else.")
        for key, table in sorted(SELECTION_VALUES.items()):
            field = resolve_field(FIELD_MAP.get(key))
            options = SELECTION_OPTIONS.get(field)
            if not options:
                continue
            wrong = sorted({v for v in table.values()
                            if v is not None and str(v) not in options})
            if wrong:
                print("  {} -> {}: not options: {}".format(
                    key, field, ", ".join(wrong)))
    else:
        print("  this SDK version does not report a field's options; the "
              "wording has to come from the application builder")

    names = app_field_names(app)

    if names:
        missing = [(k, v) for k, v in FIELD_MAP.items()
                   if resolve_field(v) not in names]
        unmapped = [k for k, _ in populated if k not in FIELD_MAP]
        print("\n=== mapping check ===")
        if missing:
            print("  FIELD_MAP points at fields the app does not have:")
            for key, field in missing:
                print("    {!r} -> {!r}".format(key, field))
        else:
            print("  every FIELD_MAP target exists on the application")
        if unmapped:
            print("  populated keys not in FIELD_MAP (data you are discarding):")
            print("    " + ", ".join(unmapped))


def field_pairs(app):
    """(display name, key) for every field, however this SDK exposes them.

    An application field has both a display name and a key - "Alert ID" and
    something like ssa.alert-id. records.create takes the display name and
    quietly ignores anything else, so a key in FIELD_MAP writes nothing and
    raises nothing: the field just stays empty.
    """
    pairs = []
    for attribute in ("field_definitions", "_fields_by_name", "fields"):
        value = getattr(app, attribute, None)
        if isinstance(value, dict):
            for name, definition in value.items():
                key = None
                if isinstance(definition, dict):
                    key = definition.get("key") or definition.get("id")
                else:
                    key = getattr(definition, "key", None) or getattr(definition, "id", None)
                pairs.append((name, key))
        elif isinstance(value, (list, tuple)):
            for definition in value:
                if isinstance(definition, dict):
                    name = definition.get("name")
                    key = definition.get("key") or definition.get("id")
                else:
                    name = getattr(definition, "name", None)
                    key = getattr(definition, "key", None) or getattr(definition, "id", None)
                if name:
                    pairs.append((name, key))
        if pairs:
            return sorted(pairs)
    return pairs


def app_field_names(app):
    """Just the display names."""
    return sorted({name for name, _ in field_pairs(app) if name})


def selection_options(app):
    """Display name -> option list, for every selection field on the app.

    A selection field carries its own set of allowed values, and that set is
    the only thing it will store. Reading it here means a mismatch between
    SELECTION_VALUES and the dropdown is reported with both lists side by
    side, rather than showing up as an empty field weeks later.
    """
    found = {}
    for attribute in ("field_definitions", "fields"):
        value = getattr(app, attribute, None)
        if isinstance(value, dict):
            definitions = [(name, d) for name, d in value.items()]
        elif isinstance(value, (list, tuple)):
            definitions = [(None, d) for d in value]
        else:
            continue
        for name, definition in definitions:
            # Which of these a build uses is not knowable in advance, and
            # looking under one name only means the options read as absent and
            # every dropdown falls back to the console's own wording.
            holders = ("values", "options", "selectionValues", "valuesList",
                       "items", "choices", "selection_values")
            if isinstance(definition, dict):
                name = name or definition.get("name")
                raw = next((definition[h] for h in holders
                            if isinstance(definition.get(h), (list, tuple))
                            and definition[h]), None)
            else:
                name = name or getattr(definition, "name", None)
                raw = next((getattr(definition, h) for h in holders
                            if isinstance(getattr(definition, h, None),
                                          (list, tuple))
                            and getattr(definition, h)), None)
            if not name or not isinstance(raw, (list, tuple)) or not raw:
                continue
            options = []
            for option in raw:
                if isinstance(option, dict):
                    text = (option.get("name") or option.get("value")
                            or option.get("text") or option.get("label"))
                elif isinstance(option, str):
                    text = option
                else:
                    text = (getattr(option, "name", None)
                            or getattr(option, "value", None))
                if text:
                    options.append(str(text))
            if options:
                found[str(name)] = options
        if found:
            return found
    return found


def key_to_name(app):
    """Field key -> display name, so either can be used in FIELD_MAP."""
    mapping = {}
    for name, key in field_pairs(app):
        if key and name:
            mapping[str(key)] = name
            mapping[str(key).lower()] = name
    return mapping


#: Field key -> display name, keyed on the part after the applet prefix. A key
#: is shown in the builder as na.offense-assigned-to or ssa.alert-id, and which
#: prefix a field carries depends on the applet it came from - so a mapping
#: written from one tenant's builder can name the right field under the wrong
#: prefix and match nothing. Consulted only after the exact spellings fail.
BARE_KEYS = {}


def bare_keys(app):
    """The same mapping as key_to_name, with the applet prefix dropped.

    Ambiguous suffixes are discarded rather than guessed at: if two applets
    both carry an offense-assigned-to, there is no way to tell from the
    mapping which was meant, and picking one silently is how a value ends up
    in the wrong field.
    """
    seen = {}
    for name, key in field_pairs(app):
        if not (key and name) or "." not in str(key):
            continue
        bare = str(key).rsplit(".", 1)[-1].strip().lower()
        if not bare:
            continue
        seen.setdefault(bare, set()).add(name)
    return {bare: next(iter(names)) for bare, names in seen.items()
            if len(names) == 1}


# ======================================================================
# Writing
# ======================================================================

#: Fields the application rejected. Populated at runtime from the first write
#: that names one, so a wrong entry in FIELD_MAP costs one retry rather than
#: every alert in the window - which matters when the field list is not known
#: in advance and the SDK will not report it.
UNKNOWN_FIELDS = set()


#: Field key -> display name, filled once from the application. A FIELD_MAP
#: entry naming a key is translated through this before the write.
KEY_NAMES = {}

#: Every display name on the application, so a candidate can be checked before
#: it is sent rather than after it has been silently dropped.
KNOWN_NAMES = set()

#: Display name -> the options a selection field will accept, read from the
#: application. A dropdown takes nothing else: hand it a value that is not on
#: its list and it stores nothing and says nothing, which is how Sev Tag came
#: to read Low for every alert. Empty when the SDK does not report options,
#: and then no check is made.
SELECTION_OPTIONS = {}

#: Field -> "console value -> option" for every value matched by spelling
#: rather than by a table entry. Nothing needs fixing when this appears; it is
#: printed so the translation a run performed is on the record.
OPTION_MATCHED = {}

#: Field -> values that no option matches, by table or by spelling. The field
#: is left alone rather than being sent a value the dropdown would refuse, and
#: these are named at the end of the run beside the options that do exist -
#: the fix is either an entry in SELECTION_VALUES or a new option on the field.
BAD_OPTIONS = {}


def _one_field(field):
    """A single candidate as a display name, or None if the app lacks it."""
    if field in KNOWN_NAMES:
        return field
    for probe in (field, str(field).lower()):
        if probe in KEY_NAMES:
            return KEY_NAMES[probe]
    # Last resort: the same key under a different applet prefix. Only taken
    # when the suffix names exactly one field, so this cannot pick the wrong
    # one of two look-alikes.
    bare = str(field).rsplit(".", 1)[-1].strip().lower()
    if bare in BARE_KEYS:
        matched = BARE_KEYS[bare]
        if str(field) != matched:
            PREFIX_MATCHED[str(field)] = matched
        return matched
    # A key the application did not report, or an app whose field list could
    # not be read: send it as given and let the write decide.
    return None if KNOWN_NAMES else field


#: Candidates matched only by dropping the applet prefix, reported at the end
#: of a run so the mapping can be corrected to the spelling the app uses.
PREFIX_MATCHED = {}


def resolve_field(field):
    """The display name to write under, from a name, a key, or candidates.

    With several candidates the first the application actually has is used, so
    a mapping does not have to know whether this tenant spells it "Asset OS
    Type", "Asset Os Type" or ssa.asset-os-type.
    """
    candidates = field if isinstance(field, (tuple, list)) else (field,)
    for candidate in candidates:
        resolved = _one_field(candidate)
        if resolved:
            return resolved
    # Nothing matched. Return the first candidate so the failure is reported
    # under the name the mapping asked for.
    return candidates[0] if candidates else None


def normalised(text):
    """A value reduced to what two spellings of the same option share.

    SentinelOne writes IN_PROGRESS, a Swimlane dropdown displays In Progress,
    and they are the same option. Case, underscores, hyphens and runs of
    whitespace are the only differences in practice, so they are removed from
    both sides before comparing.
    """
    plain = str(text).strip().lower()
    for character in ("_", "-", "/"):
        plain = plain.replace(character, " ")
    return " ".join(plain.split())


def match_option(value, field):
    """The option this value means, matched against the ones the app reports.

    SELECTION_VALUES stays for the mappings that are decisions - RESOLVED
    meaning Closed, UNDEFINED meaning blank - rather than spellings. Anything
    that differs only in spelling is matched here, against the live option
    list, so a new dropdown needs no table at all and a table written from the
    wrong tenant cannot silently send a value that does not exist.
    """
    options = SELECTION_OPTIONS.get(field)
    if not options or value is None:
        return None
    wanted = normalised(value)
    if not wanted:
        return None
    for option in options:
        if normalised(option) == wanted:
            return option
    return None


def retitled(value, field):
    """The console's value as a dropdown is likely to spell it.

    Only reached when the field's options are unknown, so this is a guess and
    not a match. It is still a better guess than the console's own wording: no
    Swimlane dropdown this script has met displays CRITICAL or IN_PROGRESS.
    """
    if not TITLE_CASE_UNKNOWN_OPTIONS or value is None:
        return value
    words = normalised(value).split()
    if not words:
        return value
    guess = " ".join(word.capitalize() for word in words)
    if guess != str(value):
        RETITLED.setdefault(field or "?", set()).add(
            "{} -> {}".format(value, guess))
    return guess


def fallback_for(key, field, original):
    """The option to fall back to for this key, or None if there is not one."""
    wanted = SELECTION_FALLBACK.get(key)
    if wanted is None:
        return None
    options = SELECTION_OPTIONS.get(field) if field else None
    if options and wanted not in options:
        # The fallback is not an option either. Sending it would store
        # nothing, so it is reported alongside the value it was meant to save.
        BAD_OPTIONS.setdefault(field, set()).add(str(wanted))
        return None
    FELL_BACK.setdefault(field or key, set()).add("{} -> {}".format(
        "(no value)" if original in (None, "") else original, wanted))
    return wanted


def for_selection(key, value, field=None):
    """A selection field's option for this value, or the value unchanged.

    Translating at write time rather than in flatten keeps the console's own
    wording in the details field and the discovery listing, where it is the
    evidence, while the record gets the option its dropdown will accept.
    """
    table = SELECTION_VALUES.get(key)
    if value is None:
        # An alert with no severity at all still belongs somewhere, if the
        # field offers a place for it.
        return fallback_for(key, field, None)
    if not (table or SELECTION_OPTIONS.get(field)):
        return value
    lowered = str(value).strip().lower()
    if table and lowered in table:
        # An explicit decision, and it wins. A table entry mapping to None is
        # a deliberate blank, so there is nothing left to match.
        value = table[lowered]
        if value is None:
            return None
    else:
        matched = match_option(value, field)
        if matched is not None:
            if str(matched) != str(value):
                OPTION_MATCHED.setdefault(field, set()).add(
                    "{} -> {}".format(value, matched))
            value = matched
        elif table is not None:
            # A table exists and has no entry, and no option reads the same.
            UNMAPPED_SELECTIONS.setdefault(key, set()).add(str(value))
    # The dropdown has the last word. Where its options are known and none of
    # them is this value, sending it anyway stores nothing at best and costs a
    # rejected create and a retry at worst - so it is held back and reported.
    options = SELECTION_OPTIONS.get(field) if field else None
    if options and value is not None and str(value) not in options:
        BAD_OPTIONS.setdefault(field, set()).add(str(value))
        return fallback_for(key, field, value)
    if not options:
        # The options could not be read, so nothing above matched anything.
        # Send the likeliest spelling rather than the console's.
        return retitled(value, field)
    return value


#: alert key -> the candidates tried, for every FIELD_MAP entry whose field
#: could not be matched to a field on the application. These never reach the
#: write at all, which is the quietest of all the failures: no value, no
#: error, and nothing in the record to suggest anything was attempted. They
#: used to be left to discovery, which is off on a normal run.
UNRESOLVED_FIELDS = {}


def payload_for(flat, field_names):
    """The FIELD_MAP pairs this alert can actually fill."""
    values = {}
    for key, field in FIELD_MAP.items():
        mapping = field
        field = resolve_field(field)
        if field in UNKNOWN_FIELDS:
            continue
        if field_names and field not in field_names:
            UNRESOLVED_FIELDS[key] = mapping
            continue
        raw = flat.get(key)
        value = to_datetime(raw) if key in DATE_KEYS else as_text(raw)
        value = for_selection(key, value, field)
        if value is not None:
            values[field] = value
    return values


def blame_fields(error, values):
    """Which of these field names the error mentions.

    The SDK does not hand back a structured "unknown field" error, but it does
    put the name in the message. Matching against the names actually sent is
    safer than parsing the text, and a false positive only costs one field.
    """
    text = str(error)
    named = {field for field in values if field and field in text}
    # A selection field named in the error is ambiguous: the field may be
    # missing, or present and refusing the value. Blaming it drops it for the
    # rest of the run, so a dropdown gets the benefit of the doubt and is
    # reported instead.
    refused = {field for field in named if field in SELECTION_OPTIONS}
    for field in sorted(refused):
        print("  {!r} refused {!r}; it accepts only: {}".format(
            field, values.get(field), ", ".join(SELECTION_OPTIONS[field])))
        BAD_OPTIONS.setdefault(field, set()).add(str(values.get(field)))
    UNKNOWN_FIELDS.update(named - refused)
    return named


#: Fields the application accepted without storing anything. Reported once at
#: the end rather than per alert.
SILENT_FIELDS = set()


def verify_written(record, values, alert_id):
    """Check the values actually landed on the record.

    records.create ignores a name it does not recognise instead of raising, so
    a field key used where a display name was wanted writes nothing and
    reports nothing. Reading the record back is the only way to catch it.
    """
    if record is None:
        return
    for field, sent in values.items():
        if field in SILENT_FIELDS:
            continue
        try:
            stored = record[field]
        except Exception:
            # The name is not addressable on the record either: same problem.
            SILENT_FIELDS.add(field)
            continue
        if sent in (None, ""):
            continue                      # a deliberate blank, not a dropped write
        if stored in (None, ""):
            SILENT_FIELDS.add(field)
            options = SELECTION_OPTIONS.get(field)
            if options:
                # A dropdown, so the name resolved and the value is the suspect.
                print("  {}: {!r} stored nothing - sent {!r}, and the dropdown "
                      "accepts only: {}".format(
                          alert_id, field, sent, ", ".join(options)))
            else:
                print("  {}: {!r} was accepted but stored nothing - it is "
                      "probably a field key where the display name is wanted"
                      .format(alert_id, field))
        elif (field in SELECTION_OPTIONS and sent not in (None, "")
              and str(stored) != str(sent)):
            # Accepted, non-empty, and not what was sent. Worth saying: a
            # dropdown that rewrites the value is not storing what we think.
            print("  {}: {!r} holds {!r}, not the {!r} that was sent"
                  .format(alert_id, field, stored, sent))


def untouched(verdict, status):
    """True when neither the verdict nor the status shows anyone has acted."""
    return (str(verdict or "").strip().lower() in UNTOUCHED_VERDICTS
            and str(status or "").strip().lower() in UNTOUCHED_STATUSES)


def stored(record, candidates):
    """A field's current value on the record, by whichever name it answers to."""
    for name in (candidates if isinstance(candidates, (tuple, list))
                 else (candidates,)):
        try:
            return record[resolve_field(name)]
        except Exception:
            continue
    return None


def clear_emptied(record, flat, values, field_names):
    """Blank the fields in CLEAR_WHEN_EMPTY that the console no longer fills.

    payload_for drops an empty value, which is what keeps a sync from wiping a
    field the API happens not to return. For the few fields that genuinely go
    back to empty - the assignee above all - that is wrong, and the record
    keeps naming a previous owner indefinitely.
    """
    cleared = dict(values)
    for key in CLEAR_WHEN_EMPTY:
        field = resolve_field(FIELD_MAP.get(key))
        if not field or field in cleared or field in UNKNOWN_FIELDS:
            continue
        if field_names and field not in field_names:
            continue
        if flat.get(key) not in (None, "", []):
            continue                      # the console sent a value; not our case
        if stored(record, FIELD_MAP.get(key)) in (None, ""):
            continue                      # already empty, nothing to do
        cleared[field] = None
    return cleared


def keep_analyst_values(record, values):
    """Drop writes that would overwrite a state only an analyst sets.

    On Hold is the case this exists for: it is an option on the Swimlane
    dropdown and not a SentinelOne status, so every sync would push the record
    from On Hold back to New and the triage would not survive ten minutes.
    """
    kept = dict(values)
    for key, owned in ANALYST_OWNED.items():
        field = resolve_field(FIELD_MAP.get(key))
        if field not in kept:
            continue
        current = str(stored(record, FIELD_MAP.get(key)) or "").strip().lower()
        if current in owned:
            kept.pop(field)
    return kept


def response_values(record, flat, field_names):
    """A response time, if this sync is the one that saw the alert get picked up.

    The transition is the whole point. An alert already acted on when first
    seen was responded to before this script was watching, so it gets nothing;
    one that was untouched last sync and is not now was picked up somewhere in
    between, and the interval between syncs is the resolution available.
    """
    respond_field = resolve_field(FIELD_MAP.get("timeToRespond"))
    if not respond_field or (field_names and respond_field not in field_names):
        return {}
    if stored(record, FIELD_MAP["timeToRespond"]) not in (None, ""):
        return {}                      # already measured; never overwrite it

    was = untouched(stored(record, FIELD_MAP.get("analystVerdict")),
                    stored(record, FIELD_MAP.get("status")))
    now_untouched = untouched(flat.get("analystVerdict"), flat.get("status"))
    if not was or now_untouched:
        return {}                      # no transition this sync

    seen_at = datetime.now(timezone.utc)
    elapsed = duration(flat.get("openedTime"), seen_at.isoformat())
    if elapsed is None:
        return {}
    print("  {}: picked up between syncs ({} -> {}); time to respond {} {}"
          .format(flat.get("id"),
                  stored(record, FIELD_MAP.get("status")) or "untouched",
                  flat.get("status"), elapsed, DURATION_UNIT))

    values = {respond_field: elapsed}
    responded_field = resolve_field(("Responded Time", "responded-time"))
    if responded_field and (not field_names or responded_field in field_names):
        values[responded_field] = seen_at
    return values


#: Set False once the fields are confirmed working, to keep the task log
#: short. One alert is traced, not every alert, so the cost is a few lines.
TRACE_SELECTIONS = True

#: Field names or keys whose raw definition is printed, exactly as the SDK
#: reports it. This is the one thing that settles a dropdown that will not
#: populate: it shows whether the field is a selection field at all, and under
#: which key its options are listed - which differs between builds, and an
#: option list looked for under the wrong name reads as no options and sends
#: the console's wording instead. Matched loosely, so "severity" catches
#: Severity Dropdown and severity-dropdown alike. Empty to print nothing.
DUMP_FIELD_DEFS = {"severity-dropdown", "alert-status"}

#: Extra alert keys to trace alongside the dropdowns. Add the key of any field
#: that is coming out empty: the trace separates the causes, which the empty
#: field cannot. "" is accepted as a key so a whole-record trace is possible
#: by listing FIELD_MAP's keys here.
TRACE_FIELDS = {"assigneeEmail", "assigneeName", "_details"}

_TRACED = []


def dump_field_defs(app):
    """Print the SDK's own definition for the fields named in DUMP_FIELD_DEFS."""
    if not DUMP_FIELD_DEFS:
        return
    wanted = [normalised(w) for w in DUMP_FIELD_DEFS if str(w).strip()]
    for attribute in ("field_definitions", "fields"):
        value = getattr(app, attribute, None)
        if isinstance(value, dict):
            definitions = list(value.values())
        elif isinstance(value, (list, tuple)):
            definitions = list(value)
        else:
            continue
        shown = 0
        for definition in definitions:
            if isinstance(definition, dict):
                label = "{} {}".format(definition.get("name") or "",
                                       definition.get("key") or "")
                body = definition
            else:
                label = "{} {}".format(getattr(definition, "name", "") or "",
                                       getattr(definition, "key", "") or "")
                body = {a: getattr(definition, a) for a in dir(definition)
                        if not a.startswith("_")
                        and not callable(getattr(definition, a, None))}
            haystack = normalised(label)
            if not any(w and w in haystack for w in wanted):
                continue
            if not shown:
                print("\n=== raw field definitions, from app.{} ==="
                      .format(attribute))
            shown += 1
            print("  {}".format(label.strip()))
            for shown_line, line in enumerate(paths(body)):
                if shown_line >= 60:
                    print("      ... truncated")
                    break
                print("      " + line)
        if shown:
            print("  the option list is whichever key above holds the "
                  "dropdown's wording; selection_options looks under values, "
                  "options, selectionValues, valuesList, items and choices")
            return
    print("\n=== raw field definitions ===")
    print("  this SDK version exposes no field list to read them from")


def trace_selections(flat, values):
    """Print the whole chain for each traced field, once per run.

    A field that stays empty has several possible causes - the name did not
    resolve to anything on the application, the alert carried no value, a
    dropdown had no entry for it, or the mapped value is not one of the
    dropdown's options - and every one of them looks identical from the
    record. Printing each step for a single alert separates them.
    """
    if not TRACE_SELECTIONS or _TRACED:
        return
    _TRACED.append(True)
    print("\n=== fields, for alert {} ===".format(flat.get("id")))
    for key in sorted(set(SELECTION_VALUES) | set(TRACE_FIELDS)):
        if key not in FIELD_MAP:
            print("  {}   <- not a FIELD_MAP key, so nothing is written for it"
                  .format(key))
            continue
        mapping = FIELD_MAP.get(key)
        field = resolve_field(mapping)
        raw = flat.get(key)
        mapped = for_selection(key, as_text(raw), field)
        options = SELECTION_OPTIONS.get(field)
        resolved_ok = field in KNOWN_NAMES
        print("  {}".format(key))
        print("      FIELD_MAP     {!r}".format(mapping))
        print("      resolves to   {!r}{}".format(
            field, "" if resolved_ok else
            "   <- NO field on this app answers to any of those"))
        if options:
            print("      options       {}".format(", ".join(options)))
            print("      alert sends   {!r}".format(raw))
            print("      mapped to     {!r}{}".format(
                mapped, "" if mapped is None or str(mapped) in options
                else "   <- NOT an option, so it will store nothing"))
        else:
            print("      field type    {}".format(
                "not a dropdown (text, number or date)" if resolved_ok
                else "unknown - the name did not resolve"))
            print("      alert sends   {!r}{}".format(
                raw, "   <- the alert carried no value, so nothing to write"
                if raw in (None, "", []) else ""))
        if not resolved_ok:
            reason = "no - the name does not match any field"
        elif field in values:
            reason = "yes"
        elif raw in (None, "", []):
            reason = "no - the alert sent nothing"
        else:
            reason = "no - dropped on the way to the write"
        print("      in the write  {}".format(reason))


def upsert(app, flat, field_names):
    """Create the record, or update the one already holding this alert id.

    The original only created, so an alert whose status later changed kept the
    status it had when first seen. Storing the change is the point of syncing.
    """
    alert_id = flat.get("id")
    if not alert_id:
        return "skipped"

    values = payload_for(flat, field_names)
    trace_selections(flat, values)
    if not values:
        return "skipped"

    existing = list(app.records.search((KEY_FIELD, EQ, alert_id)))
    if not existing:
        try:
            created = app.records.create(**values)
            verify_written(created, values, alert_id)
        except Exception as error:
            named = blame_fields(error, values)
            if not named:
                raise
            # The application named a field it does not have. Drop it and try
            # once more: every later alert skips it too, so the cost is one
            # retry for the whole run rather than one failure per alert.
            # "rejected" covers two different things. A field the app does
            # not have stays dropped for the run; a dropdown that refused one
            # value is dropped from this write only, and the next alert may
            # carry a value it does accept.
            missing = sorted(named & UNKNOWN_FIELDS)
            refused = sorted(named - UNKNOWN_FIELDS)
            if missing:
                print("  the application does not have, dropping for the run: "
                      "{}".format(", ".join(missing)))
            if refused:
                print("  {}: writing without {} - the value it refused is "
                      "named above".format(alert_id, ", ".join(refused)))
            retry = {k: v for k, v in values.items() if k not in named}
            if not retry:
                raise
            created = app.records.create(**retry)
            verify_written(created, retry, alert_id)
        return "created"

    record = existing[0]
    if DETECT_RESPONSE_ON_SYNC:
        values.update(response_values(record, flat, field_names))
    values = clear_emptied(record, flat, values, field_names)
    values = keep_analyst_values(record, values)
    changed = False
    for field, value in values.items():
        try:
            if record[field] != value:
                record[field] = value
                changed = True
        except Exception as error:        # one bad field must not lose the rest
            print("  {}: could not set {!r}: {}".format(alert_id, field, error))
    if not changed:
        return "unchanged"
    record.save()
    # The update path used to stop here. Assignment to a selection field can
    # be accepted and then store nothing, exactly as create does, so the only
    # record whose fields were ever checked was a brand new one - and after
    # the first sync there are no new ones. Verify here too.
    verify_written(record, values, alert_id)
    return "updated"


# ======================================================================
# Run
# ======================================================================

def main():
    global QUERY

    swimlane = Swimlane(sw_context.config["InternalSwimlaneUrl"],
                        swimlane_user, swimlane_pwd, verify_ssl=False)
    app = swimlane.apps.get(name=app_name)

    QUERY = resolve_query()
    alerts = fetch_alerts()

    if DISCOVERY:
        describe(alerts, app)
        print("\nDISCOVERY mode: nothing was written. Fill in FIELD_MAP from "
              "the lists above, set DISCOVERY = False, and run again.")
        return {"mode": "discovery", "alerts_seen": len(alerts)}

    global KEY_NAMES, KNOWN_NAMES, SELECTION_OPTIONS, BARE_KEYS
    KEY_NAMES = key_to_name(app)
    field_names = app_field_names(app)
    KNOWN_NAMES = set(field_names)
    SELECTION_OPTIONS = selection_options(app)
    BARE_KEYS = bare_keys(app)
    print("\ndropdowns whose options could be read: {}".format(
        ", ".join(sorted(SELECTION_OPTIONS)) or "none - see the definitions below"))
    if not SELECTION_OPTIONS:
        dump_field_defs(app)
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0,
              "failed": 0, "excluded": 0}
    failures = []
    excluded_by = {}

    for alert in alerts:
        flat = flatten(alert)
        reason = excluded_reason(flat)
        if reason:
            counts["excluded"] += 1
            excluded_by[reason] = excluded_by.get(reason, 0) + 1
            continue
        try:
            counts[upsert(app, flat, field_names)] += 1
        except Exception as error:
            # One malformed alert must not cost the whole window. The run
            # continues and names what it could not store.
            counts["failed"] += 1
            failures.append("{}: {}: {}".format(
                flat.get("id"), type(error).__name__, error))

    print("\n{} alert(s): {created} created, {updated} updated, "
          "{unchanged} unchanged, {excluded} excluded, {skipped} skipped, "
          "{failed} failed".format(len(alerts), **counts))
    for reason, count in sorted(excluded_by.items(), key=lambda i: -i[1]):
        print("  excluded {} on {}".format(count, reason))
    if UNKNOWN_FIELDS:
        # The real field list, learned the hard way. Remove these from
        # FIELD_MAP, or add them to the application.
        print("the application does not have: {}"
              .format(", ".join(sorted(UNKNOWN_FIELDS))))
    if RETITLED:
        print("options could not be read, so these were retitled as a guess:")
        for field, pairs in sorted(RETITLED.items()):
            print("  {}: {}".format(field, "; ".join(sorted(pairs))))
        print("  if a field above is still empty, its options are worded "
              "differently - put the exact wording in SELECTION_VALUES")
    if FELL_BACK:
        print("no option matched, so the field took its fallback:")
        for field, pairs in sorted(FELL_BACK.items()):
            print("  {}: {}".format(field, "; ".join(sorted(pairs))))
    if OPTION_MATCHED:
        print("matched to a dropdown option by spelling:")
        for field, pairs in sorted(OPTION_MATCHED.items()):
            print("  {}: {}".format(field, "; ".join(sorted(pairs))))
    if PREFIX_MATCHED:
        print("matched only after dropping the applet prefix - worth "
              "correcting in FIELD_MAP:")
        for wanted, matched in sorted(PREFIX_MATCHED.items()):
            print("  {!r} -> {!r}".format(wanted, matched))
    if UNRESOLVED_FIELDS:
        # Never written, and nothing about the record would show it. The
        # candidates are printed because the fix is a name: run with
        # DISCOVERY = True and copy the spelling the application reports.
        print("no field on '{}' matches these FIELD_MAP entries, so they were "
              "never written:".format(app_name))
        for key, mapping in sorted(UNRESOLVED_FIELDS.items()):
            tried = mapping if isinstance(mapping, (tuple, list)) else (mapping,)
            print("  {:<18} tried {}".format(
                key, ", ".join(repr(t) for t in tried)))
    if SILENT_FIELDS:
        print("accepted but stored nothing (use the display name, not the key): "
              "{}".format(", ".join(sorted(SILENT_FIELDS))))
    if UNMAPPED_SELECTIONS:
        # Written through as-is, so they landed only if the dropdown happens to
        # carry them. Add them to SELECTION_VALUES, or to the dropdown.
        print("values with no entry in SELECTION_VALUES:")
        for key, seen in sorted(UNMAPPED_SELECTIONS.items()):
            print("  {:<18} {}".format(key, ", ".join(sorted(seen))))
    if BAD_OPTIONS:
        # Both lists are printed because the fix is either a SELECTION_VALUES
        # entry on the left or a new option on the field on the right.
        print("no option matches these, so the field was left alone:")
        for field, seen in sorted(BAD_OPTIONS.items()):
            print("  {}: had {}".format(field, ", ".join(sorted(seen))))
            print("  {}  accepts {}".format(
                " " * len(field), ", ".join(SELECTION_OPTIONS.get(field, []))))
    for line in failures[:20]:
        print("  FAILED {}".format(line))

    result = {"mode": "sync", "alerts_seen": len(alerts), "failures": failures[:20],
              "unknown_fields": sorted(UNKNOWN_FIELDS),
              "silent_fields": sorted(SILENT_FIELDS),
              "bad_options": {f: sorted(v) for f, v in BAD_OPTIONS.items()},
              "unresolved_fields": sorted(UNRESOLVED_FIELDS),
              "excluded_by": excluded_by}
    result.update(counts)
    return result


def publish(result):
    """Hand the result back, however this build exposes the sink.

    sw_outputs is a dict in some Swimlane versions and a list in others, and
    the run is already finished by the time it is written - so a mismatch here
    must never turn a successful sync into a failed task.
    """
    scope = globals()
    sink = scope.get("sw_outputs")
    try:
        if isinstance(sink, dict):
            sink.update(result)
        elif isinstance(sink, list):
            sink.append(result)
        else:
            scope["sw_outputs"] = dict(result)
    except Exception as error:
        print("could not publish outputs ({}); the run itself succeeded"
              .format(error))
    return result


outputs = publish(main())
