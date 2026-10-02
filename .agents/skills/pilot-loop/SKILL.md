---
name: pilot-loop
description: Run the autonomous implement-and-review loop that delivers the Gate-1 CAPA artifact-override pilot in the installer clone. Use when asked to develop, review or continue the pilot, or to resume an interrupted run. Covers bootstrap, the four-agent iteration, the envtest integration phase, local commits, and cutting the next plan version from accumulated divergence records.
---

Pilot Loop
==========

Delivers the Gate-1 pilot described in §6 of the latest
`external-platform-installer-capi-enhancement-v*.html` at the workspace root, into
[installer/](../../../installer/) on branch `pilot-platform-external-capi`.

The orchestrator is whoever invokes this skill. The five experts in
[.agents/agents/](../../agents/) do the work. If a custom agent type is not registered in the
current session, dispatch a `general-purpose` agent whose prompt begins: *"First read
`<workspace>/.agents/agents/<name>.md` in full and adopt it as your operating instructions."*
The definition file is the source of truth either way.

## Hard boundaries

- **Stop at the envtest boundary.** No `create cluster`, no cloud call, no credential use.
  The run ends by reporting which of the plan's claims remain unproven.
- **Never push, never open a PR.** Commits land locally on `pilot-platform-external-capi`.
- **Plan HTML is append-only.** Never edit a published `vN`; emit `vN+1`.
- **Keep the clone clean.** Everything this skill creates outside `installer/` stays outside
  it. `git -C installer status --short` must show only intended Go and docs files.
- **Never log credentials or file contents.** Path, source and SHA-256 only.
- **Local CAPI state is not the target cluster.** Never describe an object in the envtest
  control plane as reaching the cluster being installed.

## Time bound and graceful stop

The loop is capped at **four iterations or two hours of wall clock, whichever comes first**.
Record the deadline before iteration 1 and check it before dispatching any agent — never
mid-flight. An agent already running is allowed to finish; the loop simply does not start
another round.

Reaching the cap is a normal outcome, not a failure. Wind down in this order and skip
nothing:

1. Stop dispatching reviewers. Let in-flight agents return.
2. Bring the mechanical gate green if it is not. If it cannot be, leave the tree as it is —
   do not commit code that does not build.
3. Write divergence records for every unresolved finding, typed `plan-incomplete` or
   `deliberate-deviation`, each naming what was not settled and what evidence is missing.
4. Commit whatever is green (Phase 3). Partial work committed locally on a branch is
   recoverable; uncommitted work in a context that has ended is not.
5. Cut the plan version (Phase 4) from the records that exist.
6. Report: what converged, what did not, and the exact question a human needs to answer to
   unblock each open item.

"No consensus" specifically means reviewers still disagree about a finding after the
verification step, or a finding reappears in two consecutive iterations without a fix that
all three accept. Do not break the tie by picking a side — record both positions with their
`file:line` evidence and let the plan version carry the disagreement forward.

## Phase 0 — bootstrap

Required, not optional: `pkg/clusterapi/mirror/` ships with only a README, so there is no
embedded path until a build produces the zip (divergence 004).

```sh
cd installer
git rev-parse --abbrev-ref HEAD          # expect pilot-platform-external-capi
rm -f pkg/clusterapi/mirror/cluster-api.zip   # divergence 008: the script's own clean is a no-op
./hack/build.sh                          # sources build-cluster-api.sh, runs make -C cluster-api all
unzip -l pkg/clusterapi/mirror/cluster-api.zip
```

Expect ~375 MB and 13 entries: `cluster-api`, ten providers, `etcd`, `kube-apiserver`. Takes
several minutes and downloads envtest v1.35.0 from GitHub (divergence 005). Do **not** run
`hack/build-cluster-api.sh` directly — it is a non-executable sourced library and silently
no-ops under `sh` (divergence 003).

Re-verify the clone is clean afterwards; the zip is gitignored.

## Phase 1 — the iteration, capped at 4

**1. Implement.** `pilot-implementer` writes or fixes against §6.3/§6.4, then runs the
mechanical gate:

```sh
go build ./pkg/clusterapi/...
gofmt -s -l pkg/clusterapi/          # NOT hack/go-fmt.sh — it fails on any dirty tree (divergence 010)
hack/go-vet.sh ./...
IS_CONTAINER=TRUE go test -short ./pkg/clusterapi/...
./hack/go-lint.sh ./pkg/clusterapi/...   # ~90s, podman; must report 0 issues
```

