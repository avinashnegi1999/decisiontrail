"""Deterministic eval: graph resolver vs matched flat baseline, graded against
an authored answer ledger that must also agree with the independent oracle.
No model calls.  Run: python eval.py   (writes results/eval.json)"""
import copy, json, os
from pathlib import Path

import baseline, decisiontrail as dt
from oracle import oracle

HERE = Path(__file__).parent


def heldout_fixture(dev, spec):
    """Apply held-out mutations (renames, new/removed relations, new passages) to the dev fixture."""
    fx = copy.deepcopy(dev)
    for m in spec["mutations"]:
        op = m["op"]
        if op == "rename_project":
            p = next(p for p in fx["projects"] if p["id"] == m["id"])
            p["aliases"] = p.get("aliases", []) + [p["name"].lower()]
            p["name"] = m["name"]
        elif op == "add_passage":
            fx["passages"].append(m["passage"])
        elif op == "replace_passage":
            fx["passages"] = [m["passage"] if p["id"] == m["passage"]["id"] else p for p in fx["passages"]]
        elif op == "add_decision":
            fx["decisions"].append(m["decision"])
        elif op == "add_relation":
            fx["relations"].append(m["relation"])
        elif op == "remove_relation":
            fx["relations"].remove(m["relation"])
        else:
            raise ValueError(op)
    fx["cases"] = spec["cases"]
    return fx


def scope_for(fx, name, env):
    n = name.lower()
    p = next(p for p in fx["projects"] if p["name"].lower() == n or n in p.get("aliases", []))
    return next(s["id"] for s in fx["scopes"] if s["project"] == p["id"] and s["env"] == env)


def grade(got, exp):
    s = {"status": got["status"] == exp["status"]}
    if exp["status"] == "ANSWER":
        s["decision"] = got.get("decision") == exp["decision"]
        s["owner"] = got.get("owner") == exp["owner"]
        s["rationale"] = sorted(got.get("rationale") or []) == sorted(exp["rationale"])
    elif exp["status"] == "CONFLICT":
        s["decision"] = sorted(got.get("decisions") or []) == sorted(exp["decisions"])
    s["wrong_answer"] = got["status"] == "ANSWER" and got.get("decision") != exp.get("decision")
    s["all"] = all(v for k, v in s.items() if k != "wrong_answer") and not s["wrong_answer"]
    return s


def run_split(name, fx):
    g = dt.connect(f"dt_eval_{name}")
    dt.load(g, fx)
    out = []
    for c in fx["cases"]:
        scope = dt.resolve_project(g, c["project"])
        scope_id = next(s["scope"] for s in scope["scopes"] if s["env"] == c["env"])
        assert scope_id == scope_for(fx, c["project"], c["env"])
        orc = oracle(fx, scope_id, c["t"], c["req"])
        ledger_ok = all(orc.get(k) == v for k, v in c["expect"].items())
        graph = dt.resolve(g, scope_id, c["t"], c["req"])
        flat = baseline.answer(fx, scope_id, c["t"], c["req"])
        out.append({"id": c["id"], "scope": scope_id, "t": c["t"], "req": c["req"], "expect": c["expect"],
                    "ledger_agrees_with_oracle": ledger_ok, "graph": graph, "baseline": flat,
                    "graph_grade": grade(graph, c["expect"]), "baseline_grade": grade(flat, c["expect"])})
    return out


def summary(rows, who):
    n = len(rows)
    g = [r[f"{who}_grade"] for r in rows]
    ans = [x for x, r in zip(g, rows) if r["expect"]["status"] == "ANSWER"]
    abst = [x for x, r in zip(g, rows) if r["expect"]["status"] != "ANSWER"]
    return {"cases_fully_correct": f"{sum(x['all'] for x in g)}/{n}",
            "status_correct": f"{sum(x['status'] for x in g)}/{n}",
            "current_decision_correct": f"{sum(x['decision'] for x in ans)}/{len(ans)}",
            "owner_correct": f"{sum(x['owner'] for x in ans)}/{len(ans)}",
            "rationale_passages_exact": f"{sum(x['rationale'] for x in ans)}/{len(ans)}",
            "wrong_or_obsolete_answers": sum(x["wrong_answer"] for x in g),
            "correct_abstention": f"{sum(x['status'] for x in abst)}/{len(abst)}"}


if __name__ == "__main__":
    dev = json.loads((HERE / "fixture.json").read_text())
    splits = {"dev": dev}
    if (HERE / "heldout.json").exists():
        splits["heldout"] = heldout_fixture(dev, json.loads((HERE / "heldout.json").read_text()))
    report = {}
    for name, fx in splits.items():
        rows = run_split(name, fx)
        bad = [r["id"] for r in rows if not r["ledger_agrees_with_oracle"]]
        report[name] = {"ledger_vs_oracle_disagreements": bad,
                        "graph": summary(rows, "graph"), "baseline": summary(rows, "baseline"), "cases": rows}
        print(f"== {name}: {len(rows)} cases, ledger/oracle disagreements: {bad or 'none'}")
        for who in ("graph", "baseline"):
            print(f"   {who:8} {report[name][who]}")
        for r in rows:
            if not r["graph_grade"]["all"] or not r["baseline_grade"]["all"]:
                print(f"   {r['id']} {r['scope']} @{r['t']} expect={r['expect']}\n"
                      f"      graph={ {k: v for k, v in r['graph'].items() if k != 'evidence'} }\n      baseline={r['baseline']}")
    os.makedirs(HERE / "results", exist_ok=True)
    (HERE / "results" / "eval.json").write_text(json.dumps(report, indent=1))
