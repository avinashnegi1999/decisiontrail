"""60-minute feasibility gate. Deterministic, real FalkorDB, no model calls.
Run: python gate.py   -> prints trace + PASS/FAIL, writes results/gate_trace.json
"""
import json, os
import decisiontrail as dt

K = dt.key
FX = {
    "projects": [{"id": "harbor", "name": "Harbor"}],
    "scopes": [{"id": "harbor/prod", "project": "harbor", "env": "production"},
               {"id": "harbor/staging", "project": "harbor", "env": "staging"}],
    "people": [{"id": "ana", "name": "Ana Ruiz"}, {"id": "ben", "name": "Ben Okafor"},
               {"id": "cal", "name": "Cal Mendes"}],
    "requirements": [{"id": "R1", "project": "harbor", "text": "How customer data is exported"}],
    "passages": [
        {"id": "P0", "doc": "Harbor governance charter", "rev": "r3",
         "text": "Ana Ruiz approves architecture for Harbor production and staging. Ben Okafor approves architecture for Harbor production.",
         "claims": [K("ana", "AUTHORIZED_FOR", "harbor/prod"), K("ana", "AUTHORIZED_FOR", "harbor/staging"),
                    K("ben", "AUTHORIZED_FOR", "harbor/prod")]},
        {"id": "P1", "doc": "Harbor architecture page", "rev": "r7",
         "text": "ADR-1: Harbor exports customer data in real time in production and staging. Approved and owned by Ana Ruiz.",
         "claims": [K("D1", "APPLIES_TO", "harbor/prod"), K("D1", "APPLIES_TO", "harbor/staging"),
                    K("D1", "APPROVED_BY", "ana"), K("D1", "OWNED_BY", "ana"), K("D1", "ADDRESSES", "R1"),
                    K("D1", "SUPPORTED_BY", "P1")]},
        {"id": "P2", "doc": "ADR-2 nightly exports", "rev": "r1",
         "text": "ADR-2: From 2025-06-01 Harbor production exports customer data nightly, replacing ADR-1 for production only. Approved and owned by Ben Okafor. See incident INC-42.",
         "claims": [K("D2", "APPLIES_TO", "harbor/prod"), K("D2", "SUPERSEDES", "D1", "harbor/prod"),
                    K("D2", "APPROVED_BY", "ben"), K("D2", "OWNED_BY", "ben"), K("D2", "ADDRESSES", "R1"),
                    K("D2", "SUPPORTED_BY", "P3")]},
        {"id": "P3", "doc": "INC-42 postmortem", "rev": "r2",
         "text": "INC-42: real-time export saturated the production database during peak load. Staging was unaffected. Batch exports remove the peak.",
         "claims": []},
        {"id": "P4", "doc": "Team chat note", "rev": "r1",
         "text": "Cal: from 2025-09-01 let's switch production back to real-time exports, replacing ADR-2. I approve this and own it.",
         "claims": [K("N1", "APPLIES_TO", "harbor/prod"), K("N1", "SUPERSEDES", "D2", "harbor/prod"),
                    K("N1", "APPROVED_BY", "cal"), K("N1", "ADDRESSES", "R1"), K("N1", "OWNED_BY", "cal")]},
    ],
    "decisions": [{"id": "D1", "title": "Real-time exports", "from": "2025-01-01"},
                  {"id": "D2", "title": "Nightly exports", "from": "2025-06-01"},
                  {"id": "N1", "title": "Return to real-time exports", "from": "2025-09-01"}],
    "relations": [
        {"type": "AUTHORIZED_FOR", "a": "ana", "b": "harbor/prod", "src": "P0"},
        {"type": "AUTHORIZED_FOR", "a": "ana", "b": "harbor/staging", "src": "P0"},
        {"type": "AUTHORIZED_FOR", "a": "ben", "b": "harbor/prod", "src": "P0"},
        {"type": "APPLIES_TO", "a": "D1", "b": "harbor/prod", "src": "P1"},
        {"type": "APPLIES_TO", "a": "D1", "b": "harbor/staging", "src": "P1"},
        {"type": "APPROVED_BY", "a": "D1", "b": "ana", "src": "P1"},
        {"type": "OWNED_BY", "a": "D1", "b": "ana", "src": "P1"},
        {"type": "ADDRESSES", "a": "D1", "b": "R1", "src": "P1"},
        {"type": "SUPPORTED_BY", "a": "D1", "b": "P1", "src": "P1"},
        {"type": "APPLIES_TO", "a": "D2", "b": "harbor/prod", "src": "P2"},
        {"type": "SUPERSEDES", "a": "D2", "b": "D1", "src": "P2", "scope": "harbor/prod"},
        {"type": "APPROVED_BY", "a": "D2", "b": "ben", "src": "P2"},
        {"type": "OWNED_BY", "a": "D2", "b": "ben", "src": "P2"},
        {"type": "ADDRESSES", "a": "D2", "b": "R1", "src": "P2"},
        {"type": "SUPPORTED_BY", "a": "D2", "b": "P3", "src": "P2"},
        # newer, unauthorized: cal holds no AUTHORIZED_FOR edge
        {"type": "APPLIES_TO", "a": "N1", "b": "harbor/prod", "src": "P4"},
        {"type": "SUPERSEDES", "a": "N1", "b": "D2", "src": "P4", "scope": "harbor/prod"},
        {"type": "APPROVED_BY", "a": "N1", "b": "cal", "src": "P4"},
        {"type": "ADDRESSES", "a": "N1", "b": "R1", "src": "P4"},
        {"type": "OWNED_BY", "a": "N1", "b": "cal", "src": "P4"},
    ],
}

