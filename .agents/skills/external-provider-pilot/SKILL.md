---
name: external-provider-pilot
description: Bring up an OpenShift cluster on `platform: external` driven by a non-integrated CAPI infrastructure provider, or debug one that stalls. Use when adding a third provider, reproducing the OCI pilot, or diagnosing a run that reaches Ready nodes but not 34/34 operators. Encodes what thirteen OCI runs cost to learn.
argument-hint: [provider-short-name] — e.g. capoci, capz
allowed-tools: Bash Read Write Edit Grep Glob
version: 1 (2026-10-01, from divergences 073-078; first provider arc completed)
---

# External provider pilot

**Scope.** Everything here was learned installing OpenShift on OCI through CAPOCI with
an unmodified installer. Most of it is **not OCI-specific** — that is the point of
having written it down. Each item says whether it generalises.

**The one-line result this encodes:** `platform: external` + a CAPI provider the
installer was never compiled against produced 34/34 operators with **zero installer
changes**. The hard parts were not Cluster API.

---

## 1. Before anything, what order to attack in

The failure modes arrive in a fixed order, and each one masks the next. Work them in
this sequence or you will debug the wrong layer.

| # | Gate | Symptom when it fails | Generic? |
| --- | --- | --- | --- |
| 1 | boot image + platform ID | nodes never appear, or appear as `localhost.localdomain` | **yes** |
| 2 | bootstrap ignition delivery | bootstrap instance boots and does nothing | **yes** for any cloud with a metadata size cap |
| 3 | `api-int:22623` reachable | masters boot, never get their config | **yes** |
| 4 | provider ID + CCM | nodes `NotReady`, `uninitialized` taint never removed | **yes** |
| 5 | CSR approval | workers never join | **yes** |
| 6 | **ingress** | **everything Ready, 29/34 operators, `authentication` + `console` down** | **yes** |
| 7 | teardown | orphans after `destroy cluster` | **yes** |

Gate 6 is the one nobody predicts. Budget for it.

---

## 2. The findings that cost the most, shortest first

### A successful `connect()` to a nodePort proves nothing

The listening socket belongs to ovnkube. `connect()` succeeds, *then* OVN picks an
endpoint, and the drop happens after the handshake. A connect-then-hang is the
signature of a **remote** endpoint being unreachable, not of a missing listener.

Corollary: a nodePort over the IPv4 loopback is **not a path OVN serves**
(`route_localnet=0`, nft rather than iptables-nat). `127.0.0.1:<nodePort>` timing out
is correct behaviour and is not a diagnostic.

### `platform: external` routers are on the host network, and that changes the firewall

The ingress operator defaults to `endpointPublishingStrategy.type: HostNetwork`. So:

1. **Nothing asks the cloud for an external address.** The only Service the operator
   creates is a ClusterIP. You must ship a `Service` of `type: LoadBalancer` as a day-0
   extra manifest and let the partner CCM build the load balancer.
2. **The Service's endpoints are node IPs on 80/443**, so OVN balances a request
   arriving at node A to a router on node B — node A connects to node B's `:443`. **The
   node security groups need 80/443 ingress from the cluster CIDR.** Every careful,
   complete-looking node port list omits this, because on integrated platforms the
   routers are not on the host network.

Source those rules from the VCN/VPC CIDR, **never** `0.0.0.0/0`.

### Generated identifiers cannot be in day-0 manifests — and this is the contract, not a quirk

Two unrelated controllers demanded it: the CAPI provider's machine placement, and the
CCM's load-balancer security group. **A manifest authored before the infrastructure
exists cannot contain an identifier the infrastructure generates.** This is what the
`postProvision` hook is *for*. Expect to find a third instance on provider three.

### Out-of-band fixes to a reconciled resource are not fixes

