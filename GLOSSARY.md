# SwarmResearch — Glossary

Every keyword this repo uses, defined in plain English, grouped by theme. Each entry
ends with **Why it matters here** — the one sentence that ties the term to this
codebase. If you can read this page, you can follow the whiteboard lecture video
(`brag-output/brag.mp4`) and the README's design-decisions section without getting lost.

---

## 1. The agent team

### agent
A software worker that has a job description, some tools, and just enough judgment to do that one job. In this repo an agent is a plain async function with a narrow role — nothing magical.
**Why it matters here:** every member of the team (planner, searchers, readers, analyst, critic, writer) is one small, testable async function, not a mysterious blob.

### multi-agent system
A program built from several specialized agents that hand work to each other, instead of one giant model trying to do everything in a single breath. Splitting roles lets each step be checked, capped, and retried on its own.
**Why it matters here:** SwarmResearch *is* one — the whole point is that a division of labor produces answers a single chatbot cannot.

### planner
The agent that reads your research question and writes the work plan: it splits the question into sub-queries and lays out the tasks and their dependencies. Think of a manager turning "investigate X" into a checklist.
**Why it matters here:** `PlannerAgent` turns one question into the task DAG the whole run follows — offline it uses structured heuristics, no LLM required.

### searcher
The agent that finds documents relevant to a sub-query. It does not read them deeply; it just ranks and fetches.
**Why it matters here:** `SearchBackend` ranks the bundled 20-document corpus with TF-IDF, and each search node is capped at `SWARM_MAX_DOCS_PER_TASK` documents so the run never drowns in text.

### reader
The agent that actually reads a retrieved document and extracts claims from it — short factual sentences lifted from the text, each with its exact location.
**Why it matters here:** `ReaderAgent` produces span-pinned `ClaimRecord`s; a claim without a verifiable location is thrown away, which is where the honesty guarantee starts.

### analyst
The agent that merges claims from many readers, removes duplicates, and cross-checks them against each other — including checking whether two documents state conflicting numbers.
**Why it matters here:** `AnalystAgent` dedupes with Jaccard similarity and runs the contradiction detection that catches the planted 42 vs 47 dB(A) disagreement.

### critic
The quality inspector. It verifies that every claim really appears at its cited location, measures whether the evidence actually covers the question, and orders more searching when coverage is thin.
**Why it matters here:** `CriticAgent` is the coverage gate: spans get re-verified against the source text, and weak coverage triggers a re-tasking plan.

### writer
The agent that composes the final markdown report from verified claims, attaching a numbered citation to every factual sentence.
**Why it matters here:** `WriterAgent` *enforces* citations — a factual sentence without `[n]` (or an explicit `analyst-inference` marker) cannot reach the report.

### TF-IDF search
Term Frequency × Inverse Document Frequency — a classic ranking formula. Score a document by how often your words appear in it, weighted down for words that appear everywhere (like "the") and up for rare, distinctive words. Pure keyword matching; no AI involved.
**Why it matters here:** it is the offline search engine over the bundled corpus — deterministic, fast, and good enough that retrieval quality is bounded by the corpus, not by a black box.

### coverage check
A measure of whether the collected evidence actually addresses every part of the original question. Coverage is a number from 0 to 1; a threshold decides if the evidence is complete enough.
**Why it matters here:** the critic computes coverage against `SWARM_COVERAGE_THRESHOLD` (default 0.8) — below it, the run is not "done", it goes shopping for more evidence.

### re-tasking
Sending work back for another round: when the critic finds a coverage gap, it orders a targeted extra search-read-analyze pass for the missing part only, not a rerun of everything.
**Why it matters here:** the critic's `RetaskPlan` routes execution into a pre-compiled gap-fill branch — one bounded refinement, so refinement can never loop forever.

### gap-fill branch
The statically-compiled "second attempt" path in the graph: critic → gapfill-search → gapfill-read → gapfill-analyze → merge. It exists in the graph from the start and is either used once or skipped.
**Why it matters here:** it is how this repo gets self-correction without cycles — the refinement is finite, validated at build time, and auditable.

