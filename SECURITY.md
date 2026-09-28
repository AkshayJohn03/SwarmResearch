# Security Policy — SwarmResearch

SwarmResearch executes multi-step agent plans that fetch and read untrusted
documents. Threat model and defenses:

| Threat | Defense |
|---|---|
| Indirect prompt injection via fetched documents | Reader extracts provenance-pinned CLAIMS (quote + char span); the Critic verifies each claim exists at the cited span before it can enter the report; documents are data, never instructions |
| Hallucinated citations | `hallucination_rate` metric is computed every run; the offline-suite contract is 0.0 — any uncited factual sentence fails the writer's contract |
| Unbounded runs | Per-node budgets (max docs, max tokens), timeouts with retry caps, semaphore-capped fan-out |
| Crash-injection via bad nodes | Checkpoint store (sqlite WAL) isolates node outputs; a failing node cancels downstream but cannot corrupt completed state |
| Secrets | Web search backend refuses to construct without explicit env config; `SWARM_*` keys env-only |

Report issues marked `security`.