Both the CAPI provider and the CCM reset changes made with the cloud CLI, within the
minute. Whatever a controller reconciles must come from the object it reconciles from.
The exception measured so far: a *second listener* added to a load balancer survived,
because the provider's equality check compared only display name and health checker and
never enumerated listeners. **Verify that by reading the equality function**, not by
watching for a minute.

### The convenient address field is the wrong one, in both directions

`Service.status.loadBalancer.ingress[0].ip` gave the **private** address where the
public zone needed the public one. The provider's API-LB helper gave the **public**
address where `api-int` needed the private one. Same object, two consumers, opposite
errors. Under split-horizon DNS — the normal OpenShift arrangement — **always resolve
both and publish deliberately**.

### Only the first document of a multi-document extra manifest is applied

`countManifestDocuments`, `pkg/asset/manifests/openshift.go:426`. Nothing warns. An
upstream CCM bundle is multi-document almost without exception, so **split it to one
object per file** and record provenance (upstream SHA-256 per file) so a re-copy is a
diff.

`manifestFileExtensions` at `:453` is `.yaml`/`.yml`/`.json`. A `.day2` suffix makes the
installer copy but not apply a file — the usable way to ship an object whose CRD arrives
later (e.g. `VolumeSnapshotClass`).

### An annotation the controller does not recognise is silently ignored

Not rejected, not logged, not defaulted. The only symptom is dropped traffic. **Do not
guess annotation keys.** Get the authoritative list from the shipped binary:

```sh
oc exec -n <ns> <pod> -- \
  grep -aoE "<vendor-domain-pattern>/[a-zA-Z0-9_-]+" /usr/local/bin/<binary> | sort -u
```

Watch for prefix families: choosing a load-balancer *type* can change the prefix every
other annotation must use.

### Written teardown is not tested teardown

The standing rule — every created resource ships with its teardown in the same increment
— held, and the teardown path still had two bugs, because it had never run. Also:

- **If the CCM tags nothing, a tag sweep is impossible.** Capture the OCID/ARN at
  post-provision and record it in the hook's state file.
- **Check the obvious repair before making it.** A name-contains sweep on the infra ID
  matched the *API* load balancer and would have deleted the cluster's own endpoint.

---

## 3. The runbook

### Phase 0 — artifacts

Build the provider's manager binary and `infrastructure-components.yaml`. Check the
installer's controller argument list (`pkg/clusterapi/external.go`) against the
provider's flags one by one — `-v`, `--webhook-port`, `--webhook-cert-dir`,
`--kubeconfig`, `--health-addr`. pflag exits non-zero on an unknown flag, so one
mismatch is fatal.

**A `#!/bin/sh` wrapper is a legal `binaryPath`** and `validateHostArch`
(`pkg/clusterapi/artifacts.go:195-200`) says so explicitly. Translate the flag; do not
drop it — the installer polls `/healthz` at exactly the address it passed.

### Phase 1 — manifests and substitution

```sh
./openshift-install create manifests --dir="${INSTALL_DIR}"
```

Read the infra ID from `manifests/cluster-infrastructure-02-config.yml`. It is the
cluster name **plus a five-character random suffix**, and the `Cluster` object's name
must equal it or `Machine.spec.clusterName` will not resolve.

> **The generated manifest tree is a credential store** — TLS and CA private keys, the
> pull secret, the kubeadmin hash. Inspect it by filename and size. `grep -oE '^  infrastructureName: .*'`
> is safe because its output is bounded by the pattern. **A range `sed` is never safe**
> whatever its endpoints look like.

### Phase 2 — ignition, and the offload if the cloud needs one

```sh
./openshift-install create ignition-configs --dir="${INSTALL_DIR}"
```

If the cloud caps instance metadata below the bootstrap ignition size: upload
`bootstrap.ign` to object storage, mint a time-limited unauthenticated URL, and
**overwrite `<install-dir>/bootstrap.ign` with a ~300-byte pointer config**. The
installer reloads it — `bootstrap.Bootstrap` implements `Load()`
(`pkg/asset/ignition/bootstrap/bootstrap.go:39-41`) and sits in the IgnitionConfigs
target (`pkg/asset/targets/targets.go:56-64`). **No installer change.**

