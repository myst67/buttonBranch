"""Smallest possible Turbine Python action. Paste, run, look at the node.

No inputs needed. It returns three constants and publishes them every way an
action's result can be collected.

  Values appear  -> output plumbing works, so the problem is in how Script A is
                    wired: its `records` input, or its output keys.
  Nothing appears -> the tenant is not surfacing this action's output at all.
                    Declare the keys alpha, beta and gamma in the action's
                    output schema and run it again.

Read the result on the Python ACTION node inside the run, not on the playbook
job record: the job record shows the playbook's own inputs and result, which are
empty on a TEST run whatever the actions did.
"""

RESULT = {"alpha": 1, "beta": "hello", "gamma": True}


def main(context=None):
    return dict(RESULT)


# Every collection convention, so at least one of them lands.
outputs = dict(RESULT)
output = dict(RESULT)
result = dict(RESULT)

script = main
run = main
execute = main
handler = main

if "context" in globals():
    _ctx = globals()["context"]
    _payload = dict(RESULT)
    _existing = getattr(_ctx, "outputs", None)
    if isinstance(_existing, dict):
        _existing.update(_payload)
    else:
        try:
            _ctx.outputs = _payload
        except (AttributeError, TypeError):
            pass
    if isinstance(_ctx, dict):
        if not isinstance(_ctx.get("outputs"), dict):
            _ctx["outputs"] = {}
        _ctx["outputs"].update(_payload)
