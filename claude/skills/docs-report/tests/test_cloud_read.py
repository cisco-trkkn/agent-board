import io, json, os, re, shutil, subprocess, sys, tempfile, time, contextlib, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import cloud_read  # noqa: E402

class Fake:
    def __init__(self, code=0): self.calls, self.code = [], code
    def __call__(self, argv, **kw):
        self.calls.append(argv)
        code = self.code
        class R: returncode, stdout, stderr = code, "out\n", ""
        return R

ALLOWED = [
    ["gcloud", "--version"],
    ["gcloud", "projects", "describe", "trk-org-prod-0"],
    ["gcloud", "run", "services", "list", "--project=trk-org-prod-0", "--format=json"],
    ["gcloud", "beta", "run", "services", "list"],
    ["gcloud", "projects", "get-iam-policy", "p"],
    ["gcloud", "projects", "get-ancestors", "p"],
    ["bq", "--project_id=p", "show", "ds.t"],
    ["bq", "ls", "p:ds"],
    ["bq", "query", "--dry_run", "--use_legacy_sql=false", "SELECT 1"],
    ["bq", "query", "--use_legacy_sql=false", "WITH a AS (SELECT 1 AS x) SELECT x FROM a"],
    ["bq", "query", "select 1;"],
    ["bq", "query", "SELECT 1 -- DROP TABLE t"],
    ["bq", "query", "SELECT 'DELETE; x' AS s"],
    ["bq", "query", "--dry_run=true", "SELECT 1"],
    ["gcloud", "alpha", "projects", "describe", "--project=p"],
    ["gcloud", "compute", "instances", "list", "--filter=name=x"],
    ["gcloud", "iam", "workload-identity-pools", "providers", "list", "--workload-identity-pool=w"],
    ["gcloud", "sql", "instances", "describe", "inst"],
    ["bq", "--project_id=p", "--location=EU", "ls"],
    # final review C2: the bq flag allowlists
    ["bq", "--format=json", "ls"],
    ["bq", "query", "--nodry_run", "SELECT 1"],
    ["bq", "query", "--nouse_legacy_sql", "SELECT 1"],
    ["bq", "query", "--max_rows=10", "--maximum_bytes_billed=1000", "--location=EU", "--project_id=p",
     "--format=json", "--parameter=x:INT64:1", "SELECT @x"],
    ["bq", "ls", "--max_results=5", "--format=json", "--project_id=p", "--location=EU", "p:ds"],
    ["bq", "show", "--format=prettyjson", "ds.t"],
]
REFUSED = [
    ["gcloud", "projects", "create", "p"],
    ["gcloud", "run", "services", "delete", "s"],
    ["gcloud", "projects", "set-iam-policy", "p", "f.json"],
    ["gcloud", "projects", "add-iam-policy-binding", "p", "--member=x", "--role=y"],
    ["gcloud", "run", "deploy", "s"],
    ["gcloud", "compute", "ssh", "vm"],
    ["gcloud", "projects", "list", "delete"],
    ["gcloud", "scheduler", "jobs", "run", "x"],            # run is denied beyond the group position
    ["gcloud", "beta", "scheduler", "jobs", "run", "x"],
    ["gcloud", "run", "services", "list", "run"],           # identifier equal to a deny word
    ["gcloud", "projects"],                                 # no read verb
    ["gcloud"], [],
    ["bq", "rm", "ds.t"], ["bq", "mk", "ds"], ["bq", "load", "ds.t", "gs://b/f"],
    ["bq", "query", "INSERT INTO t VALUES (1)"],
    ["bq", "query", "SELECT 1; UPDATE t SET a = 1"],
    ["bq", "query", "DELETE FROM t WHERE true"],
    ["bq", "query", "MERGE t USING s ON true WHEN MATCHED THEN DELETE"],
    ["bq", "query", "CREATE TABLE t AS SELECT 1"],
    ["bq", "query", "DROP TABLE t"],
    ["bq", "query", "SELECT 1; SELECT 2"],
    ["bq", "query", "SELECT '--'; DROP TABLE t"],           # quote hides a fake comment
    ["bq", "query", "SELECT 1 /* x */; DROP TABLE t"],
    ["bq", "query", "SELECT 'unterminated"],
    ["bq", "query", "--destination_table=ds.t", "SELECT 1"],
    ["bq", "query", "--dry_run", "--destination_table=ds.t", "SELECT 1"],
    ["bq", "query", "--dry_run=false", "DROP TABLE t"],
    ["bq", "query", "--nodry_run", "DROP TABLE t"],
    ["bq", "query"],
    ["bq", "query", "SELECT 1", "SELECT 2"],
    # review round 1: gcloud write verbs next to a read verb
    ["gcloud", "storage", "rm", "gs://b/obj", "list"],
    ["gcloud", "storage", "cp", "list", "gs://b/x"],
    ["gcloud", "compute", "instances", "add-metadata", "vm", "--metadata=a=b", "describe"],
    ["gcloud", "pubsub", "topics", "publish", "t", "--message", "m", "list"],
    ["gcloud", "run", "jobs", "execute", "list"],
    ["gcloud", "functions", "call", "list"],
    ["gcloud", "projects", "list", "a", "b"],               # second positional after the verb
    ["gcloud", "list", "projects"],                          # verb is not after a group
    ["gcloud", "beta", "list"],                              # track only, no group
    ["gcloud", "Projects", "list"],                          # group token fails the pattern
    # review round 2: bare bq global flag shifts the subcommand; gcloud write paths not in the allowlist
    ["bq", "--project_id", "show", "rm", "-f", "ds.t"],
    ["bq", "--location", "ls", "rm", "ds.t"],
    ["gcloud", "logging", "write", "mylog", "list"],
    ["gcloud", "compute", "instances", "attach-disk", "vm", "list"],
    ["gcloud", "sql", "instances", "failover", "inst", "describe"],
    ["gcloud", "storage", "objects", "list"],                # path not listed
    ["gcloud", "beta", "logging", "write", "list"],
    # review round 1: dry-run flags, \r comments, EXTERNAL_QUERY, flag files
    ["bq", "query", "--dry_run", "--nodry_run", "DROP TABLE t"],
    ["bq", "query", "--dry_run", "--dry_run=false", "DROP TABLE t"],
    ["bq", "query", "--dry_run", "DROP TABLE t"],            # dry run relaxes nothing
    ["bq", "query", "SELECT 1 --x\r; DROP TABLE t"],
    ["bq", "query", "SELECT 1 #x\r; DROP TABLE t"],
    ["bq", "query", "SELECT * FROM EXTERNAL_QUERY('c', 'DELETE FROM x')"],
    ["bq", "query", "select * from external_query('c', 'x')"],
    ["bq", "show", "--flagfile=/tmp/x", "ds.t"],
    ["bq", "--bigqueryrc=/tmp/rc", "query", "SELECT 1"],
    ["bq", "--bigqueryrc=/tmp/rc", "ls"],
    ["bq", "--flagfile", "ds.t", "ls"],
    ["gcloud", "projects", "list", "--flags-file=/tmp/x.yaml"],
    ["terraform", "plan"], ["sh", "-c", "gcloud projects list"],
    ["/usr/bin/gcloud", "projects", "list"],
    # final review C1: a separate flag value swallows the read verb, gcloud runs the next token
    ["gcloud", "iam", "roles", "--project", "list", "copy", "--source=roles/viewer", "--destination=x",
     "--dest-project=p"],
    ["gcloud", "iam", "roles", "--format", "list", "copy", "--source=roles/viewer", "--destination=x",
     "--dest-project=p"],
    ["gcloud", "projects", "--project", "list", "move"],
    ["gcloud", "sql", "instances", "--format", "list", "restart"],
    ["gcloud", "run", "services", "list", "--project", "p"],   # any flag without '=' is refused
    ["gcloud", "projects", "list", "-q"],
    # final review C2 + Minor 1: bq flags outside the allowlists, any dash spelling
    ["bq", "query", "-destination_table=ds.t", "SELECT 1"],
    ["bq", "query", "-replace", "--destination_table=ds.t", "SELECT 1"],
    ["bq", "query", "-replace", "SELECT 1"],
    ["bq", "query", "-append_table", "SELECT 1"],
    ["bq", "query", "--batch", "SELECT 1"],
    ["bq", "query", "--api=https://evil.example", "SELECT 1"],
    ["bq", "--api=https://evil.example", "ls"],
    ["bq", "--apilog=/tmp/x", "ls"],
    ["bq", "-apilog=/tmp/x", "query", "SELECT 1"],
    ["bq", "ls", "--filter=labels.a:b"],
    ["bq", "show", "-j", "job_1"],
    ["bq", "query", "--location", "SELECT 1"],              # value flag without '=' swallows the SQL
    ["bq", "query", "--", "SELECT 1"],
]

