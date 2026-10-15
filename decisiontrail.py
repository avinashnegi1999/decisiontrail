"""DecisionTrail core: load a curated fixture into FalkorDB and resolve
which decision currently applies, why, and who owns it.

Every relationship edge carries `src` (a passage id). An edge counts only
if that passage's `claims` list contains the relation key, so a passage
that merely mentions two entities cannot bridge them.
"""
import falkordb

HOST, PORT = "localhost", 6379


def key(a, rel, b, scope=None):
    return f"{a}|{rel}|{b}" + (f"@{scope}" if scope else "")


def connect(name):
    return falkordb.FalkorDB(host=HOST, port=PORT).select_graph(name)


def load(g, fx):
    try:
        g.delete()
    except Exception:
        pass
    q = g.query
    for p in fx["projects"]:
        q("CREATE (:Project {id:$id, name:$name})", p)
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
        add_relation(g, r)


def add_relation(g, r):
    t = r["type"]
    assert t in {"APPLIES_TO", "SUPERSEDES", "APPROVED_BY", "OWNED_BY", "ADDRESSES",
                 "SUPPORTED_BY", "AUTHORIZED_FOR"}, t
    props = "{src:$src, scope:$scope}" if t == "SUPERSEDES" else "{src:$src}"
    g.query(f"MATCH (a {{id:$a}}), (b {{id:$b}}) CREATE (a)-[:{t} {props}]->(b)",
            {"a": r["a"], "b": r["b"], "src": r["src"], "scope": r.get("scope")})


# Admissible = in effect at $t, applies to scope (supported), approved by a
# person who is authorized for that scope (both supported). Then drop any
# admissible decision that another admissible decision supersedes in this
# scope (supported). Remaining decisions grouped by requirement.
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
WITH s, r, d, collect(DISTINCT adp.id) + collect(DISTINCT ap.id) + collect(DISTINCT bp.id) + collect(DISTINCT zp.id) AS ev,
     collect(DISTINCT p.id) AS approvers
WITH s, collect({d:d, r:r, ev:ev, approvers:approvers}) AS rows
WITH s, rows, [x IN rows | x.d.id] AS ids
UNWIND rows AS row
WITH s, ids, row, row.d AS d
OPTIONAL MATCH (d2:Decision)-[x:SUPERSEDES]->(d) WHERE x.scope = s.id AND d2.id IN ids
OPTIONAL MATCH (xp:Passage) WHERE xp.id = x.src AND d2.id+'|SUPERSEDES|'+d.id+'@'+s.id IN xp.claims
WITH row, d, count(xp) AS beaten WHERE beaten = 0
RETURN row.r.id AS req, d.id AS decision, d.title AS title, row.ev AS evidence, row.approvers AS approvers
ORDER BY req, decision
"""

OWNER = """
MATCH (d:Decision {id:$d})-[o:OWNED_BY]->(p:Person)
MATCH (op:Passage) WHERE op.id = o.src AND d.id+'|OWNED_BY|'+p.id IN op.claims
RETURN p.id AS person, p.name AS name, op.id AS passage ORDER BY person
"""

RATIONALE = """
MATCH (d:Decision {id:$d})-[e:SUPPORTED_BY]->(p:Passage)
MATCH (ep:Passage) WHERE ep.id = e.src AND d.id+'|SUPPORTED_BY|'+p.id IN ep.claims
RETURN p.id AS passage, p.doc AS doc, p.rev AS rev, p.text AS text ORDER BY passage
"""

# Every passage that cited a supersession of the decision, regardless of
# whether it counted -- lets the answer explain what it ignored.
SUPERSEDE_ATTEMPTS = """
MATCH (d2:Decision)-[x:SUPERSEDES]->(d:Decision {id:$d}) WHERE x.scope = $scope
RETURN d2.id AS by, x.src AS passage ORDER BY by
"""


def rows(g, q, params):
    res = g.query(q, params)
    cols = [c[1] if isinstance(c, (list, tuple)) else c for c in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]


def applicable(g, scope, t):
    return rows(g, APPLICABLE, {"scope": scope, "t": t})


def owners(g, d):
    return rows(g, OWNER, {"d": d})


def rationale(g, d):
    return rows(g, RATIONALE, {"d": d})


def resolve(g, scope, t, req):
    """Deterministic answer for (scope, time, requirement)."""
    cands = [r for r in applicable(g, scope, t) if r["req"] == req]
    if not cands:
        return {"status": "UNKNOWN", "reason": "no admissible decision"}
    if len(cands) > 1:
        return {"status": "CONFLICT", "decisions": [c["decision"] for c in cands],
                "reason": "equally authoritative active decisions"}
    c = cands[0]
    own = owners(g, c["decision"])
    owner = own[0]["person"] if len({o["person"] for o in own}) == 1 else None
    return {"status": "ANSWER", "decision": c["decision"], "owner": owner,
            "rationale": [p["passage"] for p in rationale(g, c["decision"])],
            "evidence": sorted(set(c["evidence"]) | {o["passage"] for o in own})}
