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
    "noteExists": "Note Exists",
    "detectionProduct": "Detection Product",
    "detectionVendor": "Detection Vendor",
    "assetId": "Asset Id",
    "assetName": "Asset Name",
}

#: Keys whose value is an ISO timestamp and must reach Swimlane as a datetime.
DATE_KEYS = {"detectedAt", "createdAt", "updatedAt", "firstSeenAt", "lastSeenAt"}

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

QUERY = """
query listAlerts($filters: [FilterInput!], $sortBy: String!, $sortOrder: SortOrderType!,
                 $first: Int, $after: String) {
  alerts(filters: $filters, sort: {by: $sortBy, order: $sortOrder},
         first: $first, after: $after) {
    totalCount
    pageInfo { hasNextPage endCursor }
    edges {
      cursor
      node {
        id name description status severity analystVerdict classification
        confidenceLevel externalId storylineId attackSurfaces dataSources labels
        detectedAt createdAt updatedAt firstSeenAt lastSeenAt noteExists
        fileHash fileName exclusionHash exclusionHashes { sha1 sha256 }
        ticketId result attackPathExists attackPaths { id name }
        availableActionIds
        assignee { userId fullName email }
        detectionSource { engine product vendor }
        incident { id name }
        resolveData { resolvedAt resolvedDuration }
        aiInvestigationStatus
        aiInvestigation { autoTriggered purpleAiStatus status timestamp verdict }
        tags { key keyValue type value }
        assets { id name osType status category type agentUuid agentVersion }
        process { cmdLine parentName file { name path md5 sha1 sha256 certSubject } }
      }
    }
  }
}
"""


def call_api(after=None):
    """One page of alerts, retrying the transient failures.

    The original called response.json() straight off the request. A 429 or a
    gateway error returns a body that is not the expected shape - sometimes not
    JSON at all - so the failure surfaced as a confusing parse error rather
    than as the rate limit it was.
    """
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

    body = {"query": QUERY, "variables": variables}
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
                # GraphQL reports its own errors inside a 200.
                if payload.get("errors"):
                    raise RuntimeError("GraphQL errors: {}".format(payload["errors"]))
                return payload
            last_error = "{}: {}".format(status, response.text[:300])

        if status not in RETRY_ON and status != 0:
            raise RuntimeError("SentinelOne returned {}. Not retryable - check "
                               "the token, the console URL and the query. {}"
                               .format(status, last_error))

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


def fetch_alerts():
    """Every alert in the window, following the cursor.

    The original asked for pageInfo and then ignored it, so anything past the
    first 100 alerts was silently dropped.
    """
    nodes, cursor, pages, total = [], None, 0, None

    while pages < max_pages:
        payload = call_api(cursor)
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

    flat = {key: node.get(key) for key in (
        "id", "name", "description", "status", "severity", "analystVerdict",
        "classification", "confidenceLevel", "externalId", "storylineId",
        "attackSurfaces", "dataSources", "labels", "detectedAt", "createdAt",
        "updatedAt", "firstSeenAt", "lastSeenAt", "noteExists", "fileHash",
        "fileName", "exclusionHash", "ticketId", "result", "attackPathExists",
        "availableActionIds", "aiInvestigationStatus")}

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
    })

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

def payload_for(flat, field_names):
    """The FIELD_MAP pairs this alert can actually fill."""
    values = {}
    for key, field in FIELD_MAP.items():
        if field_names and field not in field_names:
            continue                       # reported by discovery, skipped here
        raw = flat.get(key)
        value = to_datetime(raw) if key in DATE_KEYS else as_text(raw)
        if value is not None:
            values[field] = value
    return values


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
        app.records.create(**values)
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
    swimlane = Swimlane(sw_context.config["InternalSwimlaneUrl"],
                        swimlane_user, swimlane_pwd, verify_ssl=False)
    app = swimlane.apps.get(name=app_name)

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
    for line in failures[:20]:
        print("  FAILED {}".format(line))

    result = {"mode": "sync", "alerts_seen": len(alerts), "failures": failures[:20]}
    result.update(counts)
    return result


outputs = main()
try:
    sw_outputs.update(outputs)
except NameError:
    pass
