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
DISCOVERY = True

#: The Swimlane application alerts are stored in. Pass app_name as an input to
#: override it, so the same script can serve dev and prod without an edit.
APP_NAME = "Test | SentinelOne Case Management Application"

#: The field on the application holding the SentinelOne alert id. This is the
#: key the script de-duplicates on, so it must be unique per alert.
KEY_FIELD = "Alert ID"

#: Alert key -> Swimlane field name. Only the pairs listed here are written, so
#: an unmapped key is ignored rather than crashing the run. Fill this in from
#: what DISCOVERY prints: the left side must match a key in the flattened
#: alert, the right side must match a field name on the application exactly.
FIELD_MAP = {
    "id": "Alert ID",
    "name": "Alert_Name",
    "description": "Alert_Description",
    "status": "Alert Status",
    "severity": "Alert Severity",
    "classification": "Alert Classification",
    "confidenceLevel": "Confidence Level",
    "externalId": "External ID",
    "storylineId": "StoryLine ID",
    "attackSurfaces": "Attack Surfaces",
    "dataSources": "Data Sources",
    "detectedAt": "Detected At",
    "createdAt": "Created At",
    "updatedAt": "Updated At",
    "fileName": "File_Name",
    "fileHash": "File Hash",
    "ticketId": "Ticket ID",
    # Commented out in the original because a null timestamp crashed the run.
    # to_datetime() returns None for those now, so they can come back.
    "firstSeenAt": "First Seen At",
    "lastSeenAt": "Last Seen At",
    "noteExists": "Note Exists",
    "detectionProduct": "Detection Product",
    "detectionVendor": "Detection Vendor",
    "assetId": "Asset Id",
    "assetName": "Asset Name",
}

#: Keys whose value is an ISO timestamp and must reach Swimlane as a datetime.
DATE_KEYS = {"detectedAt", "createdAt", "updatedAt", "firstSeenAt", "lastSeenAt"}

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


def fetch_page(after=None):
    """One page of alerts."""
    variables = {
        "filters": [{
            "fieldId": "createdAt",
            "dateTimeRange": {
                "start": start_ms, "end": end_ms,
                "startInclusive": True, "endInclusive": True,
            },
        }],
        "sortBy": "createdAt",
        "sortOrder": "DESC",
        "first": page_size,
    }
    if after:
        variables["after"] = after
    return post_graphql(QUERY, variables)


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
    try:
        selection = selection_for("UnifiedAlert", post_graphql)
    except Exception as error:
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
    return flat


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

    print("\n=== one raw alert, in full ===")
    print(json.dumps(alerts[0], indent=2, default=str)[:4000])

    flats = [flatten(a) for a in alerts]
    keys = sorted({k for f in flats for k in f})
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

    print("\n=== fields on '{}' ===".format(app_name))
    names = app_field_names(app)
    print("  " + (", ".join(names) if names else
                  "could not read the field list from this SDK version"))

    if names:
        missing = [(k, v) for k, v in FIELD_MAP.items() if v not in names]
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


def app_field_names(app):
    """Field names, however this SDK version exposes them."""
    for attribute in ("field_definitions", "_fields_by_name", "fields"):
        value = getattr(app, attribute, None)
        if isinstance(value, dict):
            return sorted(value.keys())
        if isinstance(value, (list, tuple)):
            names = [getattr(f, "name", None) or (
                f.get("name") if isinstance(f, dict) else None) for f in value]
            names = [n for n in names if n]
            if names:
                return sorted(names)
    return []


# ======================================================================
# Writing
# ======================================================================

#: Fields the application rejected. Populated at runtime from the first write
#: that names one, so a wrong entry in FIELD_MAP costs one retry rather than
#: every alert in the window - which matters when the field list is not known
#: in advance and the SDK will not report it.
UNKNOWN_FIELDS = set()


def payload_for(flat, field_names):
    """The FIELD_MAP pairs this alert can actually fill."""
    values = {}
    for key, field in FIELD_MAP.items():
        if field in UNKNOWN_FIELDS:
            continue
        if field_names and field not in field_names:
            continue                       # reported by discovery, skipped here
        raw = flat.get(key)
        value = to_datetime(raw) if key in DATE_KEYS else as_text(raw)
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
    UNKNOWN_FIELDS.update(named)
    return named


def upsert(app, flat, field_names):
    """Create the record, or update the one already holding this alert id.

    The original only created, so an alert whose status later changed kept the
    status it had when first seen. Storing the change is the point of syncing.
    """
    alert_id = flat.get("id")
    if not alert_id:
        return "skipped"

    values = payload_for(flat, field_names)
    if not values:
        return "skipped"

    existing = list(app.records.search((KEY_FIELD, EQ, alert_id)))
    if not existing:
        try:
            app.records.create(**values)
        except Exception as error:
            named = blame_fields(error, values)
            if not named:
                raise
            # The application named a field it does not have. Drop it and try
            # once more: every later alert skips it too, so the cost is one
            # retry for the whole run rather than one failure per alert.
            print("  dropping field(s) the application rejected: {}"
                  .format(", ".join(sorted(named))))
            retry = {k: v for k, v in values.items() if k not in named}
            if not retry:
                raise
            app.records.create(**retry)
        return "created"

    record = existing[0]
    changed = False
    for field, value in values.items():
        try:
            if record[field] != value:
                record[field] = value
                changed = True
        except Exception as error:        # one bad field must not lose the rest
            print("  {}: could not set {!r}: {}".format(alert_id, field, error))
    if changed:
        record.save()
        return "updated"
    return "unchanged"


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

    field_names = app_field_names(app)
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "failed": 0}
    failures = []

    for alert in alerts:
        flat = flatten(alert)
        try:
            counts[upsert(app, flat, field_names)] += 1
        except Exception as error:
            # One malformed alert must not cost the whole window. The run
            # continues and names what it could not store.
            counts["failed"] += 1
            failures.append("{}: {}: {}".format(
                flat.get("id"), type(error).__name__, error))

    print("\n{} alert(s): {created} created, {updated} updated, "
          "{unchanged} unchanged, {skipped} skipped, {failed} failed"
          .format(len(alerts), **counts))
    if UNKNOWN_FIELDS:
        # The real field list, learned the hard way. Remove these from
        # FIELD_MAP, or add them to the application.
        print("the application does not have: {}"
              .format(", ".join(sorted(UNKNOWN_FIELDS))))
    for line in failures[:20]:
        print("  FAILED {}".format(line))

    result = {"mode": "sync", "alerts_seen": len(alerts), "failures": failures[:20],
              "unknown_fields": sorted(UNKNOWN_FIELDS)}
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
