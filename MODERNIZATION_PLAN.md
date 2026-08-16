# Modernization plan — Autonomous Coding Agent Crew

Cite current state from [ARCHITECTURE.md](ARCHITECTURE.md). This file is the forward plan.

## 1. Executive summary

The stack is already modern (Python 3.12, uv, ruff, ty, pytest, CI). Do **not** rewrite CrewAI, LangGraph, or Streamlit. Modernize the **product contract**: green must mean the request held, and a job should become a reviewable patch instead of a toy `runs/` tree. Three small phases, then one optional larger phase.

## 2. Current state assessment

From [ARCHITECTURE.md](ARCHITECTURE.md):

- **Stack:** Python 3.12, uv, CrewAI, LangGraph, Streamlit. Commands inventory in Architecture Part 1.
- **Domain:** planner → coder → tester → debugger (max 3) → documenter. Fresh `runs/<uuid>`. `### FILE:` whole-file writes.
- **Pain:** tester sees the impl snapshot; debugger can rewrite tests; documenter runs on red; coverage ~45%; no e2e; chromadb transitive advisory ignored in CI; Streamlit `invoke`s the graph in-request; no git remote / no commits.
- **Deploy:** local process + optional Ollama. No containers.

## 3. Feasibility spike & strategy

**Spike (this session, ~10 minutes of real runs — no Streamlit process):**

| Probe | `agent_crew` + tests | Streamlit UI |
| --- | --- | --- |
| Install from lockfile | Yes (`uv sync --all-groups`) | same env |
| Native/build | Yes (`uv_build` package) | n/a |
| Boot | n/a (library) | **not launched** (AGENTS.md ban) |
| ≥1 meaningful test | Yes — 4/4 `uv run pytest` | **no UI tests** |

**Strategy:** **(A) Freeze-then-lift** for `agent_crew`. The library is alive. Default (B) walking-skeleton is the wrong shape here.

| Component | Testability Milestone | Regime now | Safety rung | Residual risk |
| --- | --- | --- | --- | --- |
| `agent_crew` | **Already crossed** | lit | **L3** | No coverage gate; no tests for `run_crew` / `llm.py` / `crew.py` |
| `streamlit_app.py` | UI testability **deferred** (Phase 4 optional or never) | lit for code, dark for automated UI | **L1** | Behavior verified by reading the file only |
| CI workflow | Authored | runs if GitHub exists | **L3** when pushed | Enforcement `[UNVERIFIED]` — no remote |

**CI Milestone:** workflow already exists ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)). **Enforcing** required checks is a **human** GitHub Settings step after the first push. Agent cannot do it.

**Oracle:** no production instance. Rank: **code-as-spec** + existing pytest as characterization of workspace/routing. After Phase 1, add a **self-frozen** mutation/protect-tests golden. Residual: first new test is only as correct as we write it.

**Economic triage:** not a multi-user prod service on disk. Cheap L3 is enough. L4 e2e that launches Streamlit is **dropped** while AGENTS.md forbids UI servers.

## 4. Target architecture

Keep the modular monolith. Same process. Same graph. Change write protocol and success definition only.

| Component | Action |
| --- | --- |
| Python 3.12 / uv / ruff / ty / pytest | Keep |
| CrewAI + LangGraph | Keep |
| Streamlit UI | Keep (queue-only later if Phase 4) |
| `### FILE:` apply | Wrap: add `protect_tests` |
| Success = pytest green | Upgrade: lock tests + optional mutation probe |
| `runs/` toys | Adapt later: worktree + `git apply` (Phase 4) |
| chromadb | Leave transitive; keep CI ignore unless CrewAI pins a fix |
| Extra agents / RAG | Remove from scope (YAGNI) |

### ADR: Do not replace CrewAI or LangGraph

- **Context:** Modernization often defaults to “throw the framework.”
- **Decision:** Level 1 — keep. The loop is ~170 lines and works.
- **Alternatives:** pytest-only orchestrator — rewrite cost > honesty-gate cost.
- **Consequences:** Still pay CrewAI/LangGraph upgrades. Accept chromadb transitive until upstream moves.

### ADR: Honesty gates before real-repo patches

- **Context:** Green today can mean “tester rewrote asserts.”
- **Decision:** Phase 1 `protect_tests` + tester-before-coder optional later; mutation probe. Phase 4 real-repo is **deferred**, not dropped.
- **Alternatives:** Jump to worktrees first — bigger blast, still sycophant tests.

