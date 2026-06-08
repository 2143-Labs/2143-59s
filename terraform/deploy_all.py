#!/usr/bin/env python3
"""Phase 2: Deploy NixOS to all provisioned clusters in parallel.

Usage: deploy_all.py [--workers N]

Read OpenTofu stack outputs for server IPs, then runs nixos-anywhere +
post-deploy in parallel for all clusters. Run after `tofu apply`.
"""

import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import yaml
from spec import Spec
from deploy import deploy_nixos
from post_deploy import post_deploy
from resources.common import get_cloud_ssh_key_path


# ── Helpers ──────────────────────────────────────────────────────────

TOFU_DIR = Path(__file__).parent

def log(level: str, msg: str):
    """Log a message."""
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] [{level}] {msg}", flush=True)


def tofu_output_key(cluster_name: str) -> str:
    """Convert a cluster name (e.g. 'hetzner-ashburn-k3s') to the tofu
    output key prefix (e.g. 'hetzner_ashburn_k3s')."""
    return cluster_name.replace("-", "_")


def get_stack_outputs() -> dict:
    """Read OpenTofu stack outputs via CLI."""
    result = subprocess.run(
        ["tofu", "output", "-json"],
        capture_output=True, text=True,
        cwd=TOFU_DIR,
    )
    if result.returncode != 0:
        log("ERROR", f"Failed to read tofu outputs: {result.stderr.strip()}")
        sys.exit(1)
    return json.loads(result.stdout)


def deploy_one(cluster_name: str, server_ip: str, fip: str,
               cloud: str, region: str, ssh_key_path: str) -> dict:
    """Deploy and configure one cluster. Returns result dict."""
    log("INFO", f"[{cloud}/{region}] Deploying {cluster_name} ({server_ip})...")
    result = {
        "name": cluster_name, "ip": server_ip, "fip": fip,
        "cloud": cloud, "region": region,
    }

    try:
        deploy_nixos(
            host_ip=server_ip, hostname=cluster_name,
            cloud=cloud, region=region,
            ssh_private_key_path=ssh_key_path,
        )
        log("INFO", f"[{cloud}/{region}] nixos-anywhere done, starting post-deploy...")

        post_result = post_deploy(
            host_ip=server_ip, hostname=cluster_name,
            cloud=cloud, region=region,
        )
        result["success"] = True
        result["k3s_version"] = post_result.get("k3s_version", "?")
        result["tailscale_ip"] = post_result.get("tailscale_ip", "?")
        log("INFO", f"[{cloud}/{region}] Complete — k3s {result['k3s_version']}, TS {result['tailscale_ip']}")

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        log("ERROR", f"[{cloud}/{region}] Failed: {e}")

    return result


# ── FIP ConfigMap writer ─────────────────────────────────────────────

def render_fip_configmap(fip_registry: dict, zones: dict) -> str:
    """Render the CoreDNS zone-generator ConfigMap YAML."""
    import json as _json
    yaml_lines = [
        "apiVersion: v1",
        "kind: ConfigMap",
        "metadata:",
        "  name: fip-registry",
        "  namespace: k8gb",
        "data:",
        "  fip_registry.json: |",
    ]
    for line in _json.dumps(fip_registry, indent=2).split("\n"):
        yaml_lines.append(f"    {line}")
    yaml_lines.append("  zones.json: |")
    for line in _json.dumps(zones, indent=2).split("\n"):
        yaml_lines.append(f"    {line}")
    return "\n".join(yaml_lines)


def kubectl_apply(host_ip: str, yaml_content: str):
    """Apply a YAML manifest to the cluster via SSH + kubectl."""
    cmd = (
        f"cat << 'EOF' | kubectl apply -f - 2>/dev/null\n"
        f"{yaml_content}\n"
        f"EOF"
    )
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10",
        f"root@{host_ip}", cmd,
    ]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"kubectl apply failed: {result.stderr.strip()}")