---

## 2. The orchestration runtime (Orchestra)

### task DAG
Directed Acyclic Graph of tasks — a work plan drawn as boxes and arrows where every arrow means "this must finish before that starts", and no arrow ever loops back ("acyclic"). It is the shape of a plan you can actually schedule.
**Why it matters here:** the planner compiles the research plan into a DAG, and the runtime runs it with dependency-ordered parallelism — parallel where possible, ordered where required.

### dependency graph
The same picture, emphasized from the data's point of view: which results feed which steps. If B needs A's output, A is B's dependency.
**Why it matters here:** Orchestra schedules nodes only when all their dependencies have completed — an observer test proves the observed completion order is a valid topological order.

### topological order
Any ordering of a DAG's nodes that never puts a step before its dependencies. There are many valid orders; all of them respect the arrows.
**Why it matters here:** it is the test oracle for scheduling correctness — if the runtime ever ran a reader before its search finished, the topological check would fail.

### fan-out
One step splitting into many parallel steps — like a manager delegating one memo to six people at once. Cheap to draw, expensive to run if unbounded.
**Why it matters here:** search fan-out (four sub-queries at once) is where costs explode, so it is the first thing the runtime caps.

### semaphore
A counter that limits how many workers may run at the same time. Take a slot when you start, give it back when you finish; if none are free, wait.
**Why it matters here:** `SWARM_MAX_CONCURRENCY` (default 4) is a runtime semaphore — a test with six concurrent leaves and a cap of two proves observed peak concurrency never exceeds the cap.

### asyncio
Python's built-in library for running many I/O-bound tasks concurrently in a single thread, by awaiting (yielding) while waiting on slow things like file or network access.
**Why it matters here:** the entire runtime is async-native `asyncio` — parallelism without threads, which keeps ~600 lines auditable and race conditions rare.

### event bus
A broadcast channel where the runtime announces what is happening ("node started", "node failed", "graph completed") and any listener can subscribe. The system's live narration of itself.
**Why it matters here:** Orchestra's typed `EventBus` (`NodeStarted`/`Finished`/`Failed`/`Skipped`, `NodePaused`, `GraphCompleted`) drives the CLI streaming view and the SSE endpoint — one observer test asserts events arrive in execution order.

### checkpoint
A saved snapshot of progress: which nodes finished and what they produced. Written as the run progresses so a crash loses work, not the run.
**Why it matters here:** the `CheckpointStore` persists every node's output and every fired edge to SQLite the moment it completes — the reason resume is exact rather than approximate.

### resume
Restarting a crashed run by loading the last checkpoint and continuing from there. The definition of a good resume: finished work is never redone.
**Why it matters here:** on restart, completed nodes are skipped exactly — a test proves with execution counters that finished nodes ran once, while only the failed node ran again.

### SQLite WAL
Write-Ahead Logging mode for SQLite: writes go to a log first, then merge into the database. Readers don't block writers, and a crash mid-write leaves the last committed state intact.
**Why it matters here:** the checkpoint store runs in WAL mode so that a process dying mid-write can't corrupt the progress record — the crash-safety story starts in the storage layer.

### crash-safety
The property that a program killed at any instant can be restarted without corruption and without redoing completed work. Achieved by persisting small, atomic units of progress.
**Why it matters here:** node boundaries are the atomic units — each completed node is one committed checkpoint, so the worst case of a crash is "redo the interrupted node", never "redo the run".

### execution counter
A tally of how many times each node has actually executed. You increment it inside the node body, so it measures reality, not intentions.
**Why it matters here:** it turns "resume skips finished nodes" from a claim into a proof — the crash/resume test counts executions and asserts finished nodes ran exactly once.

### human-in-the-loop
A design where the automation pauses at chosen points and waits for a person to approve, answer, or veto before continuing.
**Why it matters here:** research runs can pause mid-flight for approval; the pause is persisted, so the wait can outlive the process.

