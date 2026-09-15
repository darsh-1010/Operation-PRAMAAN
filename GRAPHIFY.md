# graphify

Codebase-to-knowledge-graph tool. Binary lives on the external SSD:
`/Volumes/ExternalSSD/tools/bin/graphify` (put `/Volumes/ExternalSSD/tools/bin` on `PATH`, or
call it by full path). It's already wired into this repo:

- `graphify claude install` ran → CLAUDE.md has a graphify section + `.claude/settings.json`
  PreToolUse hook (Claude checks the graph before answering codebase questions).
- `graphify codex install` ran → AGENTS.md has a graphify section + `.codex/hooks.json` hook.

Everything graphify writes lives under `graphify-out/` (not created yet — see Quickstart).

## Quickstart for this repo

```bash
# 1. Build the initial graph (AST + semantic LLM pass). Needs one backend API key
#    (GEMINI_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY / etc.) or --backend ollama for local.
graphify "/Volumes/ExternalSSD/Codebase/Operation PRAMAN" --backend claude

# 2. After editing code, keep the graph current — no API cost, just re-parses AST:
graphify update "/Volumes/ExternalSSD/Codebase/Operation PRAMAN"

# 3. Ask it things instead of grepping across 4 services + frontend:
graphify query "how does risk-scoring-engine consume Score A/B/C?"
graphify path "ocr-consistency-check" "risk-scoring-engine"
graphify explain "hard_fail"
graphify god-nodes --top 10
```

`graphify-out/graph.json` is the source of truth every other command reads by default
(`--graph <path>` overrides it). It's fine for `graphify-out/` to show as dirty in git after a hook
or `update` run — that's expected, not a problem to fix.

## Command reference

### Build / update the graph
| Command | Does |
|---|---|
| `graphify <path> [--backend B] [--mode deep] [--force] [--code-only] [--postgres DSN] [--cargo] [--global] [--as tag]` | Full build: AST extraction + semantic LLM pass + clustering. `--code-only` skips LLM (no API key needed). `--force` re-scans everything (use after big refactors/deletes). |
| `graphify update <path> [--force] [--no-cluster]` | Incremental re-extract, AST only, no LLM cost. Run this after every edit. |
| `graphify extract <path> [--backend B] [--mode deep] [--force] [--max-workers N] [--token-budget N] [--max-concurrency N]` | Headless full extraction for CI/scripts (same engine as the plain build). |
| `graphify watch <path>` | Rebuild on file changes, for a long-running dev session. |
| `graphify cluster-only <path> [--no-viz] [--no-label]` | Rerun community clustering on an existing graph.json. |
| `graphify label <path> [--missing-only] [--backend B]` | (Re)name communities via LLM. |
| `graphify check-update <path>` | Cron-safe: flags if a semantic re-extraction is pending. |

### Ask questions (read-only, cheap)
| Command | Does |
|---|---|
| `graphify query "<question>" [--dfs] [--context C] [--budget N]` | BFS/DFS traversal answering a question from the graph — usually far smaller than raw grep or the full report. |
| `graphify path "A" "B"` | Shortest path between two nodes. |
| `graphify explain "X"` | Plain-language explanation of a node + neighbors. |
| `graphify affected "X" [--relation R] [--depth N]` | Reverse traversal: what breaks if X changes. |
| `graphify god-nodes [--top N] [--json]` | Most-connected nodes — the architectural hubs / hotspots. |
| `graphify diagnose multigraph [--json] [--directed\|--undirected]` | Reports edge-collapse risk from same-endpoint edges. |

### Memory / feedback loop
| Command | Does |
|---|---|
| `graphify save-result --question Q --answer A [--outcome useful\|dead_end\|corrected] [--correction TEXT]` | Log a Q&A outcome to `graphify-out/memory/` to improve future answers. |
| `graphify reflect [--half-life-days N] [--min-corroboration N]` | Aggregates memory into `graphify-out/reflections/LESSONS.md`. |

### Cross-repo / global graph
| Command | Does |
|---|---|
| `graphify global add <graph.json> [--as tag]` | Merge a project graph into `~/.graphify/global-graph.json`. |
| `graphify global remove <tag>` / `global list` / `global path` | Manage the global graph. |
| `graphify merge-graphs <g1> <g2> [--out path]` | Merge two+ graphs into one cross-repo graph. |
| `graphify clone <github-url> [--branch B] [--out dir]` | Clone a repo and print its path for graphing. |

### Export / visualize
| Command | Does |
|---|---|
| `graphify tree [--graph PATH] [--output HTML] [--root PATH]` | D3 collapsible-tree HTML view of the graph. |
| `graphify export callflow-html` | Mermaid-based architecture/call-flow HTML. |
| `graphify benchmark [graph.json]` | Measures token reduction vs. naive full-corpus grep/read. |

### Git integration
| Command | Does |
|---|---|
| `graphify hook install` / `hook uninstall` / `hook status` | Post-commit/post-checkout hooks that keep the graph in sync automatically. |
| `graphify merge-driver <base> <current> <other>` | Git merge driver for graph.json (set up via `hook install`). |

### Editor / agent integration (already done for this repo)
`graphify install --platform <name>` (or the shorthand `graphify <platform> install`, e.g.
`graphify claude install`) wires graphify into an AI coding tool. Platforms: `claude`, `codex`,
`opencode`, `aider`, `agents` (generic AGENTS.md/skill), `cursor`, `gemini`, `windows`, `codebuddy`,
`copilot`, `vscode`, `kilo`, `claw`, `droid`, `trae`, `trae-cn`, `antigravity`, `hermes`, `kiro`,
`pi`, `devin`. Each has a matching `<platform> uninstall`. `graphify uninstall [--purge]` removes
graphify from every detected platform at once (`--purge` also deletes `graphify-out/`).

## Notes

- `graphify update` needs no API key (AST-only). The full `graphify <path>` build and `label` do,
  unless you pass `--code-only` or `--backend ollama`.
- Re-run `graphify update .` (or let the git hook do it) after any code change before trusting
  `graphify query` output — a stale graph gives stale answers.
