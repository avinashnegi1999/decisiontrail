"""Independent applicability reducer: plain Python over the fixture JSON.
Shares no code or queries with decisiontrail.py; used to grade it."""


def _rels(fx):
    out = []
    for r in fx["relations"]:
        t, a, b, src, *extra = r.split()
        kv = dict(x.split("=", 1) for x in extra if "=" in x)
        pos = [x for x in extra if "=" not in x]
        out.append((t, a, b, src, pos[0] if pos else None, kv))
    return out


def oracle(fx, project_scope, t, req):
    claims = {p["id"]: set(p["claims"]) for p in fx["passages"]}
    dec = {d["id"]: d for d in fx["decisions"]}
    rels = []
    for t_, a, b, src, extra, kv in _rels(fx):
        claim = f"{a}|{t_}|{b}" + (f"@{extra}" if t_ == "SUPERSEDES" else "")
        if claim not in claims.get(src, ()):
            continue
        if kv.get("end") and f"{claim}|ENDS" in claims.get(kv["end"], ()) and t >= kv["to"]:
            continue  # authority ended by a supported passage before t
        rels.append((t_, a, b, src, extra))
    has = lambda t_, a, b: any(r[0] == t_ and r[1] == a and r[2] == b for r in rels)
    authorized = {(a, b) for t_, a, b, _, _ in rels if t_ == "AUTHORIZED_FOR"}

    def live(d):
        x = dec[d]
        return x["from"] <= t and (x.get("to") is None or t < x["to"])

    adm = [d for d in dec if live(d) and has("APPLIES_TO", d, project_scope) and has("ADDRESSES", d, req)
           and any(r[0] == "APPROVED_BY" and r[1] == d and (r[2], project_scope) in authorized for r in rels)]
    beaten = {r[2] for r in rels if r[0] == "SUPERSEDES" and r[1] in adm and r[4] == project_scope}
    cur = sorted(d for d in adm if d not in beaten)
    if not cur:
        return {"status": "UNKNOWN"}
    if len(cur) > 1:
        return {"status": "CONFLICT", "decisions": cur}
    d = cur[0]
    owners = [(r[4] or "", r[2]) for r in rels if r[0] == "OWNED_BY" and r[1] == d and (r[4] or "") <= t]
    owner = None
    if owners:
        top = max(o[0] for o in owners)
        names = {o[1] for o in owners if o[0] == top}
        owner = names.pop() if len(names) == 1 else None
    return {"status": "ANSWER", "decision": d, "owner": owner,
            "rationale": sorted(r[2] for r in rels if r[0] == "SUPPORTED_BY" and r[1] == d)}