### HumanInterrupt
The concrete exception/mechanism a node raises to trigger that pause: the run suspends, state is checkpointed, and the human's later answer is injected into the resumed run.
**Why it matters here:** `HumanInterrupt` is Orchestra's pause primitive — resume injects the answer, and a test proves the run continues exactly where it stopped.

### approval audit trail
An append-only log recording every approval request and every decision: who decided what, when, and why. Append-only means entries are never edited or deleted — only added.
**Why it matters here:** every human decision lands in `audit_log.jsonl` (`ts`, `actor`, `action`, `decision`, `reason`), a decision can only be made once (a second decision returns 409), and the queue is served by `GET /approvals` and `POST /approvals/{id}/decision`.

### conditional edges
Graph arrows chosen at runtime: a router function looks at a finished node's result and picks which downstream branch to take. Both branches exist in the graph; only one executes.
**Why it matters here:** the critic's router is the interesting one — "coverage OK" routes to merge, "gap found" routes to gap-fill, and the unrouted branch simply settles into `skipped`.

### cycle detection
A build-time check that the graph contains no loops (no path that can revisit a node). On a cyclic graph, a scheduler could spin forever, so the error is thrown before anything runs.
**Why it matters here:** `Graph.validate()` rejects cycles when the graph is compiled — which is exactly why refinement is a bounded gap-fill branch instead of a `critic → search` loop.

### bounded loop unrolling
Instead of allowing a loop in the graph, write the loop's iterations out as a fixed chain of distinct nodes — "one refinement pass", literally. Loops become finite structure.
**Why it matters here:** it is this repo's answer to "what if the critic wants a second round?" — the second round is a pre-drawn branch, so the acyclic guarantee survives.

### retry with backoff
When a step fails, try again — but wait longer between each attempt (exponentially growing delays), usually with jitter (a random extra dash) so many failures don't all retry in lockstep.
**Why it matters here:** per-node retry policy is exponential backoff plus jitter — a flaky search node gets a second chance without hammering the source.

### timeout
A promise that a step cannot hang forever: if it hasn't finished within the limit, it is treated as failed and the retry policy takes over.
**Why it matters here:** every node runs under a `wait_for` timeout — a stalled node becomes an ordinary failure, which is an ordinary, handled event.

### cancellation propagation
When a parent step is cancelled (say, a pause or a failure), its in-flight children are cancelled too — the cancellation travels down the whole subtree instead of leaving orphaned work running.
**Why it matters here:** pausing a run cancels in-flight siblings and rewinds them to pending — so a resume re-does exactly the interrupted work, no more, no less.

---

## 3. Memory & citations

### claim
One small, checkable factual statement lifted from a document — a single sentence with a source, not a paragraph of vibes. The atom of evidence in the system.
**Why it matters here:** readers emit `ClaimRecord`s; everything downstream (dedupe, contradiction checks, citations, the report) operates on claims, never on raw vibes.

### provenance
The receipts: where a piece of information came from. Full provenance names the document *and* the exact location inside it, so anyone can re-check the original.
**Why it matters here:** every claim carries `doc_id, char_start, char_end`, and the invariant `doc_text[char_start:char_end] == quote` is checked by the critic — provenance as an invariant, not a feature.

### quote span
The exact stretch of source text a claim quotes. Not a paraphrase, not a summary — the original characters, verbatim.
**Why it matters here:** claims are *extractive* on purpose: a summarized claim has no verifiable span, and the whole honesty chain depends on the quote being findable in the source.

### character offset
A position in a document measured in characters from the start — `char_start` and `char_end` are the two ends of a quote span. Machine-checkable, language-agnostic, and immune to re-wording.
**Why it matters here:** character offsets are what make citation verification mechanical: comparing two integers and a string slice, not two opinions.

### entity canonicalization
Merging the different names for the same thing — "XK-7", "the XK-7 module", and "XK7 compressor" all become one entity — so claims about it land in the same bucket.
**Why it matters here:** the blackboard canonicalizes entity aliases, which is what lets the analyst notice that two differently-worded sentences are about the same quantity.

