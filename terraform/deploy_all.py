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
        [str(TOFU_DIR / "tofu-wrap"), "output", "-json"],
        capture_output=True, text=True,
        cwd=TOFU_DIR,
    )
    if result.returncode != 0:
        log("ERROR", f"Failed to read tofu outputs: {result.stderr.strip()}")
        sys.exit(1)
    return json.loads(result.stdout)


def deploy_one(cluster_name: str, server_ip: str, fip: str,
               cloud: str, region: str, geo_tag: str, ssh_key_path: str) -> dict:

    """Deploy and configure one cluster. Returns result dict."""
    log("INFO", f"[{cloud}/{region}] Deploying {cluster_name} ({server_ip})...")
    result = {
        "name": cluster_name, "ip": server_ip, "fip": fip,
        "cloud": cloud, "region": region, "geo": geo_tag,
    }

    try:
        deploy_result = deploy_nixos(
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
        result["timing"] = {
            "deploy": deploy_result.get("timing", {}),
            "post_deploy": post_result.get("timing", {}),
        }
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
                "geo": r.get("geo", r["region"]),
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

# ── Metrics table ────────────────────────────────────────────────────

def fmt_sec(s: float) -> str:
    """Format seconds as XXXs or XXm."""
    if s >= 120:
        return f"{s/60:.0f}m"
    return f"{s:.0f}s"


METRIC_ROWS = [
    ("ssh_ready", "SSH ready"),
    ("maxstartups_done", "MaxStartups fix"),
    ("bzip2_done", "Install bzip2"),
    ("phase1_done", "NixOS install"),
    ("phase1_install", "nixos-anywhere"),
    ("reboot_done", "Reboot wait"),
    ("phase2_done", "nixos-rebuild"),
    ("nixos_booted", "Post: wait boot"),
    ("k3s_restarted", "Post: k3s restart"),
    ("tailscale_done", "Post: Tailscale"),
    ("verify_done", "Post: verify"),
]


def print_metrics_table(results: list):
    """Print a timing metrics summary table."""
    successful = [r for r in results if r.get("success") and r.get("timing")]
    if not successful:
        log("INFO", "(no timing data to display)")
        return

    # Column headers
    names = [r["name"] for r in successful]
    col_w = max(len(n) for n in names + ["Stage"])
    hdr = f"{'Stage':<{col_w}} | " + " | ".join(f"{n:<{col_w}}" for n in names)
    sep = "-" * len(hdr)

    log("INFO", f"\n{'=' * 60}")
    log("INFO", "Deployment Timing Metrics")
    log("INFO", f"{'=' * 60}")
    log("INFO", hdr)
    log("INFO", sep)

    for key, label in METRIC_ROWS:
        cells = []
        for r in successful:
            t = r["timing"]
            val = (t.get("deploy", {}).get(key) or
                   t.get("post_deploy", {}).get(key))
            if val is not None:
                cells.append(f"{fmt_sec(val):<{col_w}}")
            else:
                cells.append(f"{'—':<{col_w}}")
        log("INFO", f"{label:<{col_w}} | " + " | ".join(cells))

    log("INFO", sep)
    total_cells = []
    for r in successful:
        t = r["timing"]
        total = (t.get("deploy", {}).get("total", 0) +
                 t.get("post_deploy", {}).get("verify_done", 0))
        total_cells.append(f"{fmt_sec(total):<{col_w}}")
    log("INFO", f"{'TOTAL':<{col_w}} | " + " | ".join(total_cells))
    log("INFO", f"{'=' * 60}")

# ── Pre-checks ──────────────────────────────────────────────────────

FLAKE_PATH = os.path.expanduser("~/repos/dotfiles/nixos/cluster")

def precheck_nixos_configs(cluster_names: list) -> bool:
    """Verify all NixOS configurations evaluate without errors."""
    log("INFO", "Pre-check: evaluating NixOS configurations...")
    for name in cluster_names:
        flake_ref = f"{FLAKE_PATH}#nixosConfigurations.{name}.config.networking.hostName"
        result = subprocess.run(
            ["nix", "eval", flake_ref],
            capture_output=True, text=True,
            timeout=120,
        )
        if result.returncode != 0:
            log("ERROR", f"NixOS config '{name}' FAILED to evaluate:\n{result.stderr.strip()[-500:]}")
            return False
        log("INFO", f"  {name}: OK")
    return True


def precheck_ssh_connectivity(tasks: list, ssh_key_path: str) -> bool:
    """Verify SSH access to all nodes before starting nixos-anywhere."""
    log("INFO", "Pre-check: testing SSH connectivity...")
    for t in tasks:
        cluster_name, server_ip = t[0], t[1]
        cmd = [
            "ssh", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
        ]
        if ssh_key_path:
            cmd.extend(["-i", ssh_key_path])
        cmd.extend([f"root@{server_ip}", "echo ok"])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if "ok" not in result.stdout:
            log("ERROR", f"SSH check FAILED for {cluster_name} ({server_ip})")
            return False
        log("INFO", f"  {cluster_name} ({server_ip}): OK")
    return True


# ── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Deploy NixOS to all OpenTofu-provisioned clusters")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers (default: 1)")

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
            cluster_spec.geo_tag,
            ssh_key_path
        ))

    if not tasks:
        log("ERROR", "No clusters to deploy")
        sys.exit(1)

    if args.workers > 1:
        log("WARN", f"Workers={args.workers} — MaxStartups exhaustion risk. Only set >1 if you've increased sshd MaxStartups on all nodes.")

    # Pre-checks
    log("INFO", "Running pre-checks...")
    if not precheck_nixos_configs(cluster_names):
        log("ERROR", "Pre-check failed: NixOS config evaluation. Fix configs and re-run.")
        sys.exit(1)

    if not precheck_ssh_connectivity(tasks, ssh_key_path):
        log("ERROR", "Pre-check failed: SSH connectivity. Verify nodes are up.")
        sys.exit(1)

    log("INFO", "All pre-checks passed.\n")
    log("INFO", f"Deploying {len(tasks)} clusters (workers={args.workers})...\n")
    # Run deploys in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(deploy_one, *t): t[0] for t in tasks}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # Print timing metrics table
    print_metrics_table(results)

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
