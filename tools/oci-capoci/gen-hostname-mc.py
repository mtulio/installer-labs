import base64, textwrap

# MAINTAINER NOTE, not shipped to the node. SCRIPT below must not name the
# literal substitution placeholder (CLUSTER_ID) even inside a comment. An
# earlier revision wrote `CLUSTER-ID-master-0` as the displayName example and
# a run's placeholder assertion failed on it -- this manifest is not a
# substitution input, so the token was never going to be rewritten. The
# wording is `<infraID>-master-0` instead.
#
# That reword was once applied to the emitted file and not back here, so
# regenerating silently resurrected the token. Fix the generator, never the
# output: the output is overwritten by the next run.

SCRIPT = """#!/bin/bash
# Set this node's hostname from the OCI instance metadata service.
#
# WHY THIS EXISTS. RHCOS boots here with ignition.platform.id=openstack,
# because that is the only artifact whose Ignition provider reads OCI's
# metadata channel (see ../../docs/boot-image.md). Afterburn therefore asks the
# OpenStack metadata API for a hostname. OCI does not serve that API, so the
# answer is nothing and the hostname stays at its default.
#
# MEASURED: without this unit every machine registers as
# "localhost.localdomain", so three masters contend for ONE Node object and the
# cluster cannot form. Oracle ships an equivalent oci-hostname-update.service;
# this is a hardened rewrite of it -- theirs is WantedBy=multi-user.target with
# no ordering against the kubelet, writes /etc/hostname without applying it to
# the running system, and shells out to jq.
set -e -o pipefail

IMDS=http://169.254.169.254/opc/v2/instance

current=$(hostnamectl --static 2>/dev/null || true)
case ${current} in
"" | localhost | localhost.localdomain) ;;
*)
	echo "hostname already set to ${current}; leaving it alone"
	exit 0
	;;
esac

# Two fields, in order of preference. `hostname` is what OCI's own DHCP would
# hand out and is already DNS-safe; `displayName` is the fallback and is what
# Oracle's version uses. Asking for a single field rather than the whole
# document keeps jq out of the dependency list -- it is not guaranteed present
# in the initramfs-adjacent environment this runs in.
# `hostname` is absent unless the VNIC carries a hostnameLabel, and CAPOCI does
# not set one -- curl -f then exits non-zero on the 404 and the loop falls
# through to displayName, which CAPOCI sets to the Machine name
# (e.g. <infraID>-master-0). Both are tried every round so that a late-arriving
# hostname still wins.
name=""
for _ in $(seq 1 30); do
	for field in hostname displayName; do
		raw=$(curl -fsSL --max-time 10 \\
			-H "Authorization: Bearer Oracle" "${IMDS}/${field}" || true)
		# Defensive: IMDS returns a bare string for a single field, but strip
		# surrounding quotes and whitespace in case it ever returns JSON, and
		# lowercase it because a Node name must be lowercase.
		name=$(printf '%s' "${raw}" | tr -d '"[:space:]' | tr '[:upper:]' '[:lower:]')
		case ${name} in
		"" | localhost | localhost.localdomain) name="" ;;
		*[!a-z0-9.-]*)
			echo "ignoring ${field}: not a valid hostname" >&2
			name=""
			;;
		*) break 2 ;;
		esac
	done
	sleep 5
done

if [ -z "${name}" ]; then
	echo "could not read a usable hostname from ${IMDS} after 30 attempts" >&2
	exit 1
fi

# hostnamectl rather than `echo > /etc/hostname`: it sets the running hostname
# as well as the persistent one. Writing the file alone leaves the kernel
# hostname at localhost until the next reboot, which is exactly when the
# kubelet reads it.
hostnamectl set-hostname "${name}"
echo "hostname set to ${name}"
"""

UNIT = """[Unit]
Description=Set the node hostname from the OCI instance metadata service
# Ordering is the whole point. The kubelet takes its node name from the
# hostname at start and never revisits it, so this must win the race that
# Oracle's version loses. node-valid-hostname.service is RHCOS's own guard
# against a localhost node name; ordering before it means we satisfy that
# guard rather than waiting out its timeout.
After=NetworkManager-wait-online.service
Before=node-valid-hostname.service
Before=kubelet.service
[Service]
ExecStart=/usr/local/bin/oci-set-hostname
Type=oneshot
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console
[Install]
WantedBy=multi-user.target
"""

HEADER = """# yamllint disable rule:line-length
#
# The long line is the Ignition data URL carrying the base64 of the script
# reproduced in full below. Ignition requires file contents as a single data
# URL, so it cannot be wrapped; the plaintext under it is what a reviewer
# should read instead.
#
# Set every node's hostname from the OCI instance metadata service.
#
# The other half of what `platform: external` needs before a node can go Ready.
# 99_external-00-kubelet-providerid-{role}.yaml gives the node a provider ID;
# this gives it a NAME. Both run before the kubelet, and the cluster fails in a
# different way without each.
#
# An earlier revision of this example deliberately left this out, on the
# grounds that the providerID manifest should cover "one concern". A run proved
# that wrong: all three masters registered as "localhost.localdomain" and
# fought over a single Node object. The omission is recorded rather than
# quietly reversed -- see ../../docs/capi-requirements.md.
#
# The script below is base64 in the manifest because Ignition stores file
# contents as a data URL. It is reproduced in plain text here so it can be
# reviewed without decoding:
#
{plaintext}
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  labels:
    machineconfiguration.openshift.io/role: {role}
  name: 00-{role}-oci-hostname
spec:
  config:
    ignition:
      version: 3.4.0
    storage:
      files:
      - path: /usr/local/bin/oci-set-hostname
        mode: 493
        overwrite: true
        contents:
          source: data:text/plain;charset=utf-8;base64,{b64}
    systemd:
      units:
      - name: oci-set-hostname.service
        enabled: true
        contents: |
{unit}
"""

b64 = base64.b64encode(SCRIPT.encode()).decode()
plaintext = "\n".join(("#   " + l).rstrip() for l in SCRIPT.split("\n"))
unit = "\n".join(("          " + l).rstrip() for l in UNIT.rstrip().split("\n"))

for role in ("master", "worker"):
    out = HEADER.format(role=role, b64=b64, plaintext=plaintext, unit=unit)
    path = "99_external-01-oci-hostname-%s.yaml" % role
    open(path, "w").write(out)
    print("wrote", path, len(out), "bytes")
