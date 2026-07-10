#!/usr/bin/env python3
"""Self-contained preflight validation of deploy/ against ai-guild-infra's
documented app-repo contract (ops/app-repo.md pre-flight checklist). This does
NOT replace the authoritative `cue vet` + `ib validate` that ai-guild-infra
runs at reconcile-time (which needs the private schema); it catches the common
mistakes at PR time without any cross-repo/private dependency."""
import glob
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("::error::PyYAML not available"); sys.exit(2)

DEPLOY = "deploy"
errors = []


def err(m):
    errors.append(m)


mpath = os.path.join(DEPLOY, "ironbridge.yaml")
if not os.path.isfile(mpath):
    print(f"::error::{mpath} missing"); sys.exit(1)

with open(mpath) as f:
    m = yaml.safe_load(f) or {}

name = m.get("name")
if not isinstance(name, str) or not re.match(r"^[a-z][a-z0-9_-]{0,62}$", name or ""):
    err(f"name '{name}' missing or not kebab/snake lowercase")

hostname = m.get("hostname", "")
if not isinstance(hostname, str) or not hostname.endswith(".ironbridge.tech"):
    err(f"hostname '{hostname}' must be under .ironbridge.tech")

up = m.get("upstream", {}) or {}
if not isinstance(up.get("port"), int) or not (1 <= up["port"] <= 65535):
    err("upstream.port must be an int 1-65535")
hc = up.get("health_check")
if hc is not None and not str(hc).startswith("/"):
    err("upstream.health_check must be a path starting with /")

auth = m.get("auth", {}) or {}
mode = auth.get("mode")
if mode not in ("app", "access", "internal"):
    err(f"auth.mode '{mode}' must be app|access|internal")
if mode == "access" and not auth.get("rules"):
    err("auth.mode: access requires a non-empty rules list")

expose = (m.get("expose") or {}).get("via")
if expose is not None and expose not in ("public", "internal", "none"):
    err(f"expose.via '{expose}' must be public|internal|none")

# Quadlets
containers = sorted(glob.glob(os.path.join(DEPLOY, "*.container")))
basenames = [os.path.splitext(os.path.basename(c))[0] for c in containers]
if name and name not in basenames:
    err(f"no {name}.container matching manifest name (found: {basenames})")

for c in containers:
    b = os.path.splitext(os.path.basename(c))[0]
    if name and b != name and not b.startswith(name + "-"):
        err(f"stray quadlet {b}.container outside '{name}' namespace")

main = os.path.join(DEPLOY, f"{name}.container")
if name and os.path.isfile(main):
    text = open(main).read()

    cn = re.search(r"^ContainerName=(.+)$", text, re.M)
    if not cn or cn.group(1).strip() != name:
        err(f"{name}.container: ContainerName= must be present and equal '{name}'")

    img = re.search(r"^Image=(.+)$", text, re.M)
    if not img:
        err(f"{name}.container: Image= required")
    else:
        iv = img.group(1).strip()
        if iv.startswith("ghcr.io/") and not iv.startswith("ghcr.io/ironbridge-ai/"):
            err(f"{name}.container: ghcr image must be under ghcr.io/ironbridge-ai/ (got {iv})")

    if re.search(r"^\s*PublishPort=", text, re.M):
        err(f"{name}.container: PublishPort= is not allowed")

    for directive in ("CPUQuota", "MemoryMax"):
        if not re.search(rf"^{directive}=", text, re.M):
            err(f"{name}.container: {directive}= is mandatory in [Service]")

    for mnt in re.findall(r"^Volume=(.+)$", text, re.M):
        mm = re.match(r"%h/storage/([a-z0-9-]+)", mnt.strip())
        if mm and not (mm.group(1) == name or mm.group(1).startswith(name + "-")):
            err(f"{name}.container: Volume mounts another app's storage ({mm.group(1)})")

if errors:
    print("preflight FAILED:")
    for e in errors:
        print(f"  - {e}")
        print(f"::error::{e}")
    sys.exit(1)

print(f"preflight OK — {mpath} + {len(containers)} quadlet(s) pass the ai-guild-infra pre-flight checklist")
print("(authoritative cue vet + ib validate run at reconcile-time in ai-guild-infra)")
