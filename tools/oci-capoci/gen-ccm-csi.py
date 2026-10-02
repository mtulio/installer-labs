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
import subprocess

import yaml

# Upstream. `oracle-quickstart/oci-openshift` is the real home of this bundle;
# `oracle/oci-openshift` does not exist and an earlier revision of these
# headers named it.
UPSTREAM_URL = "https://github.com/oracle-quickstart/oci-openshift"
UPSTREAM_ROOT = pathlib.Path("oci-openshift")
BUNDLE_PATH = "custom_manifests/oci-ccm-csi-drivers/v1.34.0"

SRC = UPSTREAM_ROOT / BUNDLE_PATH
DST = pathlib.Path(
    "installer/upi/external/examples/oci-capoci/external-install/extra-manifests"
)

# Deltas against upstream, keyed by source file. Everything else is copied
# byte-for-byte so `diff` against the source shows exactly these and nothing
# else.
CCM_IMAGE_OLD = "ghcr.io/nikhisin3001/cloud-provider-oci:v1.34.0"
CCM_IMAGE_NEW = "ghcr.io/oracle/cloud-provider-oci:v1.34.0"

HEADER = """# yamllint disable rule:indentation rule:brackets rule:line-length rule:comments
#
# COPIED, NOT WRITTEN -- object {n} of {total} from Oracle's bundle.
#
#   upstream  {url}
#   commit    {commit}
#   ref       {ref}
#   path      {bundle}/{src}
#   sha256    {sha}
#   object    {kind}/{name}
#
# TRACKING UPSTREAM DRIFT. The permalink to the exact bytes this was copied
# from is the upstream URL, then `/blob/`, then the commit, then the path --
# all three are above. To check for drift, hash the current upstream file and
# compare with the sha256 above:
#
#   git -C oci-openshift fetch origin && \\
#     git -C oci-openshift show origin/main:{bundle}/{src} | sha256sum
#
# If it differs, re-run tools/oci-capoci/gen-ccm-csi.py against the new
# checkout. Do not hand-edit this file: it is generated, and a hand edit makes
# the sha256 above a lie, which is the one thing that would make this header
# worse than no header at all.
#
# One object per file because the bootstrap node applies this directory one
# object per file and silently drops the rest of a multi-document one; the
# installer refuses such a file outright. See oci-ccm-csi-bundle.md in this
# directory for the full account: why these are day-0 while their config
# Secrets are not, what the two deltas against upstream are, and the
# partner-manifest supply-chain gap this bundle exposes.
#
# The yamllint disable is cosmetic only, and every rule in it is a house style
# this repository applies to code it writes: Oracle indents sequences, writes
# `[ "x" ]`, puts one space before a trailing comment and runs container args
# past 120 columns. Reformatting a vendored file to satisfy them was tried and
# broke it, and it would also destroy the one property that makes the sha256
# above useful -- that these bytes can be diffed against upstream. See
# oci-ccm-csi-bundle.md.
{delta}"""

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


def git(*args):
    """Read something out of the upstream clone, or "" if it cannot be read.

    Degrades rather than failing: the sha256 is the authoritative provenance
    and is computed from the bytes themselves. The commit and ref make the
    bytes locatable, which is a convenience on top of that -- not a reason to
    refuse to generate.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(UPSTREAM_ROOT), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def upstream_provenance():
    """Commit and human-readable ref of the checkout being copied from."""
    commit = git("rev-parse", "HEAD") or "UNKNOWN (not a git checkout)"

    tag = git("describe", "--tags", "--exact-match")
    date = git("show", "-s", "--format=%cs", "HEAD")
    ref = ", ".join(part for part in (f"tag {tag}" if tag else "", date) if part)

    # An uncommitted change in the clone means the sha256 below does not
    # correspond to anything fetchable, which is exactly the case a reader
    # must not be left to discover by a failing diff.
    if git("status", "--porcelain", "--", BUNDLE_PATH):
        ref = (ref + ", " if ref else "") + "LOCALLY MODIFIED -- not fetchable"

    return commit, ref or "unknown"


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
    commit, ref = upstream_provenance()

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
            url=UPSTREAM_URL,
            commit=commit,
            ref=ref,
            bundle=BUNDLE_PATH,
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
