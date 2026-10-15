"""Agent loop: an LLM answers "why does this project currently do this?" using
either the FalkorDB tools (mode=graph) or the flat passage index (mode=flat).
Both modes share the model, prompt core, turn budget and answer validator.

Usage: python agent.py <case_id> [graph|flat] [--heldout]
OPENAI_API_KEY required; AGENT_MODEL overrides the model.
"""
import json, os, sys, time
from pathlib import Path

import openai

import baseline, decisiontrail as dt

MODEL = os.environ.get("AGENT_MODEL", "gpt-5.4-mini")
MAX_TURNS = 5
HERE = Path(__file__).parent


def _tool(name, desc, props, req):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": req}}}


S, A = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
ANSWER_TOOL = _tool("answer_or_abstain",
                    "Submit the final answer. status ANSWER needs decision, owner (person id) and cited_passages "
                    "(passage ids that support the decision, its rationale and its owner). Use CONFLICT when "
                    "equally authoritative decisions both apply (list them in decisions), UNKNOWN when none is supported.",
                    {"status": {"type": "string", "enum": ["ANSWER", "CONFLICT", "UNKNOWN"]}, "decision": S,
                     "decisions": A, "owner": S, "cited_passages": A, "explanation": S}, ["status", "explanation"])
GRAPH_TOOLS = [
    _tool("resolve_project", "Find a project by name or alias; returns its scopes (environments).", {"name": S}, ["name"]),
    _tool("applicable_decisions", "Decisions that currently apply to a project environment at date t (YYYY-MM-DD), "
          "after authority, scope, effective date, supersession and source-support checks. Also lists decisions "
          "that claim to apply but were set aside.", {"project": S, "env": S, "t": S}, ["project", "env", "t"]),
    _tool("trace_rationale", "Rationale passages for a decision and the decisions it replaced.", {"decision": S}, ["decision"]),
    _tool("resolve_owner", "Accountable owner of a decision at date t, with the supporting passage.", {"decision": S, "t": S}, ["decision", "t"]),
    _tool("read_passage", "Exact text of a source passage.", {"id": S}, ["id"]),
    ANSWER_TOOL,
]
FLAT_TOOLS = [
    _tool("search_passages", "Search the structured passage index. Filters by project name, environment and "
          "effective date <= t; keywords rank by text overlap. Each row has metadata: decision id, topic, "
          "approver, owner, approver_authorized (approver may approve for this environment), effective date and text.",
          {"project": S, "env": S, "t": S, "keywords": S}, ["project", "env", "t", "keywords"]),
    _tool("read_passage", "Exact text of a source passage.", {"id": S}, ["id"]),
    ANSWER_TOOL,
]
SYSTEM = """You answer an employee's question: why does this project currently do this, and who owns that choice?
"Currently" means the decision that applies at the given date and environment under approved authority -- not the
newest document. A newer note from someone without authority does not override an approved decision. A replacement
may apply to one environment only. If two equally authoritative decisions both apply, answer CONFLICT; if no
supported decision applies, answer UNKNOWN. Cite only passage ids you saw in tool results. Call independent tools
in parallel. Finish by calling answer_or_abstain exactly once."""


