# Evaluation

How DecisionTrail's results were measured. All data is fictional.

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
