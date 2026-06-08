# Multi-Cloud k3s Provisioning (OpenTofu)

Provision k3s clusters across Hetzner, DigitalOcean, and future clouds via
OpenTofu. Each cluster gets a VM + floating/reserved IP, then NixOS + k3s
is installed via nixos-anywhere.

## Quick Start

```bash
# Decrypt cloud API tokens
export TF_VAR_hcloud_token=$(agenix -d ~/repos/dotfiles/nixos/cluster/secrets/hetzner/hcloud-token.age -i ~/.ssh/age)
export TF_VAR_digitalocean_token=$(agenix -d ~/repos/dotfiles/nixos/cluster/secrets/do-pat.age -i ~/.ssh/age)

# Check for changes
tofu plan

# Apply infrastructure changes
tofu apply

# Deploy NixOS + k3s to all nodes (after VM creation)
python3 deploy_all.py --workers 2
```

## Structure

```
tofu/
├── main.tf                  # Providers, locals (cluster definitions), module calls
├── imports.tf               # Import blocks (inert after first apply)
├── outputs.tf               # Server IPs, FIPs (consumed by deploy_all.py)
├── deploy_all.py            # Parallel nixos-anywhere + post-deploy
├── clusters.yaml            # Cluster metadata (shared with deploy script)
├── modules/
│   └── cluster/             # Reusable Hetzner cluster module
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
└── resources/
    └── common.py            # SSH key helpers, kubectl wrapper
```

## Adding a New Cluster

1. Add a cluster definition in `main.tf` under `locals.clusters`
2. If Hetzner, add to `hetzner_location_map` if new region
3. Add outputs in `outputs.tf`
4. Run `tofu apply` to provision
5. Run `python3 deploy_all.py` to install NixOS + k3s

Example:
```hcl
"hetzner-nuremberg-k3s" = {
  cloud  = "hetzner"
  region = "nuremberg"
  size   = "cpx31"
  geo    = "eu-nuremberg"
  labels = {
    k3s         = "true"
    name        = "hetzner-nuremberg-k3s"
    owner       = "john2143"
    managed-by  = "tofu"
    role        = "k3s-server"
  }
}
```

Then in `hetzner_location_map`:
```hcl
nuremberg = "nbg1"
```

## Future Clouds

- **DigitalOcean**: Add `digitalocean_droplet` + `digitalocean_reserved_ip` + `digitalocean_reserved_ip_assignment` resources to the cluster module (or separate module)
- **AWS**: Use `aws_instance` + `aws_eip` + `aws_eip_association`
- **GCP**: Use `google_compute_instance` + `google_compute_address`
- **Azure**: Use `azurerm_linux_virtual_machine` + `azurerm_public_ip`

All follow the same pattern: VM + static IP + IP assignment.
