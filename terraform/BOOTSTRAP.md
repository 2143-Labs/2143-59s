# Multi-Cloud k3s — Bootstrap Guide

Three-cloud k3s HA: DigitalOcean NYC + Hetzner Ashburn + Hetzner Hillsboro.
Provisioning by OpenTofu, OS by NixOS (nixos-anywhere), apps by ArgoCD.

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
  s3-credentials.age      — DO Spaces keys (for tofu state)
  do-pat.age              — DO API token
  hetzner/hcloud-token.age — Hetzner Cloud API token
  cloud-ssh-key.age       — k3s-cloud SSH private key (also on DO account, id 56925510)
```

All decrypted at runtime by agenix. Never touch disk in plaintext.

## Quick Start

## Known Issues

### DO: nixos-anywhere installs but system never boots
DO droplets go dark permanently after nixos-anywhere runs. GRUB installs
successfully (BIOS mode) but the system never responds on the network
after reboot. This affects ALL attempts regardless of:
- disk layout (GPT/BIOS vs GPT+UEFI)
- network config (cloud-init vs pure DHCP)
- GRUB device setting (auto vs explicit)

Hypothesis: DO's KVM hypervisor has an incompatibility with the kexec
approach used by nixos-anywhere (boot kernel replacement). Possible fixes:
1. Try nixos-infect instead of nixos-anywhere
2. Use DO's rescue mode + manual NixOS install
3. Avoid DO entirely for nixos-anywhere nodes

### Hetzner: tailscale preauth key may time out
`tailscale up` has a 30s timeout. If headscale server is slow to respond
or unreachable, the preauth key round-trip can fail. SSH in and reconnect
manually if needed.

```bash
# 1. Provision cloud resources
cd ~/repos/2143-59s/terraform
./tofu-wrap plan      # preview
./tofu-wrap apply     # create droplets/servers (7 resources)

# 2. Deploy NixOS + k3s to all nodes
#    Each node: ~10-15 min
source .venv/bin/activate
python3 deploy_all.py --workers 1

# Or manually per-node:
nixos-anywhere --flake ~/repos/dotfiles/nixos/cluster#<hostname> \
  -i <decrypted-ssh-key> root@<server-ip>

# 3. Post-deploy (age key, agenix, tailscale, k3s verify)
#    Managed by post_deploy.py, or manual steps in the deploy script.
```

## Cluster Inventory

| Name | Cloud | Region | Size | Geo Tag |
|------|-------|--------|------|---------|
| do-nyc-k3s | DigitalOcean | nyc1 | s-2vcpu-4gb | us-nyc |
| hetzner-ashburn-k3s | Hetzner | ashburn | cpx21 | us-ashburn |
| hetzner-hillsboro-k3s | Hetzner | hillsboro | cpx31 | us-hillsboro |

NixOS flake hosts:
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

Key fingerprint: `MD5:b8:85:11:e3:73:92:5a:44:1c:62:4b:85:9a:30:2a:28`

## NixOS Notes

- DO nodes need `extraModules = [ ./modules/digitalocean.nix ]` for cloud-init datasource
- DO disk device is `/dev/vda` (not `/dev/sda`)
- Cloud-init bootcmd sets `MaxStartups 100:100:200` on all nodes — without it, nixos-anywhere's concurrent SSH exhausts the default Ubuntu limit

## Teardown

```bash
cd ~/repos/2143-59s/terraform
./tofu-wrap destroy   # removes all cloud resources
```
