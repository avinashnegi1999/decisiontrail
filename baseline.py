"""Matched baseline: a flat, structured passage index (could be one SQL table)
with the same durable facts and the same authority/scope guard, but no
relationship traversal. Rule: newest authorized passage for the topic and
environment wins. Kept deliberately honest -- it is what a good retrieval
system with metadata filters does."""
import re

ENV_WORDS = {"production": "production", "staging": "staging"}


def index(fx):
    """One row per passage: project, effective date, envs named in the text,
    topic, approver, owner -- all from the same curated fixture."""
    dec = {d["id"]: d for d in fx["decisions"]}
    claims = [c for p in fx["passages"] for c in p["claims"] if "|AUTHORIZED_FOR|" in c]
    ended = {c[:-len("|ENDS")] for c in claims if c.endswith("|ENDS")}  # current charter only
    auth = {(c.split("|")[0], c.split("|")[2]) for c in claims if not c.endswith("|ENDS") and c not in ended}
    scope_env = {s["id"]: (s["project"], s["env"]) for s in fx["scopes"]}
    rows = []
    for p in fx["passages"]:
        get = lambda rel: [c.split("|")[2] for c in p["claims"] if f"|{rel}|" in c]
        subj = {c.split("|")[0] for c in p["claims"] if c.split("|")[0] in dec}
        eff = max([dec[d]["from"] for d in subj] or [p["date"]])
        approver = (get("APPROVED_BY") or [None])[0]
        rows.append({"id": p["id"], "project": p["project"], "effective": eff, "doc": p["doc"], "text": p["text"],
                     "envs": {e for w, e in ENV_WORDS.items() if re.search(w, p["text"], re.I)},
                     "topic": (get("ADDRESSES") or [None])[0], "decision": (sorted(subj) or [None])[0],
                     "approver": approver, "owner": (get("OWNED_BY") or [None])[0],
                     "approver_scopes": {scope_env[s][1] for a, s in auth if a == approver and s in scope_env
                                         and scope_env[s][0] == p["project"]}})
    return rows


def search(rows, project, env, t, topic):
    hits = [r for r in rows if r["project"] == project and r["topic"] == topic and env in r["envs"]
            and r["effective"] <= t and env in r["approver_scopes"]]
    return sorted(hits, key=lambda r: r["effective"], reverse=True)


def answer(fx, scope, t, req):
    project, env = next((s["project"], s["env"]) for s in fx["scopes"] if s["id"] == scope)
    hits = search(index(fx), project, env, t, req)
    if not hits:
        return {"status": "UNKNOWN"}
    top = hits[0]
    return {"status": "ANSWER", "decision": top["decision"], "owner": top["owner"], "rationale": [top["id"]]}
