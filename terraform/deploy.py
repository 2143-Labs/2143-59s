"""NixOS deployment integration — two methods for two cloud profiles.

Hetzner (nixos-anywhere):
  SSH → kexec into NixOS installer → disko partition → nixos-install → reboot.
  Works reliably because Hetzner's KVM handles the kexec kernel transition.
  kexec avoids the slow cloud-image download and boots a tiny installer kernel.

DigitalOcean (nixos-infect):
  SSH → install bzip2 → curl nixos-infect bash script → in-place replace → reboot.
  DO's KVM does NOT handle kexec properly — the kexec'd kernel boots but the
  installed NixOS never comes back after reboot (5 attempts across 5 recreations).
  nixos-infect avoids kexec entirely: it runs on the live Ubuntu, downloads NixOS,
  installs it to disk, and does a normal hardware reboot. DO handles this fine.

  The two phases:
    1. nixos-infect installs minimal base NixOS (auto-generates config for DO)
    2. nixos-rebuild switch --flake applies our full flake config (k3s, tailscale, etc.)

  Gotcha: Ubuntu 24.04 doesn't ship bzcat. Need `apt-get install -y bzip2` first.
  Gotcha: The flake lives in nixos/cluster/ subdirectory — use ?dir=nixos/cluster in URL.

MaxStartups (both):
  DO's ConfigDrive cloud-init skips bootcmd, write_files, and merges its own
  vendor-data over user-data runcmd. Can't rely on cloud-init for SSH config.
  _fix_maxstartups applies the fix over SSH as deploy step 1.

  Hetzner's cloud-init IS compliant. But _fix_maxstartups runs unconditionally
  for both clouds (harmless on Hetzner).
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
    """Deploy NixOS to a cloud VM. Dispatches to nixos-anywhere or nixos-infect based on cloud."""
    if cloud == "digitalocean":
        return _deploy_nixos_infect(host_ip, hostname, cloud, region, ssh_private_key_path, timeout)
    return _deploy_nixos_anywhere(host_ip, hostname, cloud, region, ssh_private_key_path, timeout)


def _build_ssh_base_cmd(ssh_key_path: Optional[str] = None) -> list:
    """Build common SSH options with ControlMaster multiplexing."""
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "ControlMaster=auto",
        "-o", "ControlPath=/tmp/ssh-%r@%h:%p",
        "-o", "ControlPersist=300",
    ]
    if ssh_key_path:
        cmd.extend(["-i", ssh_key_path])
    return cmd


def _deploy_nixos_anywhere(
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
        hostname: NixOS configuration name.
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

def _deploy_nixos_infect(
    host_ip: str,
    hostname: str,
    cloud: str,
    region: str,
    ssh_private_key_path: Optional[str] = None,
    timeout: int = 900,
) -> str:
    """Deploy NixOS via nixos-infect (in-place install, no kexec).

    Phase 1: Run nixos-infect from curl to replace Ubuntu with base NixOS.
    Phase 2: After reboot, apply full flake config via nixos-rebuild.

    Args:
        host_ip: Public IP of the VM.
        hostname: NixOS configuration name.
        cloud: Cloud provider name (for logging).
        region: Region name (for logging).
        ssh_private_key_path: Path to private key for SSH.
        timeout: Max seconds for the full operation.

    Returns:
        Combined stdout from both phases.
    """
    info(f"[{cloud}/{region}] Deploying NixOS ({hostname}) to {host_ip} via nixos-infect...")

    # Phase 1: Wait for SSH, fix MaxStartups, run nixos-infect
    _wait_for_ssh(host_ip, ssh_private_key_path, max_wait=300)
    _fix_maxstartups(host_ip, ssh_private_key_path)

    # Ubuntu 24.04 doesn't ship bzcat, but nixos-infect needs it.
    info(f"[{cloud}/{region}] Installing bzip2 (prerequisite for nixos-infect)...")
    bzip_cmd = _build_ssh_base_cmd(ssh_private_key_path) + [
        f"root@{host_ip}",
        "apt-get update -qq && apt-get install -y -qq bzip2 && echo 'bzip2 OK'",
    ]
    subprocess.run(bzip_cmd, capture_output=True, text=True, timeout=60)

    info(f"[{cloud}/{region}] Running nixos-infect (Phase 1)...")
    infect_cmd = _build_ssh_base_cmd(ssh_private_key_path) + [
        f"root@{host_ip}",
        "nohup bash -c '"
        "curl -s https://raw.githubusercontent.com/elitak/nixos-infect/master/nixos-infect "
        "| PROVIDER=digitalocean NIX_ALLOW_UNFREE=1 NIX_CHANNEL=nixos-25.05 "
        "bash > /tmp/nixos-infect.log 2>&1' "
        "& echo PID=$! && wait $! && echo 'INFECT_DONE'"
    ]
    try:
        result = subprocess.run(infect_cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout
    except subprocess.TimeoutExpired as e:
        output = e.stdout or ""
        warn(f"[{cloud}/{region}] nixos-infect SSH timed out ({timeout}s), "
             "system may have rebooted — continuing...")

    info(f"[{cloud}/{region}] nixos-infect Phase 1 complete. Waiting for reboot...")

    # Wait for SSH to drop (reboot) and come back
    _wait_for_ssh(host_ip, ssh_private_key_path, max_wait=600)

    info(f"[{cloud}/{region}] System rebooted. Running Phase 2: nixos-rebuild...")

    # Phase 2: Apply full flake config via nixos-rebuild.
    # The cluster flake is in nixos/cluster/ subdirectory. The root flake has
    # different machines (arch, closet, nas, etc.) and no cloud machines.
    # Must use ?dir=nixos/cluster to point at the right flake.
    flake_ref = f"github:John2143/dotfiles?dir=nixos/cluster#{hostname}"
    rebuild_cmd = _build_ssh_base_cmd(ssh_private_key_path) + [
        f"root@{host_ip}",
        f"nixos-rebuild switch --flake '{flake_ref}' 2>&1",
    ]
    result = subprocess.run(
        rebuild_cmd,
        capture_output=True, text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"nixos-rebuild failed for {hostname} ({host_ip}):\n"
            f"stdout: {result.stdout[-2000:]}\n"
            f"stderr: {result.stderr[-2000:]}"
        )

    info(f"[{cloud}/{region}] nixos-infect Phase 2 complete.")
    return output + "\n--- Phase 2 ---\n" + result.stdout


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
