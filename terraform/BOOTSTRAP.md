# Multi-Cloud k3s — Bootstrap Guide

Three-cloud k3s HA: DigitalOcean NYC + Hetzner Ashburn + Hetzner Hillsboro.
Provisioning by OpenTofu, OS by NixOS, apps by ArgoCD.

## Repo Layout

| Repo | Role | Path |
|------|------|------|
| `2143-59s/terraform/` | Cloud infra (OpenTofu) | `~/repos/2143-59s/terraform/` |
| `dotfiles/nixos/cluster/` | NixOS config + agenix secrets | `~/repos/dotfiles/nixos/cluster/` |
| `2143-59s/argocd/` | ArgoCD GitOps (k8s apps) | `~/repos/2143-59s/argocd/` |
| `2143-59s/clusters/` | Per-cluster values | `~/repos/2143-59s/clusters/` |

## State

Terraform state lives in DO Spaces — survives machine rebuilds.

```
Bucket:   2143tf (nyc3.digitaloceanspaces.com)
Key:      2143-59s/terraform.tfstate
Access:   agenix s3-credentials.age → AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
```

## Secrets

```
dotfiles/nixos/cluster/secrets/
  s3-credentials.age       — DO Spaces keys (for tofu state)
  do-pat.age               — DO API token
  hetzner/hcloud-token.age — Hetzner Cloud API token
  cloud-ssh-key.age        — k3s-cloud SSH private key (also on DO account, id 56925510)
```

All decrypted at runtime by agenix. Never touch disk in plaintext.

## Deployment Methods

Two methods exist because DigitalOcean and Hetzner handle kernel replacement differently.

### Hetzner: nixos-anywhere (works)
SSH → kexec into NixOS installer → disko partition → nixos-install → reboot.
Hetzner's KVM handles the kexec kernel transition reliably.

### DigitalOcean: nixos-infect (required — kexec fails on DO)
SSH → fix MaxStartups → install bzip2 → curl nixos-infect → in-place install → reboot.

DO's KVM does NOT handle kexec properly. After nixos-anywhere's kexec+disko+install,
the droplet never comes back after reboot (confirmed across 5 attempts, 4 different
disk/GRUB/networking configs). nixos-infect avoids kexec entirely: it runs on the
live Ubuntu, downloads NixOS, installs it to disk, and does a normal hardware reboot.

Two phases:
  1. nixos-infect installs minimal base NixOS (auto-generates config for DO)
  2. nixos-rebuild switch --flake applies our full flake config (k3s, tailscale, etc.)

Gotchas:
  - Ubuntu 24.04 doesn't ship bzcat. Install bzip2 first (handled in deploy.py).
  - The cluster flake is in nixos/cluster/ subdirectory — use ?dir=nixos/cluster in URL.
  - nixos-rebuild requires the full attribute path with ?dir= parameter.

### MaxStartups (both clouds)
DO's ConfigDrive cloud-init skips bootcmd, write_files, and merges its own
vendor-data over user-data runcmd. Can't rely on cloud-init for SSH config.
_fix_maxstartups() applies the fix over SSH as deploy step 1.

Hetzner's cloud-init IS compliant. The fix runs unconditionally (harmless on Hetzner).

## Quick Start

```bash
# 1. Provision cloud resources
cd ~/repos/2143-59s/terraform
./tofu-wrap plan      # preview
./tofu-wrap apply     # create droplets/servers (10 resources)

# 2. Deploy NixOS + k3s to all nodes
#    DO uses nixos-infect, Hetzner uses nixos-anywhere (auto-dispatched by deploy.py)
python3 deploy_all.py --workers 1

# Or manually per-node:
# Hetzner:
nixos-anywhere --flake ~/repos/dotfiles/nixos/cluster#hetzner-ashburn-k3s \
  -i <decrypted-ssh-key> root@<server-ip>
# DO:
python3 -c "
from deploy import deploy_nixos
deploy_nixos(host_ip='<ip>', hostname='do-nyc-k3s', cloud='digitalocean', region='nyc1')
"

# 3. Post-deploy (age key, agenix, tailscale, k3s verify)
#    Managed by post_deploy.py after deploy_nixos returns.
```

## Cluster Inventory

| Name | Cloud | Region | Size | Geo Tag |
|------|-------|--------|------|---------|
| do-nyc-k3s | DigitalOcean | nyc1 | s-2vcpu-4gb | us-nyc |
| hetzner-ashburn-k3s | Hetzner | ashburn | cpx21 | us-ashburn |
| hetzner-hillsboro-k3s | Hetzner | hillsboro | cpx31 | us-hillsboro |

NixOS flake hosts (in `dotfiles/nixos/cluster/flake.nix`):
- `do-nyc-k3s` / `do-nyc-k3s-agent`
- `hetzner-ashburn-k3s` / `hetzner-ashburn-k3s-agent`
- `hetzner-hillsboro-k3s` / `hetzner-hillsboro-k3s-agent`

## SSH

Key: `k3s-cloud` (age-encrypted at `cloud-ssh-key.age`)

```bash
# Decrypt for manual use
cd ~/repos/dotfiles/nixos/cluster/secrets
agenix -d cloud-ssh-key.age -i ~/.ssh/age > /tmp/k3s-cloud.pem
chmod 600 /tmp/k3s-cloud.pem
ssh -i /tmp/k3s-cloud.pem root@<fip>
```

## NixOS Notes

- DO nodes: `extraModules = [ ./modules/digitalocean.nix ]` (pure DHCP — no cloud-init module)
- DO disk device: `/dev/vda` (Hetzner: `/dev/sda`)
- DO nodes: `useEFI = false` (BIOS-only GRUB)
- The cluster flake is at `dotfiles/nixos/cluster/flake.nix`, NOT the root `dotfiles/flake.nix`
- All filesystem layout via `modules/disko.nix`
- kexec/kernel modules via `qemu-guest.nix` import in disko module

## Teardown

```bash
cd ~/repos/2143-59s/terraform
./tofu-wrap destroy   # removes all cloud resources
```