### contradiction detection
Comparing claims about the same entity and attribute to find disagreements — especially numeric mismatches (two documents giving different figures) and negations (one says "is", another says "is not").
**Why it matters here:** the analyst flags the corpus's planted disagreement — doc-02's "47 dB(A)" vs doc-03's "42 dB(A)" — as a numeric-mismatch contradiction, and the report surfaces it in *Conflicting evidence*.

### blackboard
A shared workspace where all agents post their results and read each other's — named after the classroom blackboard that a group of specialists gathers around.
**Why it matters here:** `swarm.memory.blackboard` is the typed shared store for claims, entities, and run state; agents never pass secrets in a private handshake, everything is on the board.

### context compression
Shrinking working memory to fit a limit, by keeping the most useful pieces and dropping the rest — extractively (selecting existing sentences), not by asking an LLM to summarize.
**Why it matters here:** the `ContextCompressor` scores sentences for salience and recency and prunes to the token budget — deterministic, auditable, and it preserves the character spans citations depend on.

### token budget
A hard cap on how much text (measured in model tokens) may be kept in working memory. When you hit the cap, something must be pruned before anything new is added.
**Why it matters here:** `SWARM_TOKEN_BUDGET` (default 6000) bounds memory growth; the achieved compression ratio is logged onto the blackboard as a measured number.

### hallucination rate
The fraction of claims whose quote cannot actually be found at its recorded position in its cited document — in plain words, the fraction of "receipts that don't check out". 0.0 means every claim's receipt verifies.
**Why it matters here:** `hallucination_rate = claims lacking valid provenance / total claims`; the offline suite asserts it is exactly **0.0** — every one of the 34 claims in a run verifies against its span.

### citation coverage
The fraction of factual sentences in the final report that carry a citation. 1.0 means no factual sentence is uncited — no sentence asks to be trusted on faith.
**Why it matters here:** the report is regex-parsed sentence-by-sentence in the tests; citation_coverage is 1.0, meaning every factual sentence carries `[n]` or an explicit `analyst-inference` marker.

### corpus
The fixed body of documents a system searches over. A bundled corpus means the same documents ship with the code, so experiments are reproducible offline.
**Why it matters here:** 20 synthetic Kaltwerk heat-pump documents ship in `swarm/corpus`, including the planted contradiction pair and one stale document — the whole test suite runs against them with zero network.

---

## 4. Serving

### FastAPI
A modern Python web framework for building HTTP APIs with typed request/response models, automatic validation, and interactive docs.
**Why it matters here:** `swarm serve` exposes the pipeline as a service: `POST /research` starts a run, `GET /runs/{id}` reports its state, `GET /research/stream` streams it live.

### SSE (server-sent events)
A one-way HTTP stream where the server keeps pushing events to the browser as they happen — simpler than WebSockets when the client only needs to listen.
**Why it matters here:** `GET /research/stream` streams run progress over SSE; an end-to-end ASGI test asserts event order — searches finish before readers start, tokens precede the report, the report precedes `done`.

### API-key auth
Access control where clients present a secret key (here in an `X-API-Key` header). Best practice: store only a hash of each key, compare hashes in constant time, and never log the raw key.
**Why it matters here:** set `SWARM_API_KEYS` and every route except `/health` and `/metrics` requires a valid key; only SHA-256 hashes are stored, compared in constant time, and a bad key gets a generic 401 that reveals nothing.

### correlation id
A tag attached to one request that appears in every log line and response it touches, so its scattered traces can be joined back together after the fact.
**Why it matters here:** send `X-Correlation-ID` (or one is generated) and it is echoed on every response and returned in the run body — one id joins the whole run's logs across the stack.

---

*Count: 49 terms (45 core keywords + 4 supporting). Companion to `README.md`
(architecture and design decisions) and `brag-output/brag.mp4` (the whiteboard lecture).*
