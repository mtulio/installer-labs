---
name: installer-capi-pilot
description: Run the Gate-1 CAPA artifact-override pilot loop in the installer clone — build provider binaries and the installer, capture a baseline install with the embedded CAPA path, then repeat with a local binary/components override and compare. Use when developing or validating the artifact-source seam.
argument-hint: [baseline|override|compare] (default: guide through all three)
allowed-tools: Bash(make:*) Bash(go:*) Bash(git:*) Bash(grep:*) Bash(sed:*) Bash(ls:*) Bash(find:*) Bash(diff:*) Bash(md5sum:*) Bash(sha256sum:*) Bash(file:*) Bash(hack/*) Bash(bin/openshift-install:*) Read Write Edit Grep Glob
---

Gate-1 CAPA Artifact-Override Pilot
===================================

Mode: **$ARGUMENTS**

Gate 1 proves that the installer can load a CAPA controller binary and component manifest
from outside its embedded bundle **without changing AWS behaviour**. It does not
demonstrate External-platform support, and a passing run must never be described as if it
did. A green health probe is not parity.

Run everything from [installer/](installer/).

## Build

```bash
make -C cluster-api all          # builds cluster-api/bin/<goos>_<goarch>/cluster-api-provider-*
hack/build.sh                    # zips them into the embedded mirror, builds bin/openshift-install
```

`MODE=dev hack/build.sh` keeps debug symbols. `SKIP_TERRAFORM=y` is faster.

The local override artifact for the pilot is the **same binary** the embedded path uses —
`cluster-api/bin/$(go env GOOS)_$(go env GOARCH)/cluster-api-provider-aws` — so the
comparison isolates the loading mechanism rather than a version difference. The matching
component manifest is `data/data/cluster-api/aws-infrastructure-components.yaml`.

Equivalently, and preferably once the installer is built, take both from the binary itself:

```bash
bin/openshift-install extract cluster-api aws --dest-dir=<abs dir>
```

This hidden command writes the controller binary and the matching component manifest, and
prints their SHA-256. Taking both from the same binary removes the chance of pairing a
binary with a component manifest from a different build, which is the one failure this
comparison cannot tolerate: it would look like an artifact-seam defect.

## Baseline run

Install with the unmodified embedded path and keep everything:

- the full installer log at debug level (`--log-level=debug`)
- `<dir>/.clusterapi_output/` — `envtest.kubeconfig`, `etcd.log`, `kube-apiserver.log`,
  and the collected non-Secret CAPI manifests
- the rendered controller command line (the installer logs `Running process: … with args …`)
- timings for: local control plane up, controller healthy, `infrastructureReady`, machines
  ready, teardown

## Override run

Same install config, same infra ID pattern, with the pilot override in effect. The agreed
mechanism is developer-only environment variables following the existing
`OPENSHIFT_INSTALL_*` idiom — no install-config field, no API review:

```
OPENSHIFT_INSTALL_EXPERIMENTAL_CAPI_PROVIDER_AWS_BINARY=<abs path to cluster-api-provider-aws>
OPENSHIFT_INSTALL_EXPERIMENTAL_CAPI_PROVIDER_AWS_COMPONENTS=<abs path to aws-infrastructure-components.yaml>
```

Before starting the controller, the resolver validates the artifact: file exists, is
regular and executable, architecture matches the host, and its hash is recorded. Log the
source and hash; never log credentials or file contents.

## Compare

Parity requires all of:

- identical AWS routing — `ProviderForPlatform`, the AWS manifest generators and every AWS
  lifecycle hook are untouched
- both runs reach `Cluster.status.infrastructureReady` and machine readiness
- controller health checks pass and teardown completes in both
- the collected CAPI artifacts match apart from expected identifiers and timestamps
- destroy succeeds from both

## Negative tests

Each must fail clearly, early, and without leaking credentials — and, where possible,
before any cloud resource is created:

| Case | Expected |
| --- | --- |
| override path does not exist | fail at resolution |
| path is a directory, or not executable | fail at resolution |
| binary built for the wrong architecture | fail at resolution or at process start, with a readable error |
| components YAML from a mismatched provider version | fail at CRD/webhook install |
| unrecognised controller flag | fail at process start or health timeout |
| health check never becomes ready | bounded timeout, controllers stopped, cleanup runs |

## Reporting

State plainly which checks passed, which failed with their output, and which were skipped.
Record the installer commit, the CAPA build, and both artifact hashes. If parity fails,
reproduce on the embedded path first to confirm the regression is in the artifact seam.

Finish with [installer-verify](../installer-verify/SKILL.md) before any handoff.
