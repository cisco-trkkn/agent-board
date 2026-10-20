import io, json, os, sys, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
FIXTURE = os.path.join(HERE, "fixtures", "mgr")
sys.path.insert(0, SCRIPTS)
import inventory  # noqa: E402

def run(argv):
    """Run inventory.main(argv); return (exit code, parsed stdout JSON or None, stderr text)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = inventory.main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None), err.getvalue()

def by_id(items):
    return {i["id"]: i for i in items}
