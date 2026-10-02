---
name: installer-verify
description: Run the pre-handoff gate for changes in the installer clone — format, lint, vet, unit tests, vendor and codegen verification. Use before declaring any installer change done or opening a PR.
argument-hint: [package path] (default: whole repo)
allowed-tools: Bash(go:*) Bash(git:*) Bash(hack/*) Bash(make:*) Bash(grep:*) Bash(ls:*) Read Grep Glob
---

Installer Pre-Handoff Verification
==================================

Scope: **$ARGUMENTS** (default: the whole repository).

Run from [installer/](installer/). Authoritative sources are
[installer/AGENTS.md](installer/AGENTS.md), [installer/CLAUDE.md](installer/CLAUDE.md) and
[installer/CONTRIBUTING.md](installer/CONTRIBUTING.md) — if they disagree with this file,
they win.

## Gate

```sh
hack/go-fmt.sh .
hack/go-lint.sh $(go list -f '{{ .ImportPath }}' ./...)
hack/go-vet.sh ./...
hack/go-test.sh
hack/verify-vendor.sh
hack/verify-codegen.sh
```

Narrow the scope while iterating (`hack/go-test.sh -v -run TestX ./pkg/clusterapi/...`),
but run the full set before handoff. Add `hack/shellcheck.sh` if you touched shell, and
`hack/yaml-lint.sh` if you touched YAML.

### Non-Go files count, and they have their own baselines

A change can add zero lines of Go and still fail this repository. Copying pilot YAML into
`upi/external/` introduced **15 `yamllint` errors** into a repo that had zero — all
`indent-sequences: false` violations, **semantically a no-op**, and invisible to every tool
that had consumed those exact files across four cluster installs.

- `hack/yaml-lint.sh` — baseline is **exit 0**. Any failure is yours.
- `hack/shellcheck.sh` — baseline is **exit 1**, over a pre-existing `SC1117` in
  `data/data/bootstrap/files/usr/local/bin/konnectivity-certs.sh`. Compare against that,
  not against zero, and state which findings you introduced.

Two rules when fixing these:

1. **Prove a lint fix is semantically inert** if the file is also a tested artifact — parse
   before and after and require equal objects. Do not assume the linter's complaint was
   cosmetic because it looked cosmetic.
2. **Do not blanket-fix `SC2086`.** Some lines rely on glob expansion
   (`"${DIR}"/machines/*.yaml`); quoting the whole word breaks them. Quote the variable, not
   the word.

If you changed anything under `cluster-api/providers/` or
`data/data/cluster-api/`, also run `hack/verify-capi-manifests.sh` — it regenerates the
component manifests in a container and fails on any diff.

## Checklist

- **No generated file edited by hand.** `zz_generated.deepcopy.go`,
  `data/data/install.openshift.io_installconfigs.yaml` (regenerate with
  `go generate ./pkg/types/installconfig.go`), mocks under `pkg/asset/mock/`
  (`hack/go-genmock.sh`), and `data/data/cluster-api/*.yaml`.
- **Imports are grouped** stdlib / third-party / `github.com/openshift` / blank, and
  follow the repo's alias conventions (`awstypes`, `awscapi`, `icazure`, `capimanifests`,
  …). `hack/go-fmt.sh .` handles ordering; aliases are on you.
- **New exported types and fields have doc comments.**
- **Unit tests cover the new behaviour**, table-driven per
  [docs/testing-guidelines.md](installer/docs/testing-guidelines.md).
- **No credentials in logs, errors or collected artifacts.** See
  [docs/security-guidelines.md](installer/docs/security-guidelines.md).
- **Errors are wrapped** per
  [docs/error-handling-guidelines.md](installer/docs/error-handling-guidelines.md).
- **Default behaviour for existing platforms is unchanged** — for CAPI work this means an
  AWS install with no override behaves exactly as before.
- `git status --short` shows only intended files.

## Reporting

Report results faithfully: name each command, say whether it passed, and paste the output
of anything that failed. If you skipped a step, say which and why — do not describe a
partial run as a clean one.
