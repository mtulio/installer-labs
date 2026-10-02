# Generators for the oci-capoci example's extra-manifests

These live here, never inside `installer/` — per [AGENTS.md](../../AGENTS.md)
the clone stays clean of workspace scaffolding. They emit files **into** the
clone, which sits beside this repository at the workspace root.

| Script | Emits | Run from |
| --- | --- | --- |
| `gen-hostname-mc.py` | `99_external-01-oci-hostname-{master,worker}.yaml` | the `extra-manifests/` directory |
| `gen-ccm-csi.py` | `99_external-02-oci-ccm.yaml`, `99_external-03-oci-csi.yaml` | the workspace root |

## Why generators and not hand-edited YAML

`gen-hostname-mc.py` exists because the unit's script is base64 inside an
Ignition data URL. Hand-editing base64 is how a typo becomes a boot failure
nobody can read. The script is kept as plain Python text, reproduced in a
comment block in the output, and encoded mechanically.

`gen-ccm-csi.py` exists because its output is a **copy of Oracle's bundle**
with a small number of named deltas. Keeping the copy mechanical means a new
upstream version is re-copied rather than hand-merged, and that the deltas
cannot silently drift. It asserts on every anchor it substitutes, so an
upstream change that moves them fails loudly instead of producing a
half-applied edit.

## After running either one

```sh
cd ../installer && hack/yaml-lint.sh && hack/shellcheck.sh
```

yamllint baseline is exit 0. shellcheck baseline is exit **1**, over a
pre-existing SC1117 in `data/data/bootstrap/files/usr/local/bin/konnectivity-certs.sh`
plus pre-existing SC2086/SC2016 notes under `upi/external/examples/aws-capa/scripts/`.
Compare against that baseline, not against exit 0.
