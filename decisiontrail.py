"""DecisionTrail core: load a curated fixture into FalkorDB and resolve
which decision currently applies, why, and who owns it.

Every relationship edge carries `src` (a passage id). An edge counts only
if that passage's `claims` list contains the relation key, so a passage
that merely mentions two entities cannot bridge them.
"""
import falkordb

HOST, PORT = "localhost", 6379
RELS = {"APPLIES_TO", "SUPERSEDES", "APPROVED_BY", "OWNED_BY", "ADDRESSES", "SUPPORTED_BY", "AUTHORIZED_FOR"}


def key(a, rel, b, scope=None):
    return f"{a}|{rel}|{b}" + (f"@{scope}" if scope else "")


def connect(name):
    return falkordb.FalkorDB(host=HOST, port=PORT).select_graph(name)


def parse_relation(r):
    """'TYPE a b src [extra] [k=v ...]' -> dict. Positional extra is the scope (SUPERSEDES)
    or start date (OWNED_BY); to=/end= mark an authority that ended, per passage `end`."""
    if isinstance(r, dict):
        return r
    t, a, b, src, *extra = r.split()
    d = {"type": t, "a": a, "b": b, "src": src}
    d.update(x.split("=", 1) for x in extra if "=" in x)
    extra = [x for x in extra if "=" not in x]
    if extra:
        d["scope" if t == "SUPERSEDES" else "from"] = extra[0]
    return d


def load(g, fx):
    try:
        g.delete()
    except Exception:
        pass
    q = g.query
    for p in fx["projects"]:
        q("CREATE (:Project {id:$id, name:$name, aliases:$aliases})", {"aliases": [], **p})
    for s in fx["scopes"]:
        q("MATCH (p:Project {id:$project}) CREATE (p)-[:HAS_SCOPE]->(:Scope {id:$id, env:$env})", s)
    for p in fx["people"]:
        q("CREATE (:Person {id:$id, name:$name})", p)
    for r in fx["requirements"]:
        q("MATCH (p:Project {id:$project}) CREATE (p)-[:HAS_REQUIREMENT]->(:Requirement {id:$id, text:$text})", r)
    for p in fx["passages"]:
        q("CREATE (:Passage {id:$id, doc:$doc, rev:$rev, text:$text, claims:$claims})", p)
    for d in fx["decisions"]:
        q("CREATE (:Decision {id:$id, title:$title, from:$from, to:$to})", {"to": None, **d})
    for r in fx["relations"]:
        add_relation(g, parse_relation(r))


def add_relation(g, r):
    t = r["type"]
    assert t in RELS, t
    props = {"SUPERSEDES": "{src:$src, scope:$scope}", "OWNED_BY": "{src:$src, from:$from}",
             "AUTHORIZED_FOR": "{src:$src, to:$to, end:$end}"}.get(t, "{src:$src}")
    g.query(f"MATCH (a {{id:$a}}), (b {{id:$b}}) CREATE (a)-[:{t} {props}]->(b)",
            {"a": r["a"], "b": r["b"], "src": r["src"], "scope": r.get("scope"), "from": r.get("from"),
             "to": r.get("to"), "end": r.get("end")})


# Admissible = in effect at $t, applies to scope, addresses a requirement,
# approved by a person authorized for that scope -- each edge supported by
# its cited passage. Then drop any admissible decision that another
# admissible decision supersedes in this scope (supported).
# (The WITH between passage MATCHes works around a FalkorDB planner error.)
APPLICABLE = """
MATCH (s:Scope {id:$scope})<-[a:APPLIES_TO]-(d:Decision)-[ad:ADDRESSES]->(r:Requirement)
WHERE d.from <= $t AND (d.to IS NULL OR $t < d.to)
MATCH (d)-[b:APPROVED_BY]->(p:Person)-[z:AUTHORIZED_FOR]->(s)
WITH s, r, d, p, a, ad, b, z
MATCH (adp:Passage) WHERE adp.id = ad.src AND d.id+'|ADDRESSES|'+r.id IN adp.claims
WITH s, r, d, p, a, b, z, adp
MATCH (ap:Passage) WHERE ap.id = a.src AND d.id+'|APPLIES_TO|'+s.id IN ap.claims
WITH s, r, d, p, b, z, adp, ap
MATCH (bp:Passage) WHERE bp.id = b.src AND d.id+'|APPROVED_BY|'+p.id IN bp.claims
WITH s, r, d, p, z, adp, ap, bp
MATCH (zp:Passage) WHERE zp.id = z.src AND p.id+'|AUTHORIZED_FOR|'+s.id IN zp.claims
WITH s, r, d, p, z, adp, ap, bp, zp
// authority that a supported later passage ended no longer counts after its end date
OPTIONAL MATCH (ze:Passage) WHERE ze.id = z.end AND p.id+'|AUTHORIZED_FOR|'+s.id+'|ENDS' IN ze.claims
WITH s, r, d, p, adp, ap, bp, zp, ze WHERE ze IS NULL OR $t < z.to
WITH s, r, d, collect(DISTINCT adp.id) + collect(DISTINCT ap.id) + collect(DISTINCT bp.id) + collect(DISTINCT zp.id) AS ev,
     collect(DISTINCT p.id) AS approvers
WITH s, collect({d:d, r:r, ev:ev, approvers:approvers}) AS rows
WITH s, rows, [x IN rows | x.d.id] AS ids
UNWIND rows AS row
WITH s, ids, row, row.d AS d
OPTIONAL MATCH (d2:Decision)-[x:SUPERSEDES]->(d) WHERE x.scope = s.id AND d2.id IN ids
OPTIONAL MATCH (xp:Passage) WHERE xp.id = x.src AND d2.id+'|SUPERSEDES|'+d.id+'@'+s.id IN xp.claims
WITH row, d, count(xp) AS beaten WHERE beaten = 0
RETURN row.r.id AS req, row.r.text AS requirement, d.id AS decision, d.title AS title, d.from AS effective_from,
       row.ev AS evidence, row.approvers AS approvers
ORDER BY req, decision
"""

