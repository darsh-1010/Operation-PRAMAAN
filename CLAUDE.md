# Operation PRAMAN

AI-based fake identity & document screening system (SIH26188). Full context: [README.md](README.md).

4 independent Python microservices (`services/ocr-consistency-check`, `visual-image-forensics`,
`biometric-matching`, `risk-scoring-engine`) + `frontend/`, each with its own Dockerfile/requirements.txt.
They fan out from the same two inputs, run in parallel, and feed `risk-scoring-engine` for the final
ACCEPT/MANUAL REVIEW/REJECT decision. Don't merge services or share a requirements.txt across them —
that's deliberate, not an oversight.

## Coding standards

Lazy > clever. Before adding code, check: does this already exist in the repo / stdlib / an
installed dependency? Reuse before writing.

- **File size**: soft cap ~300 lines, hard stop and split by ~500. A file past that is doing more
  than one job.
- **Function size**: soft cap ~40 lines. If you can't name what it does in one line, split it.
- **No speculative abstraction**: no interface/base class for one implementation, no config flag
  for a value that never changes, no plugin system for a single plugin. Build for the case in
  front of you.
- **No new dependency for what a few lines of stdlib does.** If you do add one, put it in that
  service's `requirements.txt` only — never the repo root.
- **Cross-service contract, not cross-service imports.** Services talk over the HTTP API shape
  described in the README (score, `hard_fail`, reason codes) — never import another service's
  code directly.
- **Secrets**: never commit real `.env` values — only `.env.example` with placeholders.
- **Untrusted file uploads**: every image/video comes from the public. See [SECURITY.md](SECURITY.md)
  before touching upload handling in the frontend or writing any backend service's ingest path.
- **Tests**: non-trivial logic (a branch, a parser, a scoring rule, anything security/money-shaped)
  gets one runnable check — an `assert`-based self-check or a small `test_*.py`. Skip tests for
  trivial one-liners.
- **Errors**: validate and fail loudly at service boundaries (API input, file uploads, model
  outputs); don't swallow exceptions.
- **Delete over add.** If a change makes older code redundant, remove it in the same PR rather
  than leaving it "for later."

See [AGENTS.md](AGENTS.md) for the same rules in the AGENTS.md convention, and
[GRAPHIFY.md](GRAPHIFY.md) for the codebase-graph tool set up below.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