Gate red ⇒ fix and re-run. Do not dispatch reviewers against code that does not build.

**The linter belongs in the gate, not in review.** Iteration 1 of the first run was declared
green and sent to three reviewers while failing `hack/go-lint.sh` with five findings
(divergence 019) — because the gate omitted it. It costs 90 seconds and it is the difference
between "compiles" and "could merge". Note `--new-from-rev` makes it diff-scoped, so it
reports only what this change introduced.

**2. Review, in parallel.** `capi-local-controlplane`, `installer-domain` and
`pilot-adversary`, each returning findings as:

```
file:line | severity | claim | concrete failure scenario | suggested fix
```

**3. Verify.** Re-check every finding against the clone yourself. Drop anything without a
reproducible failure scenario. This is the guard against the v3/v4 failure mode — confident
claims that the code does not support.

**4. Triage.** Findings about the *code* feed the next iteration. Findings about the *plan*
become divergence records, written immediately.

Exit when the gate is green and verification confirms no new findings, or at iteration 4 —
then report what is still open rather than declaring success.

## Phase 2 — envtest integration

`capi-local-controlplane` writes the integration tests in `pkg/clusterapi/` — as delivered,
`TestRunControllerArtifactOverrideIntegration` and `TestRunControllerEmbeddedBinaryIntegration`.
They follow the convention the repo already ships: `hack/go-integration-test.sh:4` selects by
`-run .Integration`, a test-name suffix, not a build tag (divergence 006).

Conventions, all three required:

- name ends `Integration`;
- `t.Skip` under `testing.Short()`, so `hack/go-test.sh` (which passes `-short`) is unaffected;
- `t.Skip` when `pkg/clusterapi/mirror/cluster-api.zip` is absent, naming `./hack/build.sh`
  in the skip message;
- set `command.RootOpts.Dir` to a `t.TempDir()`.

It starts the local control plane, points the override at
`cluster-api/bin/linux_amd64/cluster-api-provider-aws`, and asserts the controller starts and
goes healthy, its CRDs and rewritten webhooks install, `Provider.Extract` is not reached, and
teardown is clean. Then the same assertions with no env vars set — the regression guarantee.

```sh
go test -count=1 -p 1 -parallel 1 -timeout 0 -run .Integration ./pkg/clusterapi/...
```

Run it directly, **not** through `hack/go-integration-test.sh`. That script's package list is
hardcoded and `"$@"` is appended, not substituted, so `./pkg/clusterapi/...` narrows nothing —
it is already inside `./pkg/...` (233 packages either way). You get the full suite, including
`cmd/openshift-install`'s `TestAgentIntegration`, which fails without `oc`, `nmstatectl` and CI
registry credentials, and that failure is easy to misread as the pilot's (divergence 023).

**This is the pilot's actual proof.** Everything before it is compilation.

## Phase 3 — commit

One commit per §6.9 slice on `pilot-platform-external-capi`, plus one for the integration
test. Installer commit format (`<subsystem>: <what>` / blank / why), subsystem `cluster-api`,
`docs` or `integration tests`. No push. No PR.

**Every commit must build on its own.** A split that compiles only in aggregate has not been
tested — the plan's own §6.9 split did not compile, because `applyArtifactOverride` writes a
struct field the next commit was going to add (divergence 018). Verify the whole series:

```sh
git rebase --exec 'go build ./pkg/clusterapi/...' <base>
```

Splitting one file across two commits is legitimate when the boundary is logical; stage it by
writing the intermediate version of the file rather than by interactive hunk selection, which
is not available here.

## Phase 4 — cut the next plan version

`plan-divergence-scribe` batches **every** file in
[implementation-plans/01-openshift_self-managed/divergences/](../../../implementation-plans/01-openshift_self-managed/divergences/)
into `v{N+1}-instruction.md`, then produces
`external-platform-installer-capi-enhancement-v{N+1}.html` via the `plan-new-version` skill.

One version at the end of the run — records accumulate during it, so an interrupted run still
leaves the evidence.

Before finishing: base version's md5 unchanged; the new file opens offline (no `script`,
`img`, `link`, `iframe`, no external `src`); tags balanced; Appendices A–D present and
Appendix C lists every version; no credentials anywhere.

## Reporting

Say plainly what passed, what failed with its output, and what was skipped. The §6.8 cloud
parity run is out of scope by design — name it as unproven rather than implying Gate 1 passed.