OFFLINE_ENV = dict(os.environ, CLOUDSDK_CORE_DISABLE_PROMPTS="1", PAGER="cat",
                   CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK="1",
                   CLOUDSDK_CORE_DISABLE_USAGE_REPORTING="true")

def gate_command(argv):
    """The gcloud command words the gate saw: non-flag tokens up to and including the read verb."""
    toks = [t for t in argv[1:] if not t.startswith("-")]
    return toks if toks[-1] in cloud_read.GCLOUD_READ else toks[:-1]

def gcloud_command(argv):
    """The command words real gcloud resolves argv to, from the SYNOPSIS of `<argv> --help` (offline)."""
    out = subprocess.run(argv + ["--help"], capture_output=True, text=True, timeout=60,
                         stdin=subprocess.DEVNULL, env=OFFLINE_ENV).stdout
    lines = re.sub(r"\x1b\[[0-9;]*m", "", out).splitlines()
    synopsis = lines[lines.index("SYNOPSIS") + 1].split()
    assert synopsis[0] == "gcloud", synopsis
    words = []
    for w in synopsis[1:]:
        if not cloud_read.GROUP_RE.match(w):
            break
        words.append(w)
    return words

class CloudRead(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cloudread-")
        self.log = os.path.join(self.dir, "cloud-log.json")
    def tearDown(self):
        shutil.rmtree(self.dir)

    def call(self, argv, run):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cloud_read.main(["--log", self.log, "--"] + argv, run=run)
        return code, out.getvalue()

    def test_allowed_forms(self):
        for argv in ALLOWED:
            with self.subTest(argv=argv):
                self.assertTrue(cloud_read.allowed(argv)[0], cloud_read.allowed(argv))

    def test_refused_forms_never_run(self):
        for argv in REFUSED:
            with self.subTest(argv=argv):
                fake = Fake()
                code, out = self.call(argv, fake)
                self.assertEqual((code, fake.calls), (2, []))
                self.assertTrue(out.startswith("refused: "))
                self.assertEqual(out.count("\n"), 1)
        self.assertFalse(os.path.exists(self.log))

    def test_missing_separator_or_log_is_refused(self):
        fake = Fake()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cloud_read.main(["gcloud", "--version"], run=fake)
        self.assertEqual((code, fake.calls), (2, []))
        self.assertTrue(out.getvalue().startswith("refused: "))

    def test_log_entries_number_up(self):
        fake = Fake()
        self.call(["gcloud", "projects", "describe", "p"], fake)
        code, out = self.call(["bq", "ls", "p:ds"], fake)
        entry = json.loads(out)
        self.assertEqual((code, entry["n"], entry["exit"], entry["output"]), (0, 2, 0, "out\n"))
        self.assertEqual(entry["command"], "bq ls p:ds")
        self.assertEqual([e["n"] for e in json.load(open(self.log))], [1, 2])
        self.assertRegex(entry["timestamp"], r"^\d{4}-\d\d-\d\dT")

    def test_n_follows_highest_existing(self):
        json.dump([{"n": 7}, {"n": 3}], open(self.log, "w"))
        code, out = self.call(["bq", "ls"], Fake())
        self.assertEqual(json.loads(out)["n"], 8)

    def test_nonzero_exit_is_logged_and_returns_1(self):
        code, out = self.call(["bq", "ls"], Fake(code=3))
        self.assertEqual((code, json.loads(out)["exit"]), (1, 3))
        self.assertEqual(len(json.load(open(self.log))), 1)

    def test_corrupt_log_refuses_without_running(self):
        open(self.log, "w").write("not json")
        fake = Fake()
        code, out = self.call(["bq", "ls"], fake)
        self.assertEqual((code, fake.calls), (2, []))
        self.assertTrue(out.startswith("refused: "))

    def test_runner_gets_argv_without_shell(self):
        seen = {}
        def run(argv, **kw):
            seen.update(argv=argv, kw=kw)
            return Fake()(argv)
        self.call(["bq", "ls"], run)
        self.assertEqual(seen["argv"], ["bq", "ls"])
        self.assertFalse(seen["kw"].get("shell", False))

    @unittest.skipUnless(shutil.which("gcloud"), "gcloud not on PATH")
    def test_one_real_call(self):
        code, out = self.call(["gcloud", "--version"], cloud_read.subprocess.run)
        self.assertEqual(code, 0)
        self.assertIn("Google Cloud SDK", json.loads(out)["output"])

    @unittest.skipUnless(shutil.which("gcloud"), "gcloud not on PATH")
    def test_real_gcloud_parses_allowed_argv_as_the_gate_does(self):
        start = time.monotonic()
        for argv in ALLOWED:
            if argv[0] != "gcloud" or argv == ["gcloud", "--version"]:
                continue
            with self.subTest(argv=argv):
                self.assertEqual(gcloud_command(argv), gate_command(argv))
        print(f"\n[real gcloud --help parse: {time.monotonic() - start:.1f}s]", file=sys.stderr)

if __name__ == "__main__":
    unittest.main()
