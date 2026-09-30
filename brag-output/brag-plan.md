# Brag Plan: SwarmResearch — "a research team in a box"

## What is this app?
A multi-agent deep-research assistant that turns a question into a task DAG, gathers
provenance-pinned claims, cross-checks them, and writes a fully-cited report — running on
Orchestra, a hand-rolled ~600-line asyncio orchestration runtime with crash-resumable
checkpointing. 85 offline tests prove the headline behaviors: hallucination rate 0.0,
citation coverage 1.0, the planted 42 vs 47 dB(A) contradiction surfacing in the report.

## The angle
A whiteboard lecture, not a launch ad. The success metric: the repo's owner finishes the
video able to explain SwarmResearch to a colleague. The teaching spine is the TUTOR_BRIEF
section-4 outline: one-breath chatbot vs research team → the agent roles → claims with
receipts → the task DAG → crash-resume proven with counters → the planted 42 vs 47 dB(A)
contradiction → hallucination rate 0.0 → why the runtime is hand-rolled → recap.
Every technical keyword is defined on screen in one plain sentence at first use
(definition cards in a right-hand rail, matching the series' chalkboard look).

## Hook (first 8 seconds)
Chalk-drawn chat bubble firing a one-line "answer" at a hard research question —
and the line simply says "…and it made that up." Then the contrast: five small
chalk figures (the team) around the same question. The lecture's opening line:
"Ask a chatbot a hard research question — it answers in one breath."

## Key moments (the middle)
- The team lineup: planner → searchers → readers → analyst → critic → writer, drawn as
  a chalk pipeline with one-line job descriptions arriving role by role.
- The receipt: a claim card whose quote highlights the exact character span
  (`char_start 412 → char_end 447`) inside a document excerpt, with the invariant
  `doc_text[char_start:char_end] == quote` chalked underneath.
- The task DAG sketch: plan → 4 parallel searches → readers → analyze → critic, with the
  critic's conditional edge splitting into "finalize" vs a bounded gap-fill branch.
- Crash test: a runtime timeline dying mid-run, a checkpoint, then resume — with
  execution counters proving finished nodes ran exactly once.
- The contradiction: two document cards, "47 dB(A)" vs "42 dB(A)", and the report's
  *Conflicting evidence* section that refuses to pick a winner.
- The numbers board: 85 tests · hallucination rate 0.0 · citation coverage 1.0.

## Outro / punchline
The 30-second recap, chalked as a compact one-screen summary the viewer could repeat:
"Different question, same shape: split the work, quote your sources, check each other.
That's SwarmResearch — a research team in a box."

## User flow worth showing
`swarm research "What is the noise level of the XK-7 compressor module?" --offline --stream`
→ the pipeline streams node events (search → read → analyze → critic → write)
→ the cited markdown report, including its Conflicting evidence section.
Recreated as chalk UI: a terminal line, a node-event ticker, and a real excerpt of the
report (verbatim from README's sample output) in Scene 6.

## Tone
- Preset: `polished` (long-form pacing adapted per TUTOR_BRIEF — lecture, not ad)
- Creative direction: patient senior engineer at a whiteboard teaching one system to a
  smart junior; calm, precise, friendly; zero hype adjectives; every keyword defined on
  screen at first use.
- Interpretation: slow scene counts with long holds, definitions get their own readable
  cards, motion is chalk-like (write-on, settle, breathe) — restrained, never flashy.

## Format: landscape — 1920x1080
## Duration: ~6 minutes (lecture pacing; narration-driven scene lengths)

## Visual identity (series-consistent chalkboard, matches HVAC-Copilot / VerdictAI episodes)
- Background: `#13211d` chalkboard green with radial vignette
- Chalk text: `#f2f0e9`; dimmed chalk `#d5d2c6`
- Accent amber: `#f5b942` (highlight/receipts) · teal: `#63d3c3` (team/flow) · blue: `#9ec5e8` (documents)
- Display font: Ink Free (chalk handwriting, local `@font-face` to `assets/fonts/Inkfree.ttf`)
- Body font: system-ui sans (definitions stay plain and legible); mono for code/offsets
- Strongest visual element: chalk definition cards + hand-drawn pipeline/DAG diagrams

## Share copy (draft)
"I made SwarmResearch — a research team in a box: claims with receipts, a task DAG,
crash-resume proven by execution counters, and a hallucination rate of exactly 0.0
on its offline corpus. New whiteboard lecture walks the whole system."

## Audio direction
- Role: warm quiet bed under continuous narration (lecture, not music video)
- Music: `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (steady, clean), volume 0.13, looped to full duration, fade at end
- Music treatment: constant low bed under voice; do NOT duck per-scene (voice is continuous); final fade over recap
- Music cue guidance: beat sync intentionally unused — narration sets the pace for a lecture; cues would fight sentence boundaries
- Audio-reactive treatment: none (narration-led lecture; music is a bed, not a driver)
- SFX posture: sparse — one soft accent per major reveal (contradiction flag, numbers board, recap)
- Audio-coupled moments: chalk write-on of role names (scene 2), claim receipt stamp (scene 3),
  crash thud + resume (scene 5), contradiction flag (scene 6)
- Restraint rule: nothing may compete with the voice; SFX only on the 3-4 biggest moments

## Storyboard

### Scene 1 — The one-breath answer — ~40s
A chat bubble receives a hard question and fires a confident one-line answer; label
"made that up" chalked beside it. Then five small figures (the team) around the same
question. Keyword cards (right rail): "multi-agent system".
Sequential/interaction: yes — question types in, answer slams in, "made that up" stamps after.
Audio intent: quiet intrigue; the bed starts almost subliminal.
Audio-coupled idea: question types with soft key ticks; answer lands with one dry impact.
Music: vol-12 bed at 0.13.
Transition mood: soft crossfade → Scene 2.

### Scene 2 — The team — ~48s
Chalk pipeline left-to-right: PLANNER → SEARCHERS → READERS → ANALYST → CRITIC → WRITER;
each role's one-line job appears under its name as the narration reaches it.
Keyword cards: "agent", "TF-IDF search", "coverage check".
Sequential/interaction: yes — six role blocks arrive one by one with drop accents.
Audio intent: steady teaching rhythm; a small tick per role.
Audio-coupled idea: role-by-role reveal, each with `interface/drop_*`.
Transition mood: clean wipe → Scene 3.

### Scene 3 — Claims with receipts — ~42s
A document excerpt (real corpus-flavored sentence); a claim card quotes it verbatim;
the exact span highlights inside the excerpt with `char_start`/`char_end` callouts; the
invariant `doc_text[char_start:char_end] == quote` chalked below; a "receipt verified" stamp.
Keyword cards: "claim", "provenance", "character offset".
Sequential/interaction: yes — excerpt first, then quote, then span highlight, then stamp.
Audio intent: careful, deliberate — this is the honesty core.
Audio-coupled idea: span highlight draws with one soft tick; stamp with `impactSoft_medium`.
Transition mood: soft crossfade → Scene 4.

### Scene 4 — The task DAG — ~46s
Chalk DAG: plan → search-0..3 (parallel) → read-0..3 → analyze → critic (diamond) →
finalize / gap-fill branch → merge → writer. Fan-out braces labeled "semaphore cap = 4".
Keyword cards: "task DAG", "fan-out", "semaphore", "conditional edges", "gap-fill branch".
Sequential/interaction: yes — nodes draw in dependency order; both critic branches appear,
one settles into a dimmed "skipped" state.
Audio intent: structural, assured.
Audio-coupled idea: node draw-ins staggered; "skipped" fades with `interface/switch_*`.
Transition mood: clean wipe → Scene 5.

### Scene 5 — Crash and resume — ~44s
A run timeline of node chips; a red "crash" breaks the line mid-way; a checkpoint chip
(SQLite WAL) glows; the run restarts and completed chips show counters "ran ×1" while the
failed node re-runs ("ran ×2"). Keyword cards: "checkpoint", "SQLite WAL", "resume",
"execution counter".
Sequential/interaction: yes — crash interrupts, resume sweeps left-to-right skipping done nodes.
Audio intent: tension on the crash, calm resolution on resume.
Audio-coupled idea: crash thud (`impactSoft_heavy`-family soft), resume with light ticks.
Transition mood: soft crossfade → Scene 6.

### Scene 6 — The planted contradiction — ~40s
Two document cards: doc-02 "47 dB(A)" and doc-03 "42 dB(A)" for the same entity/attribute;
an analyst line connects them to a flag: "numeric mismatch". Below, the real report
excerpt: "## Conflicting evidence … doc-02 states '47 dB(A)' while doc-03 states '42 dB(A)'"
(verbatim README sample). Keyword cards: "contradiction detection", "entity canonicalization".
Sequential/interaction: yes — cards land, numbers pulse once, flag stamps, report excerpt writes on.
Audio intent: the "aha" — two sources, no winner declared.
Audio-coupled idea: flag stamp with `impactSoft_medium_002`.
Transition mood: soft crossfade → Scene 7.

### Scene 7 — The numbers — ~38s
A chalk scoreboard: 85 tests · 34 claims verified · hallucination rate 0.0 ·
citation coverage 1.0 · ~2.3s suite runtime. Each number counts up and settles with a
one-line plain-English caption ("0.0 = every claim's receipt verifies").
Keyword cards: "hallucination rate", "citation coverage".
Sequential/interaction: yes — five counters arrive one by one.
Audio intent: quiet satisfaction; let numbers breathe.
Audio-coupled idea: count-up settle ticks; one bong on the 0.0.
Transition mood: soft crossfade → Scene 8.

### Scene 8 — Why hand-rolled — ~40s
Left: the honest comparison (Orchestra ~600 LOC, 0 framework deps, plain async nodes vs
framework ecosystem/visual debugger). Right: the payoff list — exact checkpoint semantics,
ownable failure semantics, observable events. Keyword cards: "asyncio", "event bus".
Sequential/interaction: yes — trade rows arrive in pairs (cost, then payoff).
Audio intent: candid, even-handed.
Audio-coupled idea: none — restraint; the voice carries it.
Transition mood: soft crossfade → Scene 9.

### Scene 9 — Recap — ~46s
One-screen chalk summary of the full arc (team → receipts → DAG → crash-resume →
contradiction → 0.0) as six compact lines with tiny icons; closes on the series line:
"That's SwarmResearch — a research team in a box."
Sequential/interaction: yes — six recap lines write on, then the closing line.
Audio intent: warm wind-down; bed fades under the final line.
Audio-coupled idea: final line lands with a soft drop; music fade-out.
Transition mood: fade to board → end.

**Music mood for this video:** steady/clean bed (vol-12), lecture-appropriate restraint
**Audio summary:** one continuous quiet bed under continuous narration; sparse soft accents
on the four biggest reveals; fade under the recap's closing line.

## Voiceover script

Kokoro `af_heart`. Numbers written for TTS; exact figures appear on screen.
Scene durations flex to the generated WAVs (target total ≈ 6 minutes).

### SCENE 1 — The one-breath answer
Ask a chatbot a hard research question, and watch what happens. It answers in one breath. Confident, fluent — and sometimes, quietly, made up. And there's no way to check it, because it never shows you where anything came from. Now think about what real researchers do with the same question. They split it up. They read many documents. They quote their sources. They notice when two documents disagree. And they check each other's work. That difference — one breath versus a team — is the problem this project closes. SwarmResearch is a research team in a box.

### SCENE 2 — The team
Here's the team. A planner reads your question and writes the work plan, splitting it into sub-queries. Searchers find documents for each sub-query — this offline system ranks a bundled corpus of twenty documents with T F I D F: score documents by how often your words appear, weighted by how rare those words are. Readers extract claims from what was found. An analyst merges everything, removes duplicates, and cross-checks the claims. A critic is the quality gate: it verifies every claim's receipts, and measures whether the evidence covers the question. And a writer composes the final report, where every factual sentence carries a numbered citation. Six roles. One question. One report.

### SCENE 3 — Claims with receipts
Everything hinges on one small structure: the claim. A claim is a single factual sentence, lifted verbatim from a document — plus its receipts. The receipt is three facts: which document, and the character offsets — the exact start and end positions inside that document's text. The rule is strict: the text at those positions must equal the quote, character for character. The critic re-verifies every claim before the report is written. If a claim can't show its receipt, it doesn't ship. That one invariant is where honesty starts.

### SCENE 4 — The task DAG
The team doesn't chat its way through the job. The planner compiles the work into a task D A G — a directed acyclic graph. Boxes are tasks. Arrows mean: this must finish first. And acyclic means no arrow ever loops back, so the plan cannot spin forever. That shape buys two things. Parallelism where it's safe — the searches run side by side, capped by a semaphore so we never flood the sources. And order where it matters — no reader starts before its search finishes. The critic is the one decision point: good coverage routes straight to the writer. A gap routes into a pre-built gap-fill branch — one bounded second pass. Cycles are rejected at build time.

### SCENE 5 — Crash and resume
Now the fun one. What happens if the process dies halfway through? Most pipelines start over. Here, the runtime checkpoints every node the moment it finishes — its output, and the fact that it fired — into SQLite, in write-ahead logging mode. A crash loses the interrupted step, nothing more. Restart, and the run resumes: completed nodes are skipped, exactly. And that is not a promise — it's measured. A test crashes a node on purpose, then counts executions. Finished nodes ran once. Only the failed node ran again. One interrupted step redone: that's the entire cost of a crash.

### SCENE 6 — The planted contradiction
Buried in the corpus is a trap. Two documents describe the same compressor. Document zero two says the X K seven runs at forty seven decibels. Document zero three says forty two. The analyst compares claims about the same entity and the same attribute — and when two numbers disagree, it flags a numeric mismatch. The writer doesn't pick a winner. The final report carries a Conflicting Evidence section that names both sources, quotes both figures, and cites both. The system's job isn't to guess. It's to tell you the sources disagree.

### SCENE 7 — The numbers
So — does it work? Measured, not claimed. Eighty five tests, fully offline, no network, under three seconds. In the sample run: thirty four claims extracted, all verified. Hallucination rate — the fraction of claims whose quote can't be found at its recorded position — zero point zero. Citation coverage — the fraction of factual sentences that carry a citation — one point zero. Zero uncited factual sentences. And the planted contradiction surfaces in the report, every time. Every number here is a test assertion, not a marketing line.

### SCENE 8 — Why hand-rolled
One honest question remains: why build a runtime by hand? LangGraph, LangChain, CrewAI — all mature. The answer: for deep research, the runtime is the product. You need checkpointed, resumable, observable, budget-capped execution, with human approval gates — and you need to own the failure semantics. Orchestra is about six hundred lines, zero framework dependencies, and every node is a plain async function. The trade is honest: no ecosystem, no visual debugger. But you can answer: what happens when a node times out mid-retry — by reading one function.

### SCENE 9 — Recap
Thirty second recap. One chatbot answers in one breath. A research team splits the work, quotes its sources, and checks itself. SwarmResearch automates that team. A planner writes a task D A G. Searchers and readers gather claims with receipts — quote, document, character position. The analyst cross-checks them. The critic verifies spans and gates coverage. The writer cites every sentence. The runtime checkpoints every step, so a crash resumes without redoing finished work — proven with execution counters. The planted forty two versus forty seven contradiction surfaces in the report. Hallucination rate: zero point zero. Eighty five offline tests prove it. That's SwarmResearch — a research team in a box.
