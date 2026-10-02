---
name: plan-new-version
description: Generate the next version of an enhancement plan HTML from the latest version plus a written change instruction. Use when a change to the self-managed or HyperShift plan has been decided and an instruction file exists under implementation-plans/. Never edits a published version in place.
argument-hint: <track> <instruction-file> — e.g. 01-openshift_self-managed implementation-plans/01-openshift_self-managed/v5-instruction.md
allowed-tools: Bash(ls:*) Bash(grep:*) Bash(sed:*) Bash(md5sum:*) Bash(python3:*) Bash(git:*) Read Write Edit Glob Grep
version: 2 (2026-10-01; §3 rewritten around build-vN.py after v16 — the base is now 700 KB and hand-editing it is no longer safe)
---

Generate Next Plan Version
==========================

Arguments: **$ARGUMENTS** — a track directory name and a change-instruction file.

## Tracks

| Track | File family | Instruction dir |
| --- | --- | --- |
| `01-openshift_self-managed` | `external-platform-installer-capi-enhancement-v<N>.html` | `implementation-plans/01-openshift_self-managed/` |
| `02-hypershift_managed` | `platform-external-hypershift-enhancement-v<N>.html` | `implementation-plans/02-hypershift_managed/` |

For the self-managed track, note that versions v0–v2 use the older
`capi-external-enhancement-v<N>.html` name. Numbering is continuous across the rename.

## Procedure

### 1. Resolve inputs

Find the highest existing `vN` for the track and the instruction file. Record `md5sum` of
the base file — you will confirm at the end that it is unchanged.

**Do not read the base version in full.** By v16 it is ~700 KB; a whole-file read costs
more than the increment and crowds out the verification work that matters. Read the
instruction file in full, then read **only the regions you will anchor against** —
`grep -n` for the anchor text, `sed -n 'A,Bp'` for the surrounding tags, and
`grep -c` for the structural counts you will re-check at the end. The script in step 3 is
what guarantees the rest is carried forward byte-for-byte, so you do not need to have
read it.

The instruction file is a **change order**, not a new plan. It tells you what to correct,
what to add and what decision to record. Everything it does not mention is carried forward
verbatim.

### 2. Verify before you write

Any claim about installer behaviour — the instruction's or the base document's — must be
checked against the local clone. Run the `capi-source-map` skill, or spot-check the
specific `file:line` citations involved. Plan versions v3 and v4 lost accuracy by
reasoning from earlier documents instead of from code; do not repeat that.

If the instruction asserts something the code contradicts, stop and say so rather than
writing it into the document.

### 3. Build `vN+1` with a script, not by hand

Write `implementation-plans/<track>/build-v<N+1>.py`, run it once, and keep it. The script
**copies the base verbatim** and applies a short list of **asserted single-match
substitutions**. Nothing else may differ.

```python
#!/usr/bin/env python3
"""Build vN+1 from vN by verbatim copy plus asserted surgical insertions."""
import hashlib, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "external-platform-installer-capi-enhancement-v15.html"
OUT  = ROOT / "external-platform-installer-capi-enhancement-v16.html"
BASE_MD5 = "05993645242fd5c1cc3f8c39a303f6fb"

src = BASE.read_text(encoding="utf-8")
assert hashlib.md5(src.encode()).hexdigest() == BASE_MD5, "base changed — stop"
doc = src

def sub(old, new, label):
    """Replace exactly once, or fail loudly."""
    global doc
    n = doc.count(old)
    if n != 1:
        sys.exit(f"ANCHOR {label!r}: expected 1 match, found {n}")
    doc = doc.replace(old, new, 1)
    print(f"ok  {label}")

sub("<title>… v15 …</title>", "<title>… v16 …</title>", "title")
# … one sub() per item in the instruction …

OUT.write_text(doc, encoding="utf-8")
assert BASE.read_text(encoding="utf-8") == src, "base was modified — stop"
print(f"wrote {OUT.name}  {len(doc)} chars  (+{len(doc)-len(src)})")
```

Why this shape and not an `Edit` pass over the HTML:

- **A silent miss is the v3/v4 failure mode.** A substitution whose anchor has drifted
  produces a plausible-looking document with one correction quietly absent — exactly the
  kind of error this project exists to prevent. `sub()` exits non-zero instead.
- **An anchor matching twice is just as bad as matching zero times**, and is the more
  likely accident in a document that repeats its own banner markup. Assert `== 1`, never
  `>= 1`.
- **Carry-forward becomes structural rather than diligent.** Everything the instruction
  does not name is untouched by construction, so "preserve the whole document" stops being
  something to verify and starts being something the tool cannot violate.
