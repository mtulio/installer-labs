---
name: publish-safety-scan
description: Decide whether a directory is safe to commit or publish, without ingesting any secret it might contain. Use before committing anything under installer/upi/external/, before attaching an example to a PR, or whenever asked "can we publish this?". Scans by marker count, shape and decoded-in-tmpdir, never by reading values.
argument-hint: <directory> — e.g. installer/upi/external
allowed-tools: Bash Grep Glob
version: 1 (2026-10-01; first use cleared installer/upi/external, 35 files)
---

# Publish safety scan

**The problem this solves.** You cannot answer "is there a secret in here?" by reading
the files, because reading one *is* the leak — it enters the transcript and may be
cached by a model provider, and it cannot be unread. Every step below answers a question
whose **answer cannot itself be the secret**.

**Run it from the tree's root.** A `cd` inside an earlier command in the same block
silently moves the working directory; a scan that reports zero hits from the wrong
directory looks identical to a clean tree. **Print `pwd` in the same command as the
scan**, and if a result contradicts something you have already seen, re-run before
believing it.

---

## 1. Hard-fail markers — counts only, never the match

```sh
cd <root> && pwd && for pat in \
  'BEGIN [A-Z ]*PRIVATE KEY' \
  'ssh-(rsa|ed25519|dss) ' \
  '^pullSecret:[[:space:]]*[^"'"'"'[:space:]]' \
  '"auths"' \
  'AKIA[0-9A-Z]{16}' \
  '([0-9a-f]{2}:){15}[0-9a-f]{2}' \
; do printf '%-45s %s\n' "$pat" "$(grep -rlE "$pat" . 2>/dev/null | wc -l)"; done
```

`grep -rl` prints **filenames**, and `wc -l` reduces that to a number. No matched text
can reach the output. Any non-zero count is a file to investigate by *shape*, below —
not to open.

> A bare `grep -oE '^[a-z_]+'` on a credentials-shaped file is **not** safe: a base64 or
> PEM continuation line can begin with lowercase letters. Use an explicit whitelist of
> expected key names when you need to know what keys exist.

## 2. Investigate a hit by shape, never by value

Ask questions whose answers are numbers or booleans:

```sh
awk 'NR==<line>{print length($0)}' <file>          # how long is it?
grep -c '^pullSecret: ""' <file>                   # is it the empty placeholder?
grep -cE 'ssh-(rsa|ed25519|dss)' <file>            # must be 0
grep -cE 'BEGIN [A-Z ]*PRIVATE KEY' <file>         # must be 0
```

**Verify a redaction by the secret's shape, never by the placeholder's presence.** A
line-oriented `sed` over a **block scalar** replaces the `key: |` line and leaves the
payload on a dangling continuation line — the file still contains the key, is now
invalid YAML, and a check for the placeholder returns a clean `1`. An edit that lands
fully and an edit that lands halfway are indistinguishable from the placeholder's side.
**Both checks must run and both must agree.**

## 3. Base64 blobs — enumerate, never decode to stdout

Report `file:line`, the YAML **key** the blob sits under, and the blob's **length**:

```sh
grep -rnoE '[A-Za-z0-9+/]{60,}={0,2}' . | awk -F: '{print $1":"$2" len="length($3)}'
```

Interpretation notes from the first run: `len=65` runs were SHA-256 hashes in comment
headers, and `key=source` blobs were MachineConfig data-URLs. Neither is a secret, but
**neither is self-evidently not one** — so decode them.

**Decode to a scratch directory, never to stdout**, then re-run step 1 on the decoded
bytes and print only each payload's size and first line:

```sh
tmp=$(mktemp -d)
# ... write each decoded payload to $tmp/NNN ...
for f in "$tmp"/*; do printf '%s %s bytes | %s\n' "$f" "$(wc -c <"$f")" "$(head -c 40 "$f" | tr -d '\n')"; done
for pat in 'BEGIN [A-Z ]*PRIVATE KEY' 'ssh-(rsa|ed25519|dss) ' '"auths"'; do
  printf '%-35s %s\n' "$pat" "$(grep -rlE "$pat" "$tmp" | wc -l)"; done
rm -rf "$tmp"
```

A first line of `#!/bin/bash` and a plausible size is a pass. Anything you cannot
characterise in one line is a stop-and-ask.

## 4. Customer identifiers — not credentials, but not publishable either

```sh
cd <root> && pwd && for pat in \
  'ocid1\.[a-z]+\.oc[0-9]+' 'arn:aws:[a-z0-9-]*:' \
  '<your-base-domain>' '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' \
  '\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b' 'tenancy' \
; do printf '%-45s %s\n' "$pat" "$(grep -rlE "$pat" . 2>/dev/null | wc -l)"; done
```

Also sweep for the workspace's own fingerprints — cluster-name prefixes, the developer's
base domain, machine-local paths, pinned pre-release image tags. These are **not**
security findings; they are publication findings, and they belong in the example's
"before publication" checklist rather than blocking the commit.

## 5. Files that should not exist here at all

```sh
find . \( -name '*.pem' -o -name '*.key' -o -name '*kubeconfig*' -o -name '.env' \) -print
find . -type f ! -perm 644 ! -perm 755 -printf '%m %p\n'
```

An unexpected mode (600, 400) on a file in a publishable tree is a signal in itself.

## 6. The two things that look like samples and are not

- **A generated manifest tree is a credential store.** `create manifests` output holds
  the machine-config-server TLS private key, a CA private key, the pull secret, cloud
  credentials and the kubeadmin password hash — in a directory of plausibly-named YAML
  that is indistinguishable at a glance from hand-authored samples. **Never publish a
  captured tree. A sample is hand-written with placeholders.**
- **A serial-console capture** can contain the bootstrap pointer-ignition URL, which is
  unauthenticated read over every day-0 secret. Redact at the point of capture.

## 7. Report the result as evidence, not as a verdict

Say what was scanned (file count, which are modified vs untracked), enumerate each
check and its count, and name anything that was investigated and cleared and **why**.
"Clean" without the counts is not a result. If any step could not be completed, say so
and do not round it to a pass.
