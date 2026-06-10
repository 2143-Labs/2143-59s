"""nixos-anywhere deployment integration.

After OpenTofu creates cloud resources (VM + floating IP), this module
runs nixos-anywhere to install NixOS + k3s on the new node.
"""

import subprocess
import os
import time

from typing import Optional
from log import info, warn


FLAKE_PATH = os.path.expanduser("~/repos/dotfiles/nixos/cluster")


def deploy_nixos(
    host_ip: str,
    hostname: str,
    cloud: str,
    region: str,
    ssh_private_key_path: Optional[str] = None,
    timeout: int = 600,
) -> str:
    """Run nixos-anywhere to deploy NixOS to a cloud VM.

    Args:
        host_ip: Public IP of the VM (primary, not floating).
        hostname: NixOS configuration name (e.g., "hetzner-ashburn-k3s").
        cloud: Cloud provider name (for logging).
        region: Region name (for logging).
        ssh_private_key_path: Path to private key for SSH. If None, uses default.
        timeout: Max seconds to wait for deployment.

    Returns:
        stdout from nixos-anywhere.
    """
    info(f"[{cloud}/{region}] Deploying NixOS ({hostname}) to {host_ip} via nixos-anywhere...")

    # Wait for SSH to become available
    info(f"[{cloud}/{region}] Waiting for SSH on {host_ip}...")
    _wait_for_ssh(host_ip, ssh_private_key_path, max_wait=300)
    _fix_maxstartups(host_ip, ssh_private_key_path)


    # Build the flake reference
    flake_ref = f"{FLAKE_PATH}#{hostname}"

    # Run nixos-anywhere
    cmd = ["nixos-anywhere", "--flake", flake_ref]
    cmd.extend(["--ssh-option", "ControlMaster=auto"])
    cmd.extend(["--ssh-option", "ControlPath=/tmp/ssh-%r@%h:%p"])
    cmd.extend(["--ssh-option", "ControlPersist=300"])
    if ssh_private_key_path:
        cmd.extend(["-i", ssh_private_key_path])
    cmd.append(f"root@{host_ip}")


    info(f"[{cloud}/{region}] Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=FLAKE_PATH,
        env={**os.environ, "NIX_SSHOPTS": "-o StrictHostKeyChecking=accept-new"},
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"nixos-anywhere failed for {hostname} ({host_ip}):\n"
            f"stdout: {result.stdout[-2000:]}\n"
            f"stderr: {result.stderr[-2000:]}"
        )

    info(f"[{cloud}/{region}] nixos-anywhere completed successfully.")
    return result.stdout


def _wait_for_ssh(
    host_ip: str,
    ssh_key_path: Optional[str] = None,
    max_wait: int = 60,

) -> None:
    """Poll SSH until it accepts connections."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        cmd = [
            "ssh", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
            "-o", "ControlMaster=auto",
            "-o", "ControlPath=/tmp/ssh-%r@%h:%p",
            "-o", "ControlPersist=300",
        ]
        if ssh_key_path:
            cmd.extend(["-i", ssh_key_path])
        cmd.extend([f"root@{host_ip}", "echo ok"])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if "ok" in result.stdout:
            return
        time.sleep(20)

    raise TimeoutError(f"SSH to {host_ip} did not become available within {max_wait}s")


def _fix_maxstartups(host_ip: str, ssh_key_path: Optional[str] = None) -> None:
    """Apply MaxStartups fix via SSH (cloud-init on DO skips bootcmd/write_files)."""
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "ControlMaster=auto",
        "-o", "ControlPath=/tmp/ssh-%r@%h:%p",
        "-o", "ControlPersist=300",
    ]
    if ssh_key_path:
        cmd.extend(["-i", ssh_key_path])
    cmd.extend(["root@{}".format(host_ip), (
        "mkdir -p /etc/ssh/sshd_config.d && "
        "cat > /etc/ssh/sshd_config.d/99-maxstartups.conf << 'EOF'\n"
        "MaxStartups 100:100:200\n"
        "MaxSessions 100\n"
        "EOF\n"
        "systemctl reload sshd 2>/dev/null || true\n"
        "grep -c 'MaxStartups 100:100:200' /etc/ssh/sshd_config.d/99-maxstartups.conf || echo 'FIX FAILED'"
    )])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if "FIX FAILED" in result.stdout:
        raise RuntimeError(f"Failed to apply MaxStartups fix on {host_ip}: {result.stdout.strip()} {result.stderr.strip()}")
