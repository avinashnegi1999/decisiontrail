"""Demo UI: python server.py, then open http://localhost:8001
Answers come from the FalkorDB tools (no model call), so the page is free to run.

GET /api/cases            dev + held-out questions
GET /api/answer?w=&c=     answer, evidence chain and set-aside decisions for one case
"""
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import decisiontrail as dt
import eval as ev

HERE = Path(__file__).parent
DEV = json.loads((HERE / "fixture.json").read_text())
WORLDS = {"dev": DEV, "heldout": ev.heldout_fixture(DEV, json.loads((HERE / "heldout.json").read_text()))}
GRAPHS = {}
for w, fx in WORLDS.items():
    GRAPHS[w] = dt.connect(f"dt_ui_{w}")
    dt.load(GRAPHS[w], fx)


def explain(w, cid):
    fx, g = WORLDS[w], GRAPHS[w]
    c = next(c for c in fx["cases"] if c["id"] == cid)
    scope = next(s["scope"] for s in dt.resolve_project(g, c["project"])["scopes"] if s["env"] == c["env"])
    ans = dt.resolve(g, scope, c["t"], c["req"])
    app = dt.applicable_decisions(g, scope, c["t"])
    out = {"case": c, "scope": scope, "answer": ans,
           "applicable": [a for a in app["applicable"] if a["req"] == c["req"]], "set_aside": app["set_aside"]}
    if ans["status"] == "ANSWER":
        out["rationale"] = dt.trace_rationale(g, ans["decision"])
        out["owner"] = dt.resolve_owner(g, ans["decision"], c["t"])
        out["passages"] = [dt.read_passage(g, p) for p in ans["evidence"]]
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE / "static"), **kw)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/cases":
            return self._json({w: [{"id": c["id"], "q": c["q"]} for c in fx["cases"]] for w, fx in WORLDS.items()})
        if url.path == "/api/answer":
            try:
                return self._json(explain(q.get("w", "dev"), q.get("c", "")))
            except (KeyError, StopIteration):
                return self._json({"error": "unknown case"}, 404)
        return super().do_GET()


if __name__ == "__main__":
    print("DecisionTrail demo on http://localhost:8001")
    ThreadingHTTPServer(("127.0.0.1", 8001), Handler).serve_forever()
