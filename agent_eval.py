"""Paid agent eval on a few held-out cases, graph tools vs flat index, same model,
prompt, turn budget and validator. Hard cap on total model requests.
Run: python agent_eval.py h04 h01 ...   (writes results/agent_eval.json)"""
import json, sys
from pathlib import Path

import agent, decisiontrail as dt, eval as ev

CAP = 120
HERE = Path(__file__).parent

fx = ev.heldout_fixture(json.loads((HERE / "fixture.json").read_text()), json.loads((HERE / "heldout.json").read_text()))
g = dt.connect("dt_eval_support")
dt.load(g, fx)
used, out = 0, []
for cid in sys.argv[1:]:
    c = next(c for c in fx["cases"] if c["id"] == cid)
    scope = ev.scope_for(fx, c["project"], c["env"])
    for mode in ("graph", "flat"):
        if used + agent.MAX_TURNS > CAP:
            print("request cap reached; stopping")
            break
        r = agent.run(c, fx, mode, emit=lambda e: None)
        used += r["usage"]["requests"]
        a = r["answer"] or {"status": "NONE"}
        got = {"status": a["status"], "decision": a.get("decision"), "decisions": a.get("decisions"),
               "owner": a.get("owner"), "rationale": [p for p in a.get("cited_passages") or []
                                                       if p in c["expect"].get("rationale", [])]}
        grade = ev.grade(got, c["expect"])
        cited = set(a.get("cited_passages") or [])
        support = dt.admissible_citations(g, scope, c["t"], a.get("decision")) if a.get("decision") else set()
        row = {"case": cid, "mode": mode, "answer": a, "correct": grade["all"], "grade": grade,
               "unsupported_citations": sorted(cited - support) if a["status"] == "ANSWER" else [],
               "usage": r["usage"]}
        out.append(row)
        print(f"{cid} {mode:5} correct={grade['all']} status={a['status']} decision={a.get('decision') or a.get('decisions')} "
              f"owner={a.get('owner')} cited={sorted(cited)} unsupported={row['unsupported_citations']} usage={r['usage']}")
tot = {k: sum(r["usage"][k] for r in out) for k in ("requests", "in", "out")}
print("total usage", tot)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "agent_eval.json").write_text(json.dumps({"total_usage": tot, "runs": out}, indent=1))
