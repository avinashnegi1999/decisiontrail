# DecisionTrail

**Why does this project currently do this?**

A new engineer reads the architecture page: Harbor exports customer data in real time. Production actually runs a nightly batch. DecisionTrail answers with the decision that applies, the reason, the accountable owner and the exact passages behind each link.

"Current" does not mean newest. It means approved and in scope at the requested date:

- A replacement applies only where it was granted. Production can change while staging keeps the old decision.
- A newer note from someone without authority does not override an approved decision.
- A decision can be approved now and take effect later.
- If two equally authoritative decisions both apply, the answer is **CONFLICT**. No tie-breaker is invented.
- If no supported decision applies, the answer is **UNKNOWN**.
- A relationship counts only if its cited passage actually states it. A passage that mentions two things does not link them.

Track: **Company Brain**. All companies, people and documents are fictional.

## Graph model

```
(Project)-[:HAS_SCOPE]->(Scope {env})
(Project)-[:HAS_REQUIREMENT]->(Requirement)
(Decision {from, to})-[:APPLIES_TO]->(Scope)
(Decision)-[:ADDRESSES]->(Requirement)
(Decision)-[:SUPERSEDES {scope}]->(Decision)
(Decision)-[:APPROVED_BY]->(Person)-[:AUTHORIZED_FOR]->(Scope)
(Decision)-[:OWNED_BY {from}]->(Person)
(Decision)-[:SUPPORTED_BY]->(Passage)        rationale
(Passage {doc, rev, text, claims})
```

Every relationship carries `src`, a passage id. The passage's `claims` list is a separate relation-evidence ledger. A query uses an edge only if `src` lists that exact claim.

## Core query

Which decisions apply to a scope at a date (abridged, full text in `decisiontrail.py`):

```cypher
MATCH (s:Scope {id:$scope})<-[a:APPLIES_TO]-(d:Decision)-[ad:ADDRESSES]->(r:Requirement)
WHERE d.from <= $t AND (d.to IS NULL OR $t < d.to)
MATCH (d)-[b:APPROVED_BY]->(p:Person)-[z:AUTHORIZED_FOR]->(s)
// each of a, ad, b, z must be claimed by its cited passage:
MATCH (ap:Passage) WHERE ap.id = a.src AND d.id+'|APPLIES_TO|'+s.id IN ap.claims
...
// drop decisions another admissible decision supersedes in this scope
OPTIONAL MATCH (d2:Decision)-[x:SUPERSEDES]->(d) WHERE x.scope = s.id AND d2.id IN ids
OPTIONAL MATCH (xp:Passage) WHERE xp.id = x.src AND d2.id+'|SUPERSEDES|'+d.id+'@'+s.id IN xp.claims
WITH row, d, count(xp) AS beaten WHERE beaten = 0
RETURN row.r.id AS req, d.id AS decision, row.ev AS evidence
```

One result per requirement is an answer. Two or more is a conflict. None is unknown. Owner, rationale and the replaced decision are three more short supported-edge queries.

## Agent tools

`resolve_project`, `applicable_decisions`, `trace_rationale`, `resolve_owner`, `read_passage`, `answer_or_abstain`. Each one runs Cypher and only reads data. The server checks each submitted answer: the ids must exist, citations must be known passages, and the approver must hold authority for that environment. The checker does not reveal the right answer.

## Results

**Feasibility gate** (`python gate.py`): 6/6. The gate has four passages, an authorized replacement, two scopes, a newer unauthorized note, and then a conflict and two unsupported relations. No kill condition was hit, and two runs returned identical traces. The trace is in `results/gate_trace.json`.

**Deterministic eval** (`python eval.py`, no model). An authored answer ledger supplies the expected answers. The ledger must also agree with `oracle.py`, an independent Python reducer that shares no code with the graph queries. The baseline is a structured passage index over the same durable facts: project, environment, effective date, topic, approver and owner. It uses the same authority guard, and the newest authorized passage wins.

