# gtm-engineering-automation-kit

**The CRM data-flow layer a go-to-market engineering team runs before revenue data can be trusted: deduplication / entity resolution on messy leads, a rules-based router (territory, account ownership, round-robin with capacity limits), and a schema contract gate that blocks bad records before any CRM write — all graded against labelled ground truth and a golden routing set.**

A note on the name, because it matters: **GTM** — go-to-market: the sales-and-marketing operations side of a company (how leads are captured, cleaned, assigned and worked). It does *not* mean Google Tag Manager here. This project is not a description of the author's day job — his day job is marketing and portfolio analytics engineering. It is a ground-up build of the lead-operations data layer that *go-to-market engineers* (a distinct, in-demand role — this build is backed by a real GTM Engineer job description's requirements) construct beside the analytics stack: the unglamorous plumbing that decides whether a sales team works real, unique, correctly assigned leads or a swamp of duplicates. It is adjacent to his analytics-engineering work in exactly the way that matters — same discipline (contracts, deterministic pipelines, measured data quality), different surface.

> **Synthetic data only.** Every company, person and email is fictional, invented for this project. No real lead, customer or CRM data is used anywhere.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies. CSV / JSON in, CSV / JSON out — deliberately no fake Salesforce or HubSpot adapters (see Scope).

## The headline numbers

Against the bundled fixtures (33 messy leads, 17 labelled duplicate pairs, 13 golden routing cases, 10 CRM-write candidates):

| Check | Result |
|---|---|
| Dedupe **precision** — of the pairs the matcher calls duplicates, how many truly are | **1.0** (16/16, zero false merges) |
| Dedupe **recall** — of the true duplicate pairs, how many the matcher finds | **0.9412** (16/17 — one pinned miss, below) |
| Routing accuracy on the golden set | **1.0** (13/13, including ownership overrides and an unknown-territory case) |
| Schema gate | 6 clean records pass, 4 invalid rejected — each with exactly one per-field reason; clean records are never falsely blocked |

The recall miss is pinned, not hidden: Katherine Voss vs Kate Voss at "Silveroak Partners" vs "Silveroak Ptrs" needs a nickname the fixed map doesn't carry *and* a company abbreviation the normaliser doesn't expand. The evals name the exact missed pair (eval E8), so fixing it one day means deliberately extending a rule — not quietly editing the score.

## Quickstart

```bash
# 1. Deduplicate the messy leads, scored against the labelled truth
python3 cli.py dedupe --input fixtures/leads.jsonl --truth fixtures/ground_truth.json

# 2. Route the golden leads (ownership -> territory round-robin -> capacity)
python3 cli.py route --input fixtures/routing-input.jsonl   # or any leads file

# 3. Run the schema gate over CRM-write candidates; write only the
#    clean records to the CRM sink
python3 cli.py validate --input fixtures/crm_records.jsonl --sink crm_sink.json

# 4. Combined report (dedupe + routing + gate + narrative)
python3 cli.py report --input fixtures/leads.jsonl

# 5. CI gate: exit 0 = pass, 1 = quality breach (precision / recall /
#    routing accuracy below threshold), 2 = IO / data error
python3 cli.py check --input fixtures/leads.jsonl

# 6. One-command end-to-end demo (dedupe -> route -> validate ->
#    report -> check -> serve)
python3 demo.py

# 7. Tiny localhost API: POST /route, POST /validate, GET /health
python3 cli.py serve --port 8765
```

