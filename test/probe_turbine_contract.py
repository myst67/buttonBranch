"""Paste this into a Turbine Python action and run it once.

It answers two questions the KPI scripts depend on:

  1. How does this tenant collect an action's output?
  2. How does it hand inputs to the script?

Add one input named ``records`` bound to any Search Records result, then run and
look at what the action shows. Whatever appears tells you which convention this
tenant uses, and the values themselves report what the script could see.

Nothing here is needed at run time. It is a one-off check.
"""

PROBE = {
    "probe_marker": "turbine-contract-probe",
    "probe_via": "unknown",
}


def describe(context):
    """Report what the script can actually see, without assuming a shape."""
    found = {
        "context_type": type(context).__name__,
        "has_inputs_attribute": hasattr(context, "inputs"),
        "context_is_dict": isinstance(context, dict),
        "input_names_seen": [],
        "records_found": False,
        "records_count": 0,
        "records_type": "none",
        "first_record_keys": [],
    }

    inputs = None
    if hasattr(context, "inputs") and isinstance(context.inputs, dict):
        inputs = context.inputs
        found["inputs_read_from"] = "context.inputs"
    elif isinstance(context, dict) and isinstance(context.get("inputs"), dict):
        inputs = context["inputs"]
        found["inputs_read_from"] = "context['inputs']"
    elif isinstance(context, dict):
        inputs = context
        found["inputs_read_from"] = "context itself"
    else:
        found["inputs_read_from"] = "none: could not locate the inputs"

    if isinstance(inputs, dict):
        found["input_names_seen"] = sorted(str(k) for k in inputs)
        records = inputs.get("records")
        found["records_type"] = type(records).__name__
        if isinstance(records, list):
            found["records_found"] = True
            found["records_count"] = len(records)
            if records and isinstance(records[0], dict):
                # The exact column names this tenant returns, which is what the
                # field map has to match.
                found["first_record_keys"] = sorted(str(k) for k in records[0])[:40]
        elif isinstance(records, dict):
            found["records_found"] = True
            found["records_type"] = "dict: the search result is wrapped"
            found["first_record_keys"] = sorted(str(k) for k in records)[:40]
        elif isinstance(records, str):
            found["records_type"] = "str: the array arrived as JSON text"

    return found


def main(context=None):
    result = dict(PROBE)
    result["probe_via"] = "main() return value"
    result.update(describe(context))

    # Publish the same thing every other way an action might be read. Whichever
    # one shows up in the run output is this tenant's convention.
    scope = globals()
    for name in ("outputs", "output", "result"):
        copy = dict(result)
        copy["probe_via"] = "module-level `{}`".format(name)
        scope[name] = copy

    if context is not None:
        existing = getattr(context, "outputs", None)
        payload = dict(result)
        payload["probe_via"] = "context.outputs"
        if isinstance(existing, dict):
            existing.update(payload)
        else:
            try:
                context.outputs = payload
            except (AttributeError, TypeError):
                pass
        if isinstance(context, dict):
            if not isinstance(context.get("outputs"), dict):
                context["outputs"] = {}
            context["outputs"].update(payload)

    return result


script = main
run = main
execute = main
handler = main

# main() sets the module-level names itself, each labelled with its own channel,
# so do not overwrite them here: the label is the whole point of the probe.
if "context" in globals():
    _probe_return = main(globals()["context"])
