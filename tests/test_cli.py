import json
import sys

import pytest
from helpers import make_home

from kovcheg import cli
from kovcheg.config import Settings

NO_MODELS = ["--set", "embedding.model=", "--set", "rerank.enabled=false"]


@pytest.fixture
def home(tmp_path):
    return make_home(tmp_path)


def run(capsys, *argv):
    rc = cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_ask_answer_and_numbered_sources(home, capsys):
    rc, out, err = run(capsys, "ask", "J18.9", "code", "--home", home, *NO_MODELS, "--set", "llm.model=echo")
    assert rc == 0
    assert out.startswith("Pneumonia, unspecified organism is coded J18.9 in ICD-10. [1]")
    assert "\nSources:\n[1] codes — Respiratory  (medical: codes.txt)" in out
    assert "Kovcheg can be wrong" in out


def test_options_before_command(home, capsys):
    rc, out, _ = run(capsys, "--home", home, *NO_MODELS, "search", "J18.9")
    assert rc == 0 and "[1] codes" in out


def test_ask_json(home, capsys):
    rc, out, _ = run(capsys, "ask", "bleeding", "--json", "--home", home, *NO_MODELS, "--set", "llm.model=echo")
    d = json.loads(out)
    assert rc == 0 and d["status"] == "ok" and d["sources"][0]["n"] == 1 and d["citations"][0] == {"n": 1, "valid": True}
    assert {"page", "section", "citation", "module", "path", "text"} <= set(d["sources"][0])


def test_exit_codes(home, capsys):
    assert run(capsys, "ask", "zzzz", "--home", home, *NO_MODELS)[0] == cli.NO_EVIDENCE
    rc, out, _ = run(capsys, "ask", "J18.9", "--home", home, *NO_MODELS)            # llm.model "" -> search only
    assert rc == 0 and "Search-only mode" in out and "[1] codes" in out
    rc, out, err = run(capsys, "ask", "J18.9", "--home", home, *NO_MODELS, "--set", "llm.model=models/none.gguf")
    assert rc == cli.MISSING and "[1] codes" in out and "LLM unavailable" in err
    assert run(capsys, "ask", "x", "-m", "nope", "--home", home, *NO_MODELS)[0] == cli.MISSING
    assert run(capsys, "search", "x", "--home", home, "--set", "bogus.key=1")[0] == cli.USAGE
    with pytest.raises(SystemExit) as e:
        cli.main(["frobnicate"])
    assert e.value.code == cli.USAGE
    assert cli.main([]) == cli.USAGE


def test_no_modules_is_missing(tmp_path, capsys):
    rc, _, err = run(capsys, "ask", "x", "--home", tmp_path, *NO_MODELS)
    assert rc == cli.MISSING and "kovcheg build" in err


def test_search_json_and_text(home, capsys):
    rc, out, _ = run(capsys, "search", "500", "mg", "--json", "--home", home, *NO_MODELS)
    assert rc == 0 and json.loads(out)["sources"][0]["path"] == "pharmacy.txt"


def test_parse_set():
    assert cli.parse_set(["a.b=1", "a.c=true", "d=hello world", "e=[1, 2]", "f="]) == {
        "a": {"b": 1, "c": True}, "d": "hello world", "e": [1, 2], "f": ""}
    with pytest.raises(cli.UsageError):
        cli.parse_set(["novalue"])


def test_init(tmp_path, capsys):
    rc, out, _ = run(capsys, "init", "--home", tmp_path)
    assert rc == 0 and (tmp_path / "kovcheg.toml").exists() and (tmp_path / "keys" / "trusted").is_dir()
    from kovcheg.config import load_settings
    load_settings(tmp_path)                                   # the commented template parses
    assert "unchanged" in run(capsys, "init", "--home", tmp_path)[1]


def test_doctor_text_and_json(home, capsys):
    rc, out, _ = run(capsys, "doctor", "--home", home, *NO_MODELS)
    assert rc == 0 and "optional libraries" in out and "medical" in out and "recommended tier" in out
    rc, out, _ = run(capsys, "doctor", "--json", "--home", home)
    d = json.loads(out)
    assert d["models"]["embedding"]["exists"] is False and {m["name"] for m in d["modules"]} == {"medical", "water"}
    assert cli.recommend(2 * 2**30)["tier"] == "S — search" and cli.recommend(8 * 2**30)["tier"] == "A — mini PC"
    assert cli.recommend(16 * 2**30)["settings"]["rerank.enabled"] is True


