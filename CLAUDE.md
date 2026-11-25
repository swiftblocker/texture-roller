# Pottery Texture Roller Generator

Parametric generator for clay texture rollers: vector art in, a printable/millable
cylinder with the art wrapped on as relief out. Max roller length 10 in (254 mm);
it must be able to roll out a full 10 in tall image.

## Layout

| Path | What lives there |
|---|---|
| `research/sources/` | One `.md` per source. Header: ID, URL, date read, type. Body: key claims, quotes under 15 words. ID format `S###`. |
| `research/topics/` | Notes merged by topic: geometry, materials, relief-depth, seams, axles-handles, clay-behavior, printing-cnc, failure-modes. Every claim cites `S###`. |
| `research/INDEX.md` | Every source: ID, title, one-line note, trust 1-5. |
| `skill/pottery-roller/SKILL.md` | Numbered rules (`R##`): value, reason, sources, confidence. The generator enforces these. |
| `skill/pottery-roller/references/` | Long tables the rules point to. |
| `app/` | The generator (engine + web UI + tests). |
| `redteam/` | `potter.md`, `engineer.md`, `ux.md` and the second-pass reports. |
| `decisions.md` | Every choice owner makes and every rejected red-team finding, dated. |

## Model routing

- Haiku subagents: scraping, source collection, summarizing a page into a source note.
- Sonnet subagents: code, UI, tests, topic merges.
- Opus (main agent): planning, writing rules, judging red-team findings.
- Research subagents run in parallel, write files, and return 10 lines or less. Raw pages never enter the main context.

## Skills

- **agent-reach**: Reddit, YouTube transcripts (yt-dlp), forums, RSS, any page WebFetch cannot read (Jina Reader). Twitter/X and the Reddit CLI backend are off on this machine; read Reddit through Jina (`https://r.jina.ai/https://old.reddit.com/...`) or the `.json` endpoint.
- **functional-cad**: all CAD logic. Numeric brief first, build123d for the parametric model, cylinder wrap, bore/handles, export and gate checks. Fusion only when owner asks.
- **hallmark**: every UI and visual decision in `app/`.

## Hard rules

- No FEA or structural simulation. Geometric and printability checks only.
- The engine names the rule number (`R##`) whenever it warns or blocks an export.
- Printed text on Windows: ASCII only (cp1252 console).
- Stop at each checkpoint in the brief and wait for owner.
