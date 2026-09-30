# Hyperframes Composition Brief: SwarmResearch — whiteboard lecture

## Objective
Create a ~6-minute whiteboard explainer lecture video for SwarmResearch (NOT a launch
ad): a patient senior engineer at a chalkboard teaching one system to a smart junior.
Narration on (Kokoro `af_heart`), definitions on screen at first use, long-form pacing.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: ~6 minutes (360–390s; scene durations flex to generated voiceover WAVs)

## Source Material
- Project root: `D:/aria/Projects/SwarmResearch`
- Primary files read: `README.md`, `src/swarm/orchestra/*`, `src/swarm/agents/*`,
  `src/swarm/memory/*`, `src/swarm/citations/graph.py`, `src/swarm/serve/*`, test suite
- Product name: SwarmResearch (runtime: Orchestra)
- Tagline / strongest claim: "a research team in a box"; hallucination rate 0.0,
  citation coverage 1.0, 85 offline tests, crash-resume proven by execution counters
- Key UI/visual moments to recreate (chalk-drawn): the report's *Conflicting evidence*
  section (verbatim from README sample), the claim receipt invariant
  `doc_text[char_start:char_end] == quote`, the critic's conditional-edge DAG,
  the crash/resume execution-counter proof
- Copy that must appear verbatim:
  - "Research report: What is the noise level of the XK-7 compressor module?" (scene 6 report excerpt)
  - "doc-02 states \"47 dB(A)\" … doc-03 states \"42 dB(A)\"" (conflicting evidence line)
  - "hallucination rate 0.0 · citation coverage 1.0 · 85 tests" (numbers board)

## Creative Direction
- Tone preset: `polished`, overridden by TUTOR_BRIEF lecture pacing (long holds,
  definitions readable, zero hype)
- Creative direction: series-consistent chalkboard look (matches HVAC-Copilot and
  VerdictAI episodes): dark green board, chalk handwriting headers, definition cards
  in a right-hand rail, chalk-line diagrams with slow ambient motion
- Angle: one-breath chatbot vs research team; every keyword defined at first use
- Hook: chat bubble answers in one breath — "…and it made that up"
- Outro / punchline: 30-second recap, closing "That's SwarmResearch — a research team in a box."
- Avoid:
  - Generic SaaS language, hype adjectives, launch energy
  - Abstract filler visuals
  - Beat-grid text reveals that outrun reading (lecture pacing wins over music)

## Visual Identity
- Background: `#13211d` board + radial vignette (body `#0d1714`)
- Text: chalk `#f2f0e9`, dim `#d5d2c6`
- Accent: amber `#f5b942`, teal `#63d3c3`, blue `#9ec5e8`; hairline `rgba(242,240,233,0.25)`
- Display font: "Ink Free" via local `@font-face` (`assets/fonts/Inkfree.ttf`)
- Body font: system-ui sans; mono (ui-monospace) for code, offsets, counters
- Visual references: chalk definition cards ("kcard"), underline strokes, dashed boxes,
  hand-drawn-style borders (thick + rounded), scene tag bottom-left ("SwarmResearch · 02/09")

## Storyboard
Use the storyboard + voiceover script in `brag-output/brag-plan.md` as the creative contract.

Scene summary (durations flex to voiceover; approximate):
1. The one-breath answer — ~40s — chat bubble, "made that up", the team teaser
2. The team — ~48s — planner→searchers→readers→analyst→critic→writer, one line each
3. Claims with receipts — ~42s — excerpt, verbatim quote, span highlight, invariant, stamp
4. The task DAG — ~46s — plan→4×search→4×read→analyze→critic→(finalize|gap-fill)→merge→writer
5. Crash and resume — ~44s — crash breaks timeline, checkpoint, resume, counters ×1/×2
6. The planted contradiction — ~40s — 47 vs 42 dB(A) cards, flag, real report excerpt
7. The numbers — ~38s — 85 tests · 0.0 · 1.0 · 34 claims · <3s count-ups with captions
8. Why hand-rolled — ~40s — ~600 LOC / 0 deps / plain async nodes vs ecosystem trade
9. Recap — ~46s — six-line summary, closing line, music fade