def test_doctor_needs_only_numpy(home, tmp_path):
    import subprocess
    code = ("import sys, builtins\n"
            "real = builtins.__import__\n"
            "BAD = {'torch','FlagEmbedding','llama_cpp','streamlit','pdfplumber','pypdf','docx','bs4','libzim','cryptography'}\n"
            "def imp(name, *a, **k):\n"
            "    if name.split('.')[0] in BAD: raise ImportError('blocked ' + name)\n"
            "    return real(name, *a, **k)\n"
            "builtins.__import__ = imp\n"
            "from kovcheg.cli import main\n"
            f"sys.exit(main(['doctor', '--home', {str(home)!r}]))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                       env={"PYTHONPATH": str(cli.Path(cli.__file__).parents[1]), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert "medical" in r.stdout


def test_ui_command(monkeypatch, tmp_path, capsys):
    s = Settings(home=tmp_path)
    cmd = cli.build_ui_command(s)
    i = cmd.index("run")
    assert cmd[i + 1].endswith("ui/app.py") or cmd[i + 1].endswith("ui\\app.py")
    flags = dict(zip(cmd[i + 2::2], cmd[i + 3::2], strict=False))
    assert flags["--server.headless"] == "true" and flags["--server.fileWatcherType"] == "none"
    assert flags["--browser.gatherUsageStats"] == "false" and flags["--server.address"] == "127.0.0.1" and flags["--server.port"] == "8501"
    assert cmd[-2:] == ["--home", str(tmp_path)]
    calls = []
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cli, "subprocess_call", lambda c, env: calls.append((c, env)) or 0)
    assert run(capsys, "ui", "--home", tmp_path, "--port", "9000", "--set", "llm.model=echo")[0] == 0
    c, env = calls[0]
    assert "9000" in c and env["KOVCHEG_HOME"] == str(tmp_path) and json.loads(env["KOVCHEG_OVERRIDES"]) == {"llm": {"model": "echo"}}
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: None)
    assert run(capsys, "ui", "--home", tmp_path)[0] == cli.MISSING


def test_modules_inspect_verify(home, capsys):
    rc, out, _ = run(capsys, "modules", "--home", home)
    assert rc == 0 and "medical" in out and "UNSIGNED" in out
    rc, out, _ = run(capsys, "list", "--json", "--home", home)
    assert {m["name"] for m in json.loads(out)} == {"medical", "water"}
    rc, out, _ = run(capsys, "inspect", "medical", "--home", home)
    assert rc == 0 and "first-aid.md" in out and "kovcheg.db" in out
    assert json.loads(run(capsys, "inspect", "medical", "--json", "--home", home)[1])["chunks"] == 8
    assert run(capsys, "inspect", "nope", "--home", home)[0] == cli.MISSING
    pytest.importorskip("kovcheg.security")
    assert run(capsys, "verify", "--home", home)[0] == 0
    with open(home / "modules" / "water" / "kovcheg.db", "ab") as f:
        f.write(b"x")
    rc, out, _ = run(capsys, "verify", "--home", home)
    assert rc == cli.ERROR and "water: INVALID" in out


def test_eval(home, tmp_path, capsys):
    f = tmp_path / "q.jsonl"
    f.write_text("\n".join([json.dumps({"question": "J18.9", "expected": "codes.txt"}),
                            json.dumps({"question": "paracetamol 500 mg", "expected": ["medical:pharmacy.txt"]}),
                            "# comment", json.dumps({"question": "zzzz", "expected": "codes.txt"})]), encoding="utf-8")
    rc, out, _ = run(capsys, "eval", f, "--json", "--home", home, *NO_MODELS)
    d = json.loads(out)
    assert rc == 0 and d["n"] == 3 and d["hit@1"] == pytest.approx(2 / 3) and d["mrr"] == pytest.approx(2 / 3)
    rc, out, _ = run(capsys, "eval", f, "--home", home, *NO_MODELS)
    assert "MISS" in out and "hit@1 0.667" in out
    f.write_text("not json", encoding="utf-8")
    assert run(capsys, "eval", f, "--home", home)[0] == cli.USAGE


def test_build_keygen_sign_via_cli(tmp_path, capsys):
    pytest.importorskip("kovcheg.builder")
    src = tmp_path / "sources" / "kb"
    src.mkdir(parents=True)
    (src / "a.txt").write_text("Boil water for one minute before drinking.", encoding="utf-8")
    rc, out, err = run(capsys, "build", "kb", "--no-embed", "--title", "Water", "--home", tmp_path, *NO_MODELS, "-q")
    assert rc == 0 and "kb:" in out
    rc, out, _ = run(capsys, "search", "boil", "water", "--home", tmp_path, *NO_MODELS)
    assert rc == 0 and "a.txt" in out
    assert run(capsys, "build", "bad/name", "--home", tmp_path, "--no-embed")[0] == cli.ERROR
    pytest.importorskip("cryptography")
    assert run(capsys, "keygen", "--home", tmp_path)[0] == 0
    assert run(capsys, "keygen", "--home", tmp_path)[0] == cli.ERROR
    assert run(capsys, "sign", "kb", "--home", tmp_path)[0] == 0
    rc, out, _ = run(capsys, "verify", "kb", "--home", tmp_path)
    assert rc == 0 and "VALID" in out
