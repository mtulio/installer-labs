---
name: capi-source-map
description: Re-derive the verified map of what blocks platform:external from using CAPI in the OpenShift installer. Use before making any claim about installer CAPI behaviour, before writing a plan change instruction, or after rebasing the installer clone. Produces a barrier table with file:line citations and a recorded commit.
argument-hint: (no arguments)
allowed-tools: Bash(git:*) Bash(grep:*) Bash(rg:*) Bash(sed:*) Bash(find:*) Bash(ls:*) Bash(md5sum:*) Read Grep Glob
---

CAPI Source Map
===============

Rebuild the barrier map from the installer source. **Do not copy the table from a previous
plan version or from a previous run of this skill** — the point of this skill is that the
claims are re-derived. Plan versions v3 and v4 inherited an inaccurate four-barrier model
precisely because it was copied forward.

Work in [installer/](installer/) unless told otherwise.

## 1. Record provenance

```bash
git -C installer rev-parse --short HEAD
git -C installer log -1 --format='%H %cs %s'
git -C installer status --short
```

Every claim you emit is scoped to this commit. Say so in the output. If the working tree is
dirty, note that too — a local pilot branch changes the answers.

## 2. Trace the provisioning path in code order

Follow the real execution order, not the order a document lists things. For each step,
record what happens for an integrated platform (`aws`) and what happens for `external`.

1. **Platform dispatch** — `ProviderForPlatform` in
   `pkg/infrastructure/platform/platform.go`. Which platforms have a case? What is the
   error for one that does not?
2. **Cluster metadata** — `pkg/asset/cluster/metadata.go` writes
   `ClusterPlatformMetadata`; `ClusterPlatformMetadata.Platform()` in
   `pkg/types/clustermetadata.go` reads it back. Check whether the platform you care about
   has a member at all — if it does not, `Platform()` returns `""`.
3. **CAPI system start** — `system.Run` in `pkg/clusterapi/system.go`. Note the order:
   local control plane, component unpack, core controller, `metadata.Load`, the empty
   platform guard, then the platform switch. Which failure is hit *first*?
4. **Controller resolution** — `getInfrastructureController` and `runController` in the
   same file. Record exactly how `Path`, `Components`, `Args` and `Env` are computed, and
   which of them already accept arbitrary values versus which are hardcoded conventions.
5. **Binary source** — `Provider.Extract` in `pkg/clusterapi/providers.go` and the
   `//go:embed mirror/*` declaration. Note how `Provider.Sources` filters zip entries.
6. **Scheme and CRD install** — `init()` and the `Scheme` variable in
   `pkg/clusterapi/localcontrolplane.go`; the `envtest.InstallCRDs` and
   `envtest.WebhookInstallOptions` calls in `runController`. Installing a CRD makes the
   resource available to the local API; it does **not** register Go types in the client
   scheme. Confirm this is still true before repeating it.
7. **CAPI cluster manifests** — the platform switch in
   `pkg/asset/manifests/clusterapi/cluster.go`. Some platforms `return nil` early, meaning
   no `Cluster` or infrastructure CR is generated at all.
8. **CAPI machine manifests** — the platform switch in `pkg/asset/machines/clusterapi.go`,
   same pattern.
9. **Lifecycle hooks** — the interfaces in `pkg/infrastructure/clusterapi/types.go` and
   where each is invoked in `pkg/infrastructure/clusterapi/clusterapi.go`. Record each
   hook's exact signature, especially what it returns.

## 3. Record the extension points that already exist

These matter as much as the barriers, and are routinely missed:

- The `text/template` vocabulary available in controller args (`runController`), and which
  arg the installer appends itself.
- Whether the health check is mandatory or conditional on a particular arg being used.
- Any provider that is already selected as a runtime *variant* rather than by platform name.
- How `data/data/cluster-api/*-infrastructure-components.yaml` is produced —
  `hack/verify-capi-manifests.sh` builds some from source and downloads others as release
  assets. Note which, by name.
- The provider build pipeline: `cluster-api/providers/<name>` → `cluster-api/Makefile` →
  `hack/build-cluster-api.sh` → embedded zip.
- Existing `OPENSHIFT_INSTALL_*` environment overrides, as precedent for unsupported
  developer-only switches:
  ```bash
  grep -rn "OPENSHIFT_INSTALL_" --include='*.go' installer/pkg installer/cmd | grep -E 'Getenv|LookupEnv'
  ```

## 4. Output

Emit two tables and a short note.

**Barriers**, in code-execution order:

| # | Barrier | Symptom | `file:line` |
| --- | --- | --- | --- |

**Existing extension points**:

| Mechanism | What it already allows | `file:line` |
| --- | --- | --- |

Then: the commit you verified against, anything you could not verify, and any place where
a previous plan version disagrees with what you just read. Flag disagreements explicitly —
they are the input to the next plan change instruction.

Do not propose an implementation here. This skill establishes facts; design happens in the
plan.