(Route accepts any leads JSONL/JSON/CSV — the golden cases' leads work as input; `tests/` shows the exact shapes.)

## How it works

**Deduplication.** **Entity resolution** — deciding which records refer to the same real-world person. First, **normalisation** — rewriting values into a canonical form so trivially-different spellings compare equal: lowercasing, punctuation removal, and stripping company suffixes (`Inc`, `LLC`, `Corp`, …) so "Northwind Labs, Inc." and "NORTHWIND LABS" are the same company. Then pairwise **matching rules** — explicit if/then tests for "same person": an exact email match; an equal name at an equal company; a nickname from a small fixed map (Bob ↔ Robert) at the same company; an initial for a first name (J. Ellis) with the same surname and company; or a one-edit typo — **Levenshtein distance** — the minimum number of single-character edits between two strings — of ≤ 1 in the full name at the same company. A name match *alone* never merges: company (or a non-generic email domain) must agree, which is what keeps the two fictional Alex Morgans at two different companies separate. Matching pairs are clustered by **union-find** — a data structure that maintains groups by repeatedly merging the groups of any two records a rule links. Quality is **precision** — of the pairs called duplicates, the share that truly are — and **recall** — of the true duplicate pairs, the share that were found — computed over all within-cluster pairs against the **ground truth** — the hand-labelled answer key of true duplicate pairs / clusters.

**Routing.** **Round-robin** — dealing assignments out in a fixed rotation, like cards. Rules fire in order: (1) **account ownership** — a lead whose normalised company is an existing owned account goes to that account's rep, even across territory lines; (2) **territory** — otherwise the lead's state maps to a region (west / central / east / south) and that region's two reps alternate round-robin. **Capacity** — the maximum number of active leads a rep may hold (3 per rep here) — is a hard limit everywhere: a rep at capacity is skipped, an owner at capacity falls through to the territory rotation (the assignment records why), and when every candidate is full — or the territory is unknown — the lead is left unassigned *with a reason*, never guessed. Accuracy is pinned by a **golden set** — a fixed list of example leads with the expected assignment for each, used as an answer key.

**Schema gate.** A **schema contract** — a written promise about a record's shape: which fields are required, their types, and their allowed values — enforced before any write. Here: six required string fields, a structurally valid email, `state` in the 51 US state/DC codes, `source` in a five-value list, and optional `employees` as a positive integer (JSON booleans are rejected explicitly — in Python `True` is an `int`, the classic quiet trap). A failing record is rejected with a per-field reason list; only valid records are written to the **sink** — the destination file that receives the records that passed. The gate reports errors and never raises on bad data, so a dirty batch maps to a clean exit code instead of a crash.

## Architecture

| Module | Job |
|---|---|
| `generator.py` | Deterministic synthetic fixtures: 33 messy leads (name / email / domain / company variants, typos, missing fields), the labelled ground truth, the 13-case routing golden set, and the 10-record CRM gate set (6 clean + 4 invalid, one defect each) |
| `dedupe.py` | Normalisation (case, punctuation, domain, company suffixes), the pairwise matching rules, union-find clustering, pair precision / recall |
| `router.py` | Territory map, account-ownership table, round-robin router with per-rep capacity limits and reasoned unassignments |
| `validation.py` | The schema contract gate: required fields, types, allowed values, per-field rejection reasons, valid-only sink writer |
| `report.py` | Combined report (dedupe metrics, routing accuracy, gate counts) + deterministic narrative copied from the computed numbers |
| `cli.py` | `dedupe` / `route` / `validate` / `report` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /route`, `POST /validate`, `GET /health`); JSONL, JSON-array and CSV inputs |
| `demo.py` | End-to-end narrative with asserts: fixture identity, pinned dedupe scores, golden routing, gate + sink, check exit codes, live localhost serve round-trip |
| `fixtures/` | The seeded leads (`leads.jsonl` + `.csv`), `ground_truth.json`, `routing_golden.json`, `crm_records.jsonl` |

## Evals

`python3 evals/run_evals.py` → **12/12 golden evals**, report committed at `evals/eval_report.json` (md5 `65afe172293da2b54f1bf1df41f36ce5`, byte-identical across 3 verified runs):

- **E1** generator determinism — seed 42 leads JSONL bytes pinned by md5
- **E2** headline dedupe pinned: precision 1.0, recall 0.9412 (16 TP, 0 FP, 1 FN)
- **E3** headline routing pinned: golden accuracy 1.0 (13/13)
- **E4** schema gate pinned: 6 pass, 4 rejected with exactly one per-field reason each; sink set = valid set
- **E5** company normalisation collapses suffix / case / punctuation variants to one key
- **E6** ownership beats territory; an at-capacity owner falls through to territory round-robin
- **E7** round-robin alternation order + capacity as a hard limit (6 of 8 west leads assigned, 2 reasoned unassignments)
- **E8** hard negatives never merge; the single missed pair is exactly the pinned Kate/Katherine case
- **E9** CLI `check` exit codes 0 / 1 / 2
- **E10** serve round-trip matches local route + validate exactly
- **E11** bundled fixtures pinned (33 leads, 17 pairs, 19 true clusters, 10 CRM records; CSV = JSONL)
- **E12** report determinism — canonical JSON identical across independent builds

Unit tests: `python3 -m unittest discover -s tests` → **64 hermetic tests**, including a no-network enforcement test (sockets stubbed), hand-computed pair metrics, every matching rule and its negative, capacity and fallthrough cases, per-field gate defects (including the bool-as-int trap), CLI exit codes, JSON/CSV round-trips, and serve round-trips.

## Development loop — what the checks actually caught

1. **The recall miss is real, measured, and deliberately unfixed.** Scoring the first full matcher run against the labelled pairs returned recall 0.9412, and the eval breakdown named the single missed pair: Katherine/Kate Voss, where *two* rules would each have to stretch (an uncovered nickname *and* the abbreviated company "Ptrs"). The easy move — adding `kate → katherine` to the nickname map — was rejected on purpose: a rule added to catch one fixture pair is overfitting the eval, and the domain+name rule would still not fire because the company names differ. The miss stays pinned in E2/E8 as the honest price of a small, auditable rule set; extending coverage means adding a *class* of evidence (e.g. company-abbreviation expansion), with new fixtures to match.
2. **Owner-at-capacity behaviour was undefined until the golden set forced the question.** The first routing spec said "ownership first, capacity is a hard limit" without saying what happens when both bite. Writing the golden cases made the gap concrete, and the decision — fall through to the territory rotation, with the reason string `owner_at_capacity_territory` recording that it happened — is now pinned by E6 and a unit test, instead of living in an operator's head.
3. **The check thresholds are a judgement call, set where the data argues.** `check` defaults (precision ≥ 0.90, recall ≥ 0.90, routing ≥ 0.90) sit just under the pinned scores (1.0 / 0.9412 / 1.0): the one known miss passes CI, but any *second* missed pair drops recall to 0.882 and fails the gate. A threshold that ignores a measured, documented limitation would cry wolf; one set any lower would stop catching regressions.

## Scope and honest limits

- **No LLM enrichment, no lead scoring.** Both were considered and cut: enrichment needs an external model (this project is offline and deterministic by design), and scoring without real outcome data is numerology. The kit cleans, deduplicates, routes and gates — it does not pretend to predict.
- **No CRM adapters.** There is no Salesforce or HubSpot connector, real or mocked; pretending otherwise would be the dishonest version of this project. Records move as CSV / JSON, and the sink is a JSON file standing in for the CRM write so the gate's behaviour is fully testable.
- **The nickname map is small and fixed** (7 entries). That is precisely why recall is 0.9412 and not 1.0 — see the dev loop. Production entity resolution would add phonetic matching and learned models; the claim here is an auditable rules baseline with measured quality, not state-of-the-art matching.
- **Company identity anchors every rule.** Two records with the same name at genuinely different companies never merge, by design — the false-merge cost (two customers' leads fused) is worse than a missed duplicate.
- **The router is a rules baseline.** No load balancing by rep performance, no skill-based routing, no working-hours logic; ownership, territory, rotation and capacity are the whole model, and every assignment carries its reason.
- **The API is a demo surface.** It binds 127.0.0.1 only, is stateless per request, and resets nothing because it keeps nothing.

## Why this project

Go-to-market engineering sits at the seam the author already works: data pipelines, contracts and quality gates, pointed at the systems revenue teams live in. Building this layer from scratch — with its quality *measured* against labelled truth instead of asserted — is the same discipline a forward-deployed engineer brings to a customer problem: make the logic inspectable, make the outputs reproducible, and make the failure modes exit codes.