## Audio
- Audio role: warm quiet bed under continuous narration
- Audio arc: bed enters faintly with scene 1, constant 0.13 under voice, fades across the recap
- Music: `assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (local), loop segments on one shared track index pattern like sibling episodes, volume 0.13
- Music treatment: NO per-scene ducking (voice is continuous); final fade over last ~4s
- Music cue guidance: intentionally unused — narration sets pace; do not snap text reveals to beats
- Audio-reactive treatment: none
- Audio-coupled moments:
  - scene 1 — answer slams (soft impact)
  - scene 2 — role-by-role drop accents (`interface/drop_*`)
  - scene 3 — receipt stamp (`impact/impactSoft_medium_000`)
  - scene 5 — crash thud, resume ticks
  - scene 6 — contradiction flag (`impact/impactSoft_medium_002`)
  - scene 7 — settle bong on 0.0 (`interface/bong_001`, quiet)
  - scene 9 — closing line soft drop
- SFX selection guidance: sparse, soft, low high-frequency risk; skip accents where the edit is already busy
- SFX analysis guidance: `<skill-dir>/assets/sfx/sfx-analysis.md` (copy files used into `assets/sfx/`)
- Exact SFX choice: Hyperframes chooses exact timestamps/density after animation exists
- Audio files: music + sfx already copied into `composition/assets/`; voiceover WAVs go to `composition/assets/voiceover/voice_NN.wav` generated by `npx hyperframes tts --voice af_heart`

## Voiceover wiring
- One WAV per scene: `assets/voiceover/voice_01.wav` … `voice_09.wav`
- `vo-N` starts at its scene's start + 1.1s lead-in; scene duration = lead + vo duration + ~1.5s tail
- Each `<audio id="vo-N" data-start=… data-duration=… data-track-index=3+N data-volume="1">`
- Root `data-duration` = sum of scene durations (authored statically after WAV durations known)

## Hyperframes Instructions
Load `hyperframes-core`, `hyperframes-animation`, `hyperframes-creative`,
`hyperframes-keyframes`, `hyperframes-cli`. /brag owns product angle, copy, storyboard;
Hyperframes owns composition structure, timing mechanics, lint/render workflow.

Requirements:
- Standalone composition: root `<div id="root" data-composition-id="swarm-lecture" data-width="1920" data-height="1080" data-duration="<total>">`; NO `<template>` wrapper
- One paused GSAP timeline registered at `window.__timelines["swarm-lecture"]`, built synchronously (or in `document.fonts.ready` — register only after build)
- Scenes as `.clip` sections (`data-start`, `data-duration`); never tween the clip itself — animate inner wrappers; no `display`/`visibility` tweens; use `opacity`/`autoAlpha` on children only
- No CSS `transform` + GSAP transform on the same element (use `fromTo`/`xPercent`); no `crossorigin` on media; every `<audio>` has an `id`
- Deterministic: no `Date.now`/`performance.now`/unseeded random/`repeat:-1` (finite repeats, floor count); ambient chalk-breath motion on decoratives in EVERY scene (continuous motion across the whole timeline keeps `check`'s `sweep_static` happy)
- Chalk write-on effect: reveal lines/boxes with `scaleX`/`clipPath` or opacity+draw of SVG strokes; keep text readable (motion ≤0.6s, then hold)
- Definition cards hold ≥ 0.3s/word settled; no text pulled off before readable
- Keywords defined on screen at first use (right rail `kcard`s matching sibling episodes)
- `data-layout-allow-overflow` only where entrance travel is intentional; fix real overflow by layout, not escapes
- Root-level clips: rely on automatic layout (position absolute inset 0 via `.clip`)
- Layout: `.board` grid `1fr 440px` (main + definition rail), padding ~52-60px, scene tag bottom-left
- Run `npx hyperframes check` before render — brag's single gate; fix ALL errors incl. WCAG AA contrast (105/105 text checks pass is the series bar)
- Render `npx hyperframes render --quality delivery --output ../brag.mp4` after check passes