> That URL is credential-equivalent: it grants unauthenticated read over every day-0
> secret. Never log it. Redact it out of serial-console output before reading:
> `sed -E 's|https?://[^ ")]*|<URL-REDACTED>|g'`.

### Phase 3 — install, and what the hooks must do

```sh
./openshift-install create cluster --dir="${INSTALL_DIR}"
```

| Hook | Fires | Must do |
| --- | --- | --- |
| `infraReady` | network exists, no machines | second LB listener for 22623; `api`/`api-int` DNS; CCM and CSI config Secrets (**the OCIDs are in the provider CR's `spec`, not its `status`**) |
| `postProvision` | control-plane machines created, cluster API serving, before `wait-for bootstrap-complete` | populate the 22623 backend set; attach the LB security group **by generated ID**; publish `*.apps` to **both** zones with the right address in each; **record the ingress LB's ID for teardown** |
| `preDestroy` | teardown | everything above, plus the ignition object and its URL |

`infraReady` **cannot** write into `<install-dir>/openshift/` — the installer has
already consumed and removed that tree. Apply from `postProvision` against
`$OPENSHIFT_INSTALL_KUBECONFIG`. Ship the partner DaemonSets as day-0 manifests so the
gap is a DaemonSet waiting on a Secret, not a cluster waiting on a DaemonSet.

`run-create-command.sh <n> infra-only` (via `OPENSHIFT_INSTALL_INFRASTRUCTURE_ONLY`)
stops after `infraReady` and creates no machines. **Use it first on a new provider** —
it exercises DNS, the extra listener and the config Secrets for the price of a network.

### Phase 4 — the manual steps that remain

```sh
oc get csr -o name | xargs -r oc adm certificate approve
```

Worker CSRs still need approval. Not provider-specific; a webhook comparing a CSR to the
instance it claims to come from is the right fix and does not exist.

### Phase 5 — teardown

`destroy cluster` **excludes Secrets** from `.clusterapi_output/`
(`pkg/infrastructure/clusterapi/clusterapi.go:696-700`), so the destroy path must restore
the provider's credential Secret or the infra-cluster finalizer never clears.

---

## 4. Diagnosing a stall

| Observation | First thing to check |
| --- | --- |
| nodes named `localhost.localdomain` | the boot image's `ignition.platform.id` — afterburn is querying a metadata service that is not there |
| node `NotReady`, `uninitialized` taint | `KUBELET_PROVIDERID`, then whether the CCM pod exists at all, then whether its config Secret exists |
| CCM pod does not exist | **count the documents in the extra manifest you shipped** |
| hook's apply fails `namespaces "x" not found` | same cause; the hook is innocent |
| 29/34 operators, `authentication` + `console` down | ingress. Is there a `Service` of `type: LoadBalancer`? Does the LB have a security group? Do the **node** groups allow 80/443? |
| LB healthy, Service correct, routers serving, traffic times out | node-to-node 80/443 |
| intermittent `connection refused` to `api-int:6443` | a dead backend still registered — often an orphaned bootstrap from a previous failed run |

Read installer logs through a redacting wrapper or with narrow greps. **Never `cat` or
`tail` a run log wholesale**, and filter `set -x` trace lines out of monitoring greps —
one can carry an ignition URL.

---

## 5. What to record

Every run that teaches something becomes a numbered divergence under
`implementation-plans/01-openshift_self-managed/divergences/`, with type, the quoted plan
text it contradicts, `file:line` at a recorded commit, what was done, and proposed plan
text. Batch them into one plan version at the end — see `plan-new-version`.

**Label the unverified.** "I never A/B tested this" is worth more in the record than a
plausible claim. And treat "someone said it was fixed" as a hypothesis.