### ADR: No Streamlit launch in agent/CI

- **Context:** [AGENTS.md](AGENTS.md)#L18.
- **Decision:** Drop UI e2e. CI stays unit/lint/ty/audit.

## 5. Per-feature migration analysis

### Control loop (`graph.py`)

- **Now:** START→planner→coder→tester↔debugger→documenter. Exhausted still documents.
- **Strategy:** A, incremental refactor.
- **Testability:** already lit. Rung L3.
- **Coupling:** `workspace.apply_files`, `route_after_tester`.
- **Effort:** S (fail-closed) / M (tester-first rewire).
- **Risk:** Locked bad tests burn 3 debugs.
- **Accept:** `route_after_tester` tests stay green; new cases for mutant-survived / protect_tests.

### Workspace (`workspace.py`)

- **Now:** regex FILE blocks, path jail, pytest subprocess.
- **Strategy:** A, add flags/helpers. Do not replace with a framework.
- **Effort:** S.
- **Accept:** existing `test_apply_files_and_pytest` + `test_safe_file_rejects_escape` stay green.

### Providers (`llm.py`)

- **Now:** allowlist + Ollama tags.
- **Strategy:** Leave in place.
- **Effort:** XS unless adding a provider.

### Streamlit UI

- **Now:** form + `run_crew` in-process.
- **Strategy:** Leave in place until Phase 4 (queue-only).
- **Effort:** M if decoupled.
- **Risk:** long blocking request — known, not a stack problem.

## 6. Phased implementation plan

**Gate rule:** `agent_crew` is **lit**. Every phase below exits on runnable commands from the inventory: `uv run ruff check .`, `uv run ty check src/`, `uv run pytest`. Do not start Phase N+1 until Phase N’s boxes are checked. Cut each phase branch from trunk (`master` today; rename to `main` is a human choice, deferred). Merge to trunk before the next phase (H7).

**CI Milestone:** already authored. After first GitHub push, **you** enable branch protection.

### Phase 1: Honesty net (T-shirt: S)

**Goal:** Coder/debugger cannot rewrite `test_*.py`. Optional one-AST mutation after first green.
**Regime:** lit
**Safety rung:** L3 (still no coverage fail-under)
**Prerequisites:** none (library already testable)
**Duration:** one short PR (~30–45 min)

#### Tasks

| ID | Task | Component | Blocked by |
| --- | --- | --- | --- |
| 1.1 | `apply_files(..., protect_tests=False)` skip `test_*.py` / `*_test.py` when True | workspace | — |
| 1.2 | Wire `protect_tests=True` in coder + debugger only | graph | 1.1 |
| 1.3 | Test: protected apply does not write `test_foo.py` | tests | 1.1 |
| 1.4 | `probe_one_mutation(workspace)` — one AST flip, restore bytes | workspace | — |
| 1.5 | Test: `assert True` survives; `assert add(2,3)==5` dies; file unchanged | tests | 1.4 |
| 1.6 | Call probe on first tester green; survived → `tests_passed=False` + note in `test_output` | graph | 1.4 |

#### Risks

- **Risk:** Debugger “fixes” impl to match vacuous tests. → **Mitigation:** 1.6 routes as fail; later tester-first is deferred (Phase 2), not in this PR.
- **Risk:** Equivalent mutant (`pass`) false-fails. → **Mitigation:** skip `If` with `Constant(True)` / empty `FunctionDef` body `[decided]`.

#### Decisions made

- Tester-before-coder rewire: **deferred** to Phase 2.
- Coverage fail-under 80: **dropped** (suite is 45%; would fail CI).
- H1: not removing a dependency family — **cleared**.
- H2: no framework major — **cleared**.
- H3: no runtime bump — **cleared**.
- H4: no edge/auth rewrite — **cleared**.
- H5: no datastore — **cleared**.
- H6: no insecure shim — **cleared**.
- H7: one PR to trunk — **cleared**.
- H8: update ARCHITECTURE + README if `apply_files` signature is user-visible — **task 1.7 in DoD**.

#### Verification & Exit Criteria

- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run ty check src/`
- [ ] `uv run pytest` — old 4 tests + new protect/mutation tests green
- [ ] Deliberate red: temporarily force `protect_tests` off in the new test and confirm it fails, then revert (“net has teeth”)
- [ ] README / ARCHITECTURE mention protect_tests if the public write contract changed
- Residual L3: no `run_crew` integration test (needs LLM). Closed never unless a fake `run_role` is injected — **deferred**.

### Phase 2: Fail-closed + tester-first (T-shirt: S)

**Goal:** Exhausted debug writes a repro and **skips documenter**. First tester visit locks tests before coder (optional if 1.x already enough).
**Regime:** lit
**Safety rung:** L3
**Prerequisites:** Phase 1 merged to trunk
**Duration:** one PR (~30 min)

#### Tasks

| ID | Task | Blocked by |
| --- | --- | --- |
| 2.1 | `route_after_tester`: exhausted → `END` or new `repro` node, not documenter | Phase 1 |
| 2.2 | Repro writes `REPRO.md` (command + `test_output`) | 2.1 |
| 2.3 | Tests for exhausted ≠ documenter | 2.1 |
| 2.4 | **Deferred in-phase default:** tester-first rewire only if 1.x still shows sycophant tests in a manual run | — |

#### Decisions made

- Tester-first graph rewire: **deferred** unless Phase 1 is not enough (default: skip 2.4).
- Documenter on red: **dropped** as success path.
- H1–H6: N/A — **cleared**. H7 trunk merge. H8 update routing diagram in ARCHITECTURE.md.

#### Verification & Exit Criteria

- [ ] `uv run pytest` including new exhausted-route test
- [ ] `uv run ruff check .` / `uv run ty check src/`
- [ ] ARCHITECTURE state-machine mermaid matches code

### Phase 3: Hygiene only if needed (T-shirt: XS)

**Goal:** First commit + GitHub remote + human CI enforcement. No behavior change.
**Regime:** lit
**Safety rung:** L3
**Prerequisites:** none (can run parallel after Phase 1 if you want a remote sooner)
**Duration:** human ~15 min

#### Tasks

| ID | Task |
| --- | --- |
| 3.1 | Initial commit on `master` (or rename to `main` — **human decision**) |
| 3.2 | Add GitHub remote and push |
| 3.3 | **You:** Settings → Branches → require `check` + `hooks` |

#### Verification

- [ ] CI ran on the default branch `[UNVERIFIED]` until remote exists
- [ ] Required checks enabled — **user action**, not agent-done
- [ ] No behavior/dependency change

### Phase 4: Real-repo patch (T-shirt: M) — deferred

**Goal:** `git worktree` + `git apply` hunks; input = failing nodeid. Streamlit queues only.
**Regime:** lit for library; UI still L1
**Prerequisites:** Phase 1–2
**Duration:** 1–2 PRs

**Dropped from v1 of this plan unless you say go:** dual-apply fallback, `gh pr create`, pytest watcher, RAG, extra agents.

Do not start Phase 4 until Phase 1–2 exit criteria are recorded.

## 7. Execution governance

- Branch `phase-N-short-name` from **trunk `master`** (unborn today — Phase 3 makes it real).
- One PR per phase. Merge to trunk before the next branch (H7).
- Lit exit = `uv run ruff check .` + `uv run ty check src/` + `uv run pytest` on the PR.
- Update this file’s checkboxes and [ARCHITECTURE.md](ARCHITECTURE.md) in the same PR (H8).
- Do not overwrite [`.github/copilot-instructions.md`](.github/copilot-instructions.md) (caveman). Commands live in [`.github/copilot-instructions.modernization.md`](.github/copilot-instructions.modernization.md) — merge by hand if you want Copilot to load them.

## 8. Migration safety net

- **Flags:** none. Phases are merged features, not flagged.
- **Data:** no DB. `runs/` is ephemeral (gitignored). H5 N/A.
- **Rollback:** revert the phase PR.
- **Transitional-insecure (H6):** none planned. CI ignore of `PYSEC-2026-311` is a tracked exception (CrewAI transitive; no Chroma server). Close when CrewAI pins a fixed chromadb — not a phase here.
- **Oracle:** pytest on workspace + routing. Self-frozen mutation/protect tests after Phase 1.
- **Testing:** add only the tests each phase names. No Streamlit launch.
- **Observability:** none beyond `CrewState["log"]`. Leave it.

## 9. Open questions (human only)

1. Enable GitHub branch protection after first push? (CI Milestone enforcement)
2. Rename `master` → `main`? Default: **deferred**, keep `master` until you say otherwise.
3. Start Phase 4 (real-repo patches) after Phase 2, or stop at honesty gates?
4. Publish a LICENSE? Out of scope for this plan.