| | Graph, dev | Baseline, dev | Graph, held-out | Baseline, held-out |
|---|---:|---:|---:|---:|
| Cases fully correct | 12/12 | 9/12 | 12/12 | 9/12 |
| Current decision | 10/10 | 10/10 | 11/11 | 11/11 |
| Owner | 10/10 | 10/10 | 11/11 | 9/11 |
| Rationale passages exact | 10/10 | 8/10 | 11/11 | 10/11 |
| Correct conflict/unknown | 2/2 | 1/2 | 1/1 | 1/1 |
| Wrong or unwarranted answers | 0 | 1 | 0 | 0 |

The baseline picks the right decision every time. It loses where the reason or owner sits one hop away: an incident postmortem that justifies a decision, an ownership transfer inside an active decision, and a conflict it resolves by date. Held-out mutations were written after the dev fixture, prompts and oracle were committed. They cover a rename, partial supersession, a future-effective replacement, a corrected owner, revoked authority, an unauthorized scoped note and a false bridge.

**Regression case h13** was added after the first held-out run. It asks about a past date, before an approver's authority was ended by a later charter. The graph and the baseline both answer it correctly.

**Agent eval** (`python agent_eval.py h01 ... h13`, gpt-5.4-mini). Both modes used the same model, prompt, six-turn budget and answer checker. Graph mode uses the FalkorDB tools; flat mode uses a search over the same passage index as the baseline. Each mode was run twice over the 12 held-out cases.

| | Graph tools, run 1 | Graph tools, run 2 | Flat index, run 1 | Flat index, run 2 |
|---|---:|---:|---:|---:|
| Held-out cases fully correct | 12/12 | 12/12 | 10/12 | 9/12 |
| Unsupported citations | 0 | 0 | 2 | 3 |
| Regression case h13 | correct | correct | correct | correct |

The two runs together took 167 requests, 162,264 input tokens and 10,960 output tokens. In flat mode, the model named the previous owner after an ownership transfer (h01, h02). In one run it also called a conflict between a decision and the newer decision that replaced it for staging only (h04). It cited passages that do not support the decision it answered with. Graph mode got every case right and cited only supporting passages.

**How the agent harness changed.** Before these final runs, the harness was fixed several times after looking at held-out runs. Every fix applied to both modes:

1. The flat search now applies its environment filter.
2. The checker forces an answer on the final turns, with two spare turns to fix a rejected answer.
3. A plain-text reply gets the same nudge in both modes.
4. An answer sent in the same turn as lookups no longer ends the run; the latest accepted answer counts.
5. The answer field now says it expects a decision id such as D3.
6. Authority in the checker and the flat search is evaluated at the requested date.
7. The turn budget went from five to six.
8. One prompt sentence was added: pass the given date to every dated tool.

The earlier runs scored from 4/12 to 11/12 for flat and from 10/12 to 12/12 for graph. Those runs were set aside because of these harness bugs, not because of their scores. The deterministic graph resolver and the oracle did not change during this work, apart from adding authority end dates, which the h13 case covers.

## Run

```bash
docker run -p 6379:6379 -d falkordb/falkordb
pip install -r requirements.txt
python gate.py
python eval.py
python server.py        # http://localhost:8001
```

The agent needs `OPENAI_API_KEY`. Run `python agent.py dev01 graph` for one case.

## Limits

- Curated import only. There is no parser, connector or automatic extraction.
- Authority can end on a date, but only when a supported later passage ends it. Authority start dates are not modeled.
- Passage support is an authored claims list. It proves that the source states the relation. It does not prove the relation is true in the real world.
- Two projects and about twenty cases cannot show general performance. Recursive SQL could run the same joins. The point here is that FalkorDB holds the connected state and returns paths you can inspect.

## AI disclosure

The code, fixtures and this README were written with help from an AI coding assistant. The author reviewed and ran everything.
