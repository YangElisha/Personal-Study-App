"""tools/check_secrets.py finds what it should (test strings are built at runtime, so this
file itself never contains a secret-shaped string)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_secrets", Path(__file__).resolve().parents[2] / "tools" / "check_secrets.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def test_detects():
    x = "Ab1" * 14
    hits = {
        "sk-" + "ant-api03-" + x: "Anthropic",
        "GOC" + "SPX-" + x: "client secret",
        "AI" + "za" + x[:35]: "Google API key",
        "-----BEGIN " + "RSA PRIVATE KEY-----": "private key",
        "GOOGLE_CLIENT_" + "SECRET=" + x: "GOOGLE_CLIENT_SECRET",
        "ANTHROPIC_" + "API_KEY=" + x: "ANTHROPIC_API_KEY",
    }
    for line, what in hits.items():
        assert any(what in f for f in cs.scan_line(line, {})), line
    assert any(".env" in f for f in cs.scan_line("abc " + x, {"GOOGLE_CLIENT_SECRET": x}))


def test_ignores_placeholders():
    for line in ("GOOGLE_CLIENT_" + "SECRET=", "GOOGLE_CLIENT_" + "SECRET=<from the console>",
                 "monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'x')", "code_verifier=abc"):
        assert cs.scan_line(line, {}) == [], line