# Phase B mutations: an equally authoritative conflicting decision, plus
# two unsupported relations whose cited passages do not assert them.
P5 = {"id": "P5", "doc": "ADR-3 weekly exports", "rev": "r1",
      "text": "ADR-3: From 2025-08-01 Harbor production exports customer data weekly. Approved and owned by Ben Okafor.",
      "claims": [K("D3", "APPLIES_TO", "harbor/prod"), K("D3", "APPROVED_BY", "ben"),
                 K("D3", "OWNED_BY", "ben"), K("D3", "ADDRESSES", "R1")]}
D3 = {"id": "D3", "title": "Weekly exports", "from": "2025-08-01"}
B_REL = [
    {"type": "APPLIES_TO", "a": "D3", "b": "harbor/prod", "src": "P5"},
    {"type": "APPROVED_BY", "a": "D3", "b": "ben", "src": "P5"},
    {"type": "OWNED_BY", "a": "D3", "b": "ben", "src": "P5"},
    {"type": "ADDRESSES", "a": "D3", "b": "R1", "src": "P5"},
    # false bridge: P3 mentions staging and nightly batch, but asserts neither link
    {"type": "APPLIES_TO", "a": "D2", "b": "harbor/staging", "src": "P3"},
    {"type": "SUPERSEDES", "a": "D2", "b": "D1", "src": "P3", "scope": "harbor/staging"},
    # unsupported owner: P2 is about D2, not D1's ownership
    {"type": "OWNED_BY", "a": "D1", "b": "cal", "src": "P2"},
]

# Expected ledger, authored by hand independently of the queries.
EXPECTED = {
    "A": [
        ("harbor/prod", "2025-10-01", {"status": "ANSWER", "decision": "D2", "owner": "ben", "rationale": ["P3"]}),
        ("harbor/staging", "2025-10-01", {"status": "ANSWER", "decision": "D1", "owner": "ana", "rationale": ["P1"]}),
        ("harbor/prod", "2025-03-01", {"status": "ANSWER", "decision": "D1", "owner": "ana", "rationale": ["P1"]}),
    ],
    "B": [
        ("harbor/prod", "2025-10-01", {"status": "CONFLICT", "decisions": ["D2", "D3"]}),
        ("harbor/staging", "2025-10-01", {"status": "ANSWER", "decision": "D1", "owner": "ana", "rationale": ["P1"]}),
        ("harbor/prod", "2025-07-01", {"status": "ANSWER", "decision": "D2", "owner": "ben", "rationale": ["P3"]}),
    ],
}


def run_phase(g, phase):
    out = []
    for scope, t, exp in EXPECTED[phase]:
        got = dt.resolve(g, scope, t, "R1")
        ok = all(got.get(k) == v for k, v in exp.items())
        out.append({"phase": phase, "scope": scope, "t": t, "expected": exp, "got": got,
                    "raw_applicable": dt.applicable_decisions(g, scope, t)["applicable"], "ok": ok})
    return out


def run():
    g = dt.connect("dt_gate")
    dt.load(g, FX)
    trace = run_phase(g, "A")
    g.query("CREATE (:Passage {id:$id, doc:$doc, rev:$rev, text:$text, claims:$claims})", P5)
    g.query("CREATE (:Decision {id:$id, title:$title, from:$from, to:null})", D3)
    for r in B_REL:
        dt.add_relation(g, r)
    trace += run_phase(g, "B")
    return trace


if __name__ == "__main__":
    t1, t2 = run(), run()
    strip = lambda tr: json.dumps(tr, sort_keys=True)
    fails = [f"{x['phase']} {x['scope']} @{x['t']}: expected {x['expected']} got {x['got']}" for x in t1 if not x["ok"]]
    # kill conditions, checked explicitly
    flat = strip(t1)
    if '"decision": "N1"' in flat:
        fails.append("KILL: newer unauthorized note N1 won")
    if any(x["scope"] == "harbor/staging" and x["got"].get("decision") == "D2" for x in t1):
        fails.append("KILL: unsupported staging bridge survived")
    if any(x["got"].get("owner") == "cal" for x in t1):
        fails.append("KILL: unsupported owner edge survived")
    if not any(x["got"]["status"] == "CONFLICT" for x in t1):
        fails.append("KILL: conflict did not produce UNKNOWN/CONFLICT")
    if strip(t1) != strip(t2):
        fails.append("KILL: paths not reproducible across runs")
    for x in t1:
        print(f"[{'ok ' if x['ok'] else 'BAD'}] {x['phase']} {x['scope']:15} @{x['t']} -> {x['got']}")
        for r in x["raw_applicable"]:
            print(f"        applicable row: {r}")
    os.makedirs("results", exist_ok=True)
    with open("results/gate_trace.json", "w") as f:
        json.dump({"queries": {"APPLICABLE": dt.APPLICABLE, "OWNER": dt.OWNER, "RATIONALE": dt.RATIONALE},
                   "trace": t1, "failures": fails}, f, indent=1)
    print("FAILURES:", fails or "none")
    print("GATE", "PASS" if not fails else "FAIL")