def write_fip_configmaps(results: list, outputs: dict):
    """Write FIP registry ConfigMaps to all provisioned clusters."""
    fip_registry = {}
    for r in results:
        if r.get("success"):
            fip_registry[r["region"]] = {
                "ip": r["fip"],
                "cloud": r["cloud"],
                "geo": r["region"].replace("nyc", "us-nyc").replace("ashburn", "us-ashburn").replace("hillsboro", "us-hillsboro"),
            }

    if not fip_registry:
        log("WARN", "No successful clusters — skipping FIP ConfigMap")
        return

    regions = list(fip_registry.keys())
    zones = {
        "openfront": {"regions": regions},
        "simulation-api": {"regions": regions},
        "john2143": {"regions": regions},
    }

    cm_yaml = render_fip_configmap(fip_registry, zones)

    for r in results:
        if not r.get("success"):
            continue
        host = r["ip"]
        if host:
            log("INFO", f"[{r['cloud']}/{r['region']}] Writing FIP ConfigMap...")
            try:
                kubectl_apply(host, cm_yaml)
                log("INFO", f"[{r['cloud']}/{r['region']}] FIP ConfigMap applied.")
            except Exception as e:
                log("WARN", f"[{r['cloud']}/{r['region']}] FIP ConfigMap failed: {e}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Deploy NixOS to all OpenTofu-provisioned clusters")
    parser.add_argument("--workers", type=int, default=3, help="Parallel workers (default: 3)")
    args = parser.parse_args()

    log("INFO", "=" * 60)
    log("INFO", "Phase 2: Deploying NixOS to all clusters (parallel)")
    log("INFO", "=" * 60)

    # Read tofu stack outputs (server IPs, FIPs)
    outputs = get_stack_outputs()
    cluster_names = outputs.get("cluster_names", {}).get("value", [])
    log("INFO", f"Found {len(cluster_names)} clusters in tofu state")

    # Read spec for cluster metadata
    spec_path = TOFU_DIR / "clusters.yaml"
    with open(spec_path) as f:
        spec = Spec(**yaml.safe_load(f))

    # Map spec clusters by name for quick lookup
    spec_by_name = {c.name: c for c in spec.clusters}

    ssh_key_path = get_cloud_ssh_key_path()

    # Build task list
    tasks = []
    for cluster_name in cluster_names:
        key = tofu_output_key(cluster_name)
        server_ip = outputs.get(f"{key}_server_ip", {}).get("value")
        fip = outputs.get(f"{key}_fip", {}).get("value", "")

        if not server_ip:
            log("WARN", f"No server IP for {cluster_name} in tofu outputs — skipping")
            continue

        cluster_spec = spec_by_name.get(cluster_name)
        if not cluster_spec:
            log("WARN", f"No spec for {cluster_name} — skipping")
            continue

        tasks.append((
            cluster_name, server_ip, fip,
            cluster_spec.cloud.value, cluster_spec.region,
            ssh_key_path
        ))

    if not tasks:
        log("ERROR", "No clusters to deploy")
        sys.exit(1)

    log("INFO", f"Deploying {len(tasks)} clusters (workers={args.workers})...\n")

    # Run deploys in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(deploy_one, *t): t[0] for t in tasks}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # Write FIP ConfigMaps to all successfully provisioned clusters
    write_fip_configmaps(results, outputs)

    # Print summary
    log("INFO", "=" * 60)
    successes = [r for r in results if r.get("success")]
    failures = [r for r in results if not r.get("success")]
    log("INFO", f"Results: {len(successes)} succeeded, {len(failures)} failed")
    for r in successes:
        log("INFO", f"  OK  {r['name']} ({r['cloud']}/{r['region']}): {r['ip']}")
    for r in failures:
        log("ERROR", f"  FAIL {r['name']} ({r['cloud']}/{r['region']}): {r.get('error', '?')}")
    log("INFO", "=" * 60)

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
