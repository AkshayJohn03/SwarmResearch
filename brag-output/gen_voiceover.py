"""Generate per-scene voiceover WAVs via `npx hyperframes tts` and record durations."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

NPX = shutil.which("npx") or "npx.cmd"

OUT = Path(__file__).parent / "composition" / "assets" / "voiceover"
OUT.mkdir(parents=True, exist_ok=True)

SCENES = {
    "scene01": "Ask a chatbot a hard research question, and watch what happens. It answers in one breath. Confident, fluent — and sometimes, quietly, made up. And there's no way to check it, because it never shows you where anything came from. Now think about what real researchers do with the same question. They split it up. They read many documents. They quote their sources. They notice when two documents disagree. And they check each other's work. That difference — one breath versus a team — is the problem this project closes. SwarmResearch is a research team in a box.",
    "scene02": "Here's the team. A planner reads your question and writes the work plan, splitting it into sub-queries. Searchers find documents for each sub-query — this offline system ranks a bundled corpus of twenty documents with T F I D F: score documents by how often your words appear, weighted by how rare those words are. Readers extract claims from what was found. An analyst merges everything, removes duplicates, and cross-checks the claims. A critic is the quality gate: it verifies every claim's receipts, and measures whether the evidence covers the question. And a writer composes the final report, where every factual sentence carries a numbered citation. Six roles. One question. One report.",
    "scene03": "Everything hinges on one small structure: the claim. A claim is a single factual sentence, lifted verbatim from a document — plus its receipts. The receipt is three facts: which document, and the character offsets — the exact start and end positions inside that document's text. The rule is strict: the text at those positions must equal the quote, character for character. The critic re-verifies every claim before the report is written. If a claim can't show its receipt, it doesn't ship. That one invariant is where honesty starts.",
    "scene04": "The team doesn't chat its way through the job. The planner compiles the work into a task D A G — a directed acyclic graph. Boxes are tasks. Arrows mean: this must finish first. And acyclic means no arrow ever loops back, so the plan cannot spin forever. That shape buys two things. Parallelism where it's safe — the searches run side by side, capped by a semaphore so we never flood the sources. And order where it matters — no reader starts before its search finishes. The critic is the one decision point: good coverage routes straight to the writer. A gap routes into a pre-built gap-fill branch — one bounded second pass. Cycles are rejected at build time.",
    "scene05": "Now the fun one. What happens if the process dies halfway through? Most pipelines start over. Here, the runtime checkpoints every node the moment it finishes — its output, and the fact that it fired — into SQLite, in write-ahead logging mode. A crash loses the interrupted step, nothing more. Restart, and the run resumes: completed nodes are skipped, exactly. And that is not a promise — it's measured. A test crashes a node on purpose, then counts executions. Finished nodes ran once. Only the failed node ran again. One interrupted step redone: that's the entire cost of a crash.",
    "scene06": "Buried in the corpus is a trap. Two documents describe the same compressor. Document zero two says the X K seven runs at forty seven decibels. Document zero three says forty two. The analyst compares claims about the same entity and the same attribute — and when two numbers disagree, it flags a numeric mismatch. The writer doesn't pick a winner. The final report carries a Conflicting Evidence section that names both sources, quotes both figures, and cites both. The system's job isn't to guess. It's to tell you the sources disagree.",
    "scene07": "So — does it work? Measured, not claimed. Eighty five tests, fully offline, no network, under three seconds. In the sample run: thirty four claims extracted, all verified. Hallucination rate — the fraction of claims whose quote can't be found at its recorded position — zero point zero. Citation coverage — the fraction of factual sentences that carry a citation — one point zero. Zero uncited factual sentences. And the planted contradiction surfaces in the report, every time. Every number here is a test assertion, not a marketing line.",
    "scene08": "One honest question remains: why build a runtime by hand? LangGraph, LangChain, CrewAI — all mature. The answer: for deep research, the runtime is the product. You need checkpointed, resumable, observable, budget-capped execution, with human approval gates — and you need to own the failure semantics. Orchestra is about six hundred lines, zero framework dependencies, and every node is a plain async function. The trade is honest: no ecosystem, no visual debugger. But you can answer: what happens when a node times out mid-retry — by reading one function.",
    "scene09": "Thirty second recap. One chatbot answers in one breath. A research team splits the work, quotes its sources, and checks itself. SwarmResearch automates that team. A planner writes a task D A G. Searchers and readers gather claims with receipts — quote, document, character position. The analyst cross-checks them. The critic verifies spans and gates coverage. The writer cites every sentence. The runtime checkpoints every step, so a crash resumes without redoing finished work — proven with execution counters. The planted forty two versus forty seven contradiction surfaces in the report. Hallucination rate: zero point zero. Eighty five offline tests prove it. That's SwarmResearch — a research team in a box.",
}


def wav_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main() -> int:
    only = sys.argv[1:] or list(SCENES)
    durations = {}
    dur_file = Path(__file__).parent / "voiceover-durations.json"
    if dur_file.exists():
        durations = json.loads(dur_file.read_text())
    for name in only:
        wav = OUT / f"{name}.wav"
        if wav.exists():
            durations[name] = wav_duration(wav)
            print(f"[skip] {name} exists, {durations[name]:.2f}s", flush=True)
            continue
        print(f"[tts ] {name} ...", flush=True)
        subprocess.run(
            [NPX, "hyperframes", "tts", SCENES[name],
             "--voice", "af_heart", "--output", str(wav)],
            check=True, capture_output=True, text=True)
        durations[name] = wav_duration(wav)
        print(f"       -> {durations[name]:.2f}s", flush=True)
    dur_file.write_text(json.dumps(durations, indent=2))
    total = sum(durations[f"scene0{i}"] for i in range(1, 10) if f"scene0{i}" in durations)
    print(f"TOTAL narration: {total:.1f}s ({total/60:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