# Everything that claims to apply here at $t, admissible or not -- so an
# answer can say what it set aside (obsolete, unauthorized, unsupported).
CONSIDERED = """
MATCH (s:Scope {id:$scope})<-[a:APPLIES_TO]-(d:Decision)
WHERE d.from <= $t AND (d.to IS NULL OR $t < d.to)
RETURN DISTINCT d.id AS decision, d.title AS title, d.from AS effective_from ORDER BY decision
"""

OWNER = """
MATCH (d:Decision {id:$d})-[o:OWNED_BY]->(p:Person)
WHERE o.from IS NULL OR o.from <= $t
WITH d, o, p
MATCH (op:Passage) WHERE op.id = o.src AND d.id+'|OWNED_BY|'+p.id IN op.claims
RETURN p.id AS person, p.name AS name, o.from AS since, op.id AS passage ORDER BY person
"""

RATIONALE = """
MATCH (d:Decision {id:$d})-[e:SUPPORTED_BY]->(p:Passage)
WITH d, e, p
MATCH (ep:Passage) WHERE ep.id = e.src AND d.id+'|SUPPORTED_BY|'+p.id IN ep.claims
RETURN p.id AS passage, p.doc AS doc, p.rev AS rev, p.text AS text, ep.id AS cited_by ORDER BY passage
"""

REPLACED = """
MATCH (d:Decision {id:$d})-[x:SUPERSEDES]->(old:Decision)
WITH d, x, old
MATCH (xp:Passage) WHERE xp.id = x.src AND d.id+'|SUPERSEDES|'+old.id+'@'+x.scope IN xp.claims
RETURN old.id AS replaced, old.title AS title, x.scope AS scope, xp.id AS passage ORDER BY replaced
"""

PROJECT = """
MATCH (p:Project)-[:HAS_SCOPE]->(s:Scope)
WHERE toLower(p.name) = toLower($name) OR toLower($name) IN p.aliases OR p.id = toLower($name)
RETURN p.id AS project, p.name AS name, collect({scope:s.id, env:s.env}) AS scopes
"""


def rows(g, q, params):
    res = g.query(q, params)
    cols = [c[1] if isinstance(c, (list, tuple)) else c for c in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]


# ---- agent tools (all read-only Cypher) ----

def resolve_project(g, name):
    found = rows(g, PROJECT, {"name": name.strip()})
    return found[0] if len(found) == 1 else {"error": f"no unique project named {name!r}", "matches": found}


def applicable_decisions(g, scope, t):
    adm = rows(g, APPLICABLE, {"scope": scope, "t": t})
    ids = {r["decision"] for r in adm}
    set_aside = [c for c in rows(g, CONSIDERED, {"scope": scope, "t": t}) if c["decision"] not in ids]
    for r in adm:
        r["evidence"] = sorted(set(r["evidence"]))
    return {"scope": scope, "t": t, "applicable": adm, "set_aside": set_aside}


def trace_rationale(g, d):
    return {"decision": d, "rationale": rows(g, RATIONALE, {"d": d}), "replaces": rows(g, REPLACED, {"d": d})}


def read_passage(g, pid):
    found = rows(g, "MATCH (p:Passage {id:$id}) RETURN p.id AS id, p.doc AS doc, p.rev AS rev, p.text AS text", {"id": pid})
    return found[0] if found else {"error": f"no passage {pid}"}


def resolve_owner(g, d, t):
    own = rows(g, OWNER, {"d": d, "t": t})
    if not own:
        return {"decision": d, "owner": None, "reason": "no supported owner"}
    latest = max(o["since"] or "" for o in own)
    top = [o for o in own if (o["since"] or "") == latest]
    if len({o["person"] for o in top}) > 1:
        return {"decision": d, "owner": None, "reason": "conflicting owners", "candidates": top}
    return {"decision": d, "owner": top[0]["person"], "name": top[0]["name"], "passage": top[0]["passage"]}


def resolve(g, scope, t, req):
    """Deterministic answer for (scope, time, requirement) built from the tools above."""
    cands = [r for r in applicable_decisions(g, scope, t)["applicable"] if r["req"] == req]
    if not cands:
        return {"status": "UNKNOWN", "reason": "no admissible decision"}
    if len(cands) > 1:
        return {"status": "CONFLICT", "decisions": [c["decision"] for c in cands],
                "reason": "equally authoritative active decisions"}
    c = cands[0]
    own = resolve_owner(g, c["decision"], t)
    rat = trace_rationale(g, c["decision"])
    return {"status": "ANSWER", "decision": c["decision"], "owner": own["owner"],
            "rationale": [p["passage"] for p in rat["rationale"]],
            "evidence": sorted(set(c["evidence"]) | ({own["passage"]} if own.get("passage") else set()))}


def admissible_citations(g, scope, t, d):
    """Passages an answer about decision d may cite: its applicability, owner, rationale and replacement chain."""
    adm = [r for r in applicable_decisions(g, scope, t)["applicable"] if r["decision"] == d]
    if not adm:
        return set()
    own = resolve_owner(g, d, t)
    rat = trace_rationale(g, d)
    return (set(adm[0]["evidence"]) | {p["passage"] for p in rat["rationale"]} | {p["cited_by"] for p in rat["rationale"]}
            | {r["passage"] for r in rat["replaces"]} | ({own["passage"]} if own.get("passage") else set()))