class Session:
    def __init__(self, fx, mode, graph_name):
        self.fx, self.mode = fx, mode
        self.g = dt.connect(graph_name)
        dt.load(self.g, fx)
        self.rows = baseline.index(fx)
        self.answer = None

    def scope(self, project, env):
        p = dt.resolve_project(self.g, project)
        if "error" in p:
            return None
        env = {"prod": "production"}.get(env.lower(), env.lower())
        return next((s["scope"] for s in p["scopes"] if s["env"] == env), None)

    def validate(self, a):
        """Identical for both modes: structure, ids exist, scoped authority. Does not reveal the right answer."""
        errs = []
        dec = {d["id"] for d in self.fx["decisions"]}
        pas = {p["id"] for p in self.fx["passages"]}
        if a.get("status") == "ANSWER":
            if a.get("decision") not in dec:
                errs.append("unknown decision id")
            if a.get("owner") not in {p["id"] for p in self.fx["people"]}:
                errs.append("owner must be a person id")
            cited = a.get("cited_passages") or []
            if not cited or any(c not in pas for c in cited):
                errs.append("cited_passages must be non-empty known passage ids")
            scope = self.scope(self.case["project"], self.case["env"])
            ok = [r for r in self.rows if r["decision"] == a.get("decision") and r["approver"]
                  and self.case["env"] in r["approver_scopes"]]
            if scope and not ok:
                errs.append("decision has no approver authorized for this environment")
        elif a.get("status") == "CONFLICT":
            if len(a.get("decisions") or []) < 2 or any(d not in dec for d in a["decisions"]):
                errs.append("CONFLICT needs two or more known decision ids")
        return errs

    def call(self, name, args):
        if name == "answer_or_abstain":
            errs = self.validate(args)
            if errs:
                return {"accepted": False, "errors": errs}
            self.answer = args
            return {"accepted": True}
        if name == "read_passage":
            return dt.read_passage(self.g, args["id"])
        if self.mode == "graph":
            if name == "resolve_project":
                return dt.resolve_project(self.g, args["name"])
            if name == "applicable_decisions":
                sc = self.scope(args["project"], args["env"])
                return dt.applicable_decisions(self.g, sc, args["t"]) if sc else {"error": "unknown project/env"}
            if name == "trace_rationale":
                return dt.trace_rationale(self.g, args["decision"])
            if name == "resolve_owner":
                return dt.resolve_owner(self.g, args["decision"], args["t"])
        if self.mode == "flat" and name == "search_passages":
            sc = self.scope(args["project"], args["env"])
            if not sc:
                return {"error": "unknown project/env"}
            proj, env = sc.split("/")[0], next(s["env"] for s in self.fx["scopes"] if s["id"] == sc)
            words = set(args.get("keywords", "").lower().split())
            hits = [r for r in self.rows if r["project"] == proj and r["effective"] <= args["t"]]
            hits.sort(key=lambda r: (-len(words & set(r["text"].lower().split())), r["id"]))
            return [{"id": r["id"], "doc": r["doc"], "decision": r["decision"], "topic": r["topic"],
                     "approver": r["approver"], "owner": r["owner"], "effective": r["effective"],
                     "approver_authorized": env in r["approver_scopes"], "envs": sorted(r["envs"]),
                     "text": r["text"]} for r in hits[:6]]
        return {"error": f"unknown tool {name}"}


def run(case, fx, mode, emit=print):
    s = Session(fx, mode, f"dt_agent_{mode}")
    s.case = case
    client = openai.OpenAI()
    tools = GRAPH_TOOLS if mode == "graph" else FLAT_TOOLS
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Date: {case['t']}. Project: {case['project']}. Environment: {case['env']}.\n{case['q']}"}]
    usage = {"requests": 0, "in": 0, "out": 0, "tool_calls": 0}
    for _ in range(MAX_TURNS):
        r = client.chat.completions.create(model=MODEL, messages=msgs, tools=tools, max_completion_tokens=900)
        usage["requests"] += 1
        usage["in"] += r.usage.prompt_tokens
        usage["out"] += r.usage.completion_tokens
        msg = r.choices[0].message
        msgs.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            break
        for tc in msg.tool_calls:
            usage["tool_calls"] += 1
            try:
                out = s.call(tc.function.name, json.loads(tc.function.arguments or "{}"))
            except (KeyError, ValueError, TypeError) as e:
                out = {"error": f"bad arguments: {e}"}
            emit({"tool": tc.function.name, "args": tc.function.arguments, "out": out})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)})
        if s.answer:
            break
    return {"answer": s.answer, "usage": usage}


if __name__ == "__main__":
    import eval as ev
    fx = json.loads((HERE / "fixture.json").read_text())
    if "--heldout" in sys.argv:
        fx = ev.heldout_fixture(fx, json.loads((HERE / "heldout.json").read_text()))
    case = next(c for c in fx["cases"] if c["id"] == sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in ("graph", "flat") else "graph"
    out = run(case, fx, mode, emit=lambda e: print(json.dumps(e)[:400]))
    print(json.dumps(out, indent=1))