- **It is re-runnable and reviewable.** The script is the diff, in a form a human can read
  in a minute, and it re-derives the output from the base if anything needs amending.

Choose anchors that include **structural tags, not just prose** — `"…sentence.</p></section>\n<section id=\"drawbacks\">"` rather than `"…sentence."`. Prose repeats; a
prose-plus-closing-tag-plus-next-section-id string does not.

Build the large insertions as named Python constants (`SEC16 = """…"""`) above the `sub()`
calls, so the call list reads as a table of contents for the change.

Rules for the content itself, which also appear as Appendix A inside the documents:

- **Never overwrite a previous version.** Write a new file.
- **Preserve the whole document.** Every template section, diagram, table, reference and
  appendix carries forward unless it is demonstrably wrong.
- **Correct visibly.** A wrong finding is replaced *and* marked as a correction, with the
  superseded claim retained nearby or in an appendix. Silent deletion loses the audit
  trail.
- **Cite code as `file:line`**, scoped to a stated commit. Label anything unverified as
  unverified — a labelled gap is worth more than a plausible-looking placeholder.
- **Label proposals as proposals.** Interface names, config schemas and code snippets that
  do not exist must be marked as design sketches, not existing API.
- **Keep it standalone and offline.** Inline all CSS and SVG. No CDN, no external fonts,
  images or scripts. Every diagram needs a caption or text alternative.
- **Keep section order** aligned with the OpenShift enhancement template.
- **Keep the local/target distinction.** Local CAPI state, especially Secrets, does not
  reach the installed cluster. Never blur this.
- **No credentials or customer-specific values** anywhere in the artifact.
- **Do not reprioritise gates** (CAPA parity first, then CAPOCI/External) unless the
  instruction explicitly says a human changed the priority.

### 4. Append the Appendix C entry

Every version gets a history entry: version, date, reason, additions, corrections, open
decisions. Retain all prior entries.

Each entry records AI attribution: the tool/agent, the model identifier **only when
independently verified and permitted to disclose**, whether the model is confirmed, and
which human reviewed it. When the model is not verifiable, write `not disclosed`. Never
infer a model from output quality and never guess.

### 5. Check before handing off

Run all of these. Each one has caught something, or guards something that has gone wrong
before. Report the numbers, not the word "clean".

**1 — the base is untouched.** `md5sum` equals the value recorded in step 1 and asserted
in the script.

**2 — tags balance, and counts only grow.** Compare opening and closing counts for each
structural tag, in the new file *and* against the base:

```sh
for t in section h2 h3 table li p details; do
  printf '%-9s base %4s/%-4s  new %4s/%-4s\n' "$t" \
    "$(grep -o "<$t[ >]" "$BASE" | wc -l)" "$(grep -o "</$t>" "$BASE" | wc -l)" \
    "$(grep -o "<$t[ >]" "$OUT"  | wc -l)" "$(grep -o "</$t>" "$OUT"  | wc -l)"
done
```

Open must equal close in the new file, and every new count must be **≥** the base's unless
the instruction removed something. A count that *dropped* means an anchor swallowed
content — the one failure mode `sub()` cannot catch, because the replacement matched once
and was simply too greedy.

**3 — it still opens offline.** Zero `<script src`, `<link href`, `<img src`, `<iframe`,
`@import`, and zero non-anchor external `src=`. Count `https\?://` and require it to equal
the base's count plus whatever prose references the instruction added — a *new* URL that
nobody asked for is the signal.

**4 — zero dangling anchors.** Every `href="#x"` must have a matching `id="x"`. New
sections are linked from new banners, and a typo there is invisible on screen:

```sh
python3 - "$OUT" <<'PY'
import re, sys
doc = open(sys.argv[1]).read()
ids = set(re.findall(r'id="([^"]+)"', doc))
bad = sorted({h for h in re.findall(r'href="#([^"]+)"', doc)} - ids)
print("dangling:", bad or "none")
PY
```

**5 — appendices.** A, B, C, D (and E, once added) present; Appendix C lists **every**
version from v0 to the new one, with no gap.

**6 — every instruction item landed.** The script's `ok <label>` lines are the receipt;
check the count against the instruction's item count, and grep the output for one distinct
phrase per item.

**7 — credential and customer-value sweep, as a delta not an absolute.** Count the
markers (`ocid1\.`, `arn:aws:`, cluster-name prefixes, the base domain, public IPs,
machine-local paths) in the base and in the new file and require the counts to be
**equal**. Pre-existing occurrences are carried forward by the append-only rule and must
not be "fixed"; what matters is that the increment added none. A bare absolute count
invites exactly the wrong remedy — editing the base.

Report what changed, what was preserved, and anything in the instruction you could not
verify. If a check could not be run, say so; do not round it to a pass.
