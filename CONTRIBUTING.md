# Contributing to Reality Layer

Thanks for your interest. The project is in the **design phase** — there is no
implementation yet. Contributions right now are mostly about sharpening the architecture
and MVP plan.

## Ground rules

- Read [`docs/reality-layer-technical-architecture.md`](docs/reality-layer-technical-architecture.md)
  and [`docs/mvp-design.md`](docs/mvp-design.md) first.
- Keep proposals scoped to the MVP boundary. Anything outside it belongs in the
  "Deferred" columns or a follow-up issue, not the MVP.
- Prefer typed events, explicit provenance, and append-only history in any design you
  propose — these are load-bearing principles, not style choices.

## Ways to contribute

| Type | How |
| --- | --- |
| Architecture feedback | Open a **Design proposal** issue |
| Bug in the docs (wrong claim, broken link, inconsistency) | Open a **Bug report** issue |
| New capability idea | Open a **Feature request** issue |
| Small fixes (typos, formatting) | PR directly |

## Pull requests

1. Branch from `main`: `git checkout -b <short-topic>`.
2. Keep changes focused; one concern per PR.
3. For doc changes, make sure internal links and section numbers still line up.
4. Reference the issue the PR addresses (`Closes #123`).
5. Commit messages: imperative mood, short subject, body explaining *why*.

## Once implementation starts

This section will grow to cover local setup, linting (ruff), typing (mypy), tests
(pytest), and the connector/mapping contract-test process. Until then, code PRs will
likely be asked to wait for the Phase 0 scaffold.

## Code of conduct

Be respectful and assume good faith. Harassment or abuse is not tolerated.
