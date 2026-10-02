"""Split Oracle's CCM and CSI bundles into one-object-per-file extra manifests.

WHY SPLIT. `extra-manifests/` files land in `<install-dir>/openshift/`, and the
bootstrap node applies that directory ONE OBJECT PER FILE -- every document
after the first in a multi-document file is silently ignored. The installer
refuses such a file at `create manifests` time
(pkg/asset/manifests/openshift.go, countManifestDocuments), so a multi-document
bundle is not merely wrong, it does not build.

MEASURED 2026-10-01, run 13. An earlier revision of this generator emitted the
two bundles as single multi-document files. They were installed with a binary
built BEFORE that guard existed, so nothing rejected them, and the cluster came
up with the `oci-cloud-controller-manager` and `oci-csi` Namespaces -- document
1 of each file -- and none of the other 16 objects. No DaemonSet, no RBAC, no
CSI driver. The hook's Secrets applied cleanly into the empty namespaces, so
the only symptom was nodes that never left NotReady.

The long-form rationale for the deltas, the supply-chain finding and the
day-0/day-1 split lives in extra-manifests/oci-ccm-csi-bundle.md, not repeated
in all eighteen headers.
"""

import hashlib
import pathlib

import yaml

SRC = pathlib.Path("oci-openshift/custom_manifests/oci-ccm-csi-drivers/v1.34.0")
DST = pathlib.Path(
    "installer/upi/external/examples/oci-capoci/external-install/extra-manifests"
)

# Deltas against upstream, keyed by source file. Everything else is copied
# byte-for-byte so `diff` against the source shows exactly these and nothing
# else.
CCM_IMAGE_OLD = "ghcr.io/nikhisin3001/cloud-provider-oci:v1.34.0"
CCM_IMAGE_NEW = "ghcr.io/oracle/cloud-provider-oci:v1.34.0"

HEADER = """# yamllint disable rule:indentation rule:brackets
#
# COPIED, NOT WRITTEN -- object {n} of {total} from Oracle's bundle.
#
#   source  oci-openshift/custom_manifests/oci-ccm-csi-drivers/v1.34.0/{src}
#   sha256  {sha}
#   object  {kind}/{name}
#
# One object per file because the bootstrap node applies this directory one
# object per file and silently drops the rest of a multi-document one; the
# installer refuses such a file outright. See oci-ccm-csi-bundle.md in this
# directory for the full account: why these are day-0 while their config
# Secrets are not, what the two deltas against upstream are, and the
# partner-manifest supply-chain gap this bundle exposes.
#
# The yamllint disable is cosmetic only -- Oracle indents sequences and writes
# `[ "x" ]`, both of which this repository's .yamllint rejects. Reformatting a
# vendored file was tried and broke it; see oci-ccm-csi-bundle.md.
{delta}---
"""

DELTA_NONE = "#\n"

DELTA_CCM_IMAGE = """#
# THIS FILE CARRIES DELTA 1: the controller image is Oracle's namespace, not
# the personal GHCR namespace upstream v1.34.0 points at. The two tags have
# DIFFERENT digests, so this is a substitution and not a rename. Rationale and
# both digests are in oci-ccm-csi-bundle.md.
#
"""


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_documents(text):
    """Split on document separators, keeping each document's original text.

    yaml.safe_load_all would lose formatting and comments, and the whole point
    of a mechanical copy is that the text survives. So the text is split here
    and parsed only to learn each document's kind and name.
    """
    docs, current = [], []
    for line in text.split("\n"):
        if line.rstrip() == "---":
            docs.append("\n".join(current))
            current = []
        else:
            current.append(line)
    docs.append("\n".join(current))
    return docs


def emit(src_name, prefix, day2_kinds=frozenset()):
    src = SRC / src_name
    text = src.read_text()
    digest = sha256(src)

    raw_docs = split_documents(text)
    parsed = [yaml.safe_load(d) for d in raw_docs]

    objects = [(r, p) for r, p in zip(raw_docs, parsed) if p is not None]
    total = len(objects)
    written = []

    for index, (raw, obj) in enumerate(objects):
        kind = obj["kind"]
        name = obj["metadata"]["name"]

        delta = DELTA_NONE
        if CCM_IMAGE_OLD in raw:
            raw = raw.replace(CCM_IMAGE_OLD, CCM_IMAGE_NEW)
            delta = DELTA_CCM_IMAGE

        # A slug, not the object name: `system:cloud-controller-manager` and
        # `fss.csi.oraclecloud.com` are both legal names and neither is a
        # filename anyone wants.
        slug = "".join(c if c.isalnum() else "-" for c in name.lower())
        slug = "-".join(part for part in slug.split("-") if part)

        stem = f"{prefix}-{index:02d}-{kind.lower()}-{slug}.yaml"
        if kind in day2_kinds:
            # Not a manifest extension, so the installer skips it
            # (manifestFileExtensions is .yaml/.yml/.json) while `oc apply -f`
            # still works on it unchanged once the CRD exists. This replaces
            # the old approach of commenting the object out line by line,
            # which left it unusable without an edit.
            stem += ".day2"

        header = HEADER.format(
            n=index + 1,
            total=total,
            src=src_name,
            sha=digest,
            kind=kind,
            name=name,
            delta=delta,
        )
        (DST / stem).write_text(header + raw.lstrip("\n").rstrip("\n") + "\n")
        written.append(stem)

    return written


def main():
    # Remove the superseded combined files so a stale copy cannot be applied.
    for stale in ("99_external-02-oci-ccm.yaml", "99_external-03-oci-csi.yaml"):
        path = DST / stale
        if path.exists():
            path.unlink()
            print(f"removed {stale} (superseded by the split)")

    for stem in emit("01-oci-ccm.yml", "99_external-02-oci-ccm"):
        print(f"wrote {stem}")
    for stem in emit(
        "01-oci-csi.yml", "99_external-03-oci-csi", day2_kinds={"VolumeSnapshotClass"}
    ):
        print(f"wrote {stem}")

    # Prove the split is lossless: every object in the source must appear in
    # exactly one output file, parsed equal. The previous reformat attempt
    # produced a file that no longer parsed and was caught only by a check like
    # this one.
    verify()


def verify():
    for src_name, prefix in (
        ("01-oci-ccm.yml", "99_external-02-oci-ccm"),
        ("01-oci-csi.yml", "99_external-03-oci-csi"),
    ):
        source = [
            d
            for d in yaml.safe_load_all((SRC / src_name).read_text())
            if d is not None
        ]
        emitted = []
        for path in sorted(DST.glob(f"{prefix}-*")):
            loaded = [
                d for d in yaml.safe_load_all(path.read_text()) if d is not None
            ]
            assert len(loaded) == 1, f"{path.name} holds {len(loaded)} objects"
            emitted.append(loaded[0])

        assert len(source) == len(emitted), (
            f"{src_name}: {len(source)} objects in, {len(emitted)} out"
        )
        for before, after in zip(source, emitted):
            if CCM_IMAGE_OLD in yaml.safe_dump(before):
                before = yaml.safe_load(
                    yaml.safe_dump(before).replace(CCM_IMAGE_OLD, CCM_IMAGE_NEW)
                )
            assert before == after, (
                f"{src_name}: {before['kind']}/{before['metadata']['name']} "
                "changed in the split"
            )
        print(f"verified {src_name}: {len(source)} objects, round-trip equal")


if __name__ == "__main__":
    main()
