# 2143-59s — ArgoCD GitOps Infrastructure

Single source of truth for all cluster infrastructure deployed by ArgoCD across 3 independent k3s clusters (Ashburn, Hillsboro, Nuremberg).

**Domain**: `9s.pics`

## Architecture

Reference: [hosting-research.md](https://github.com/John2143/dotfiles) · [hosting-next-steps.md](https://github.com/John2143/dotfiles) · [new-k8s-infra.md](https://github.com/John2143/dotfiles)

- 3 independent k3s clusters (not stretched) — SQLite per cluster
- ArgoCD App-of-Apps with sync-wave ordering
- k8gb for geoip DNS failover (60s TTL)
- PowerDNS (host-level, NixOS) + ExternalDNS RFC2136
- Traefik ingress + CrowdSec + split-IP DDoS
- Istio service mesh (mTLS STRICT)
- SeaweedFS encrypted object storage (local SSD, 3-way replication)
- MongoDB self-hosted with encryption at rest
- CloudNativePG for PostgreSQL (streaming replicas)
- Temporal for durable execution
- Backups: Backblaze B2 + home RustFS (rclone crypt)

## Sync Wave Order

| Wave | Component |
|------|-----------|
| -2   | Namespaces |
| -1   | Secrets (RFC2136, rclone, MongoDB encryption) |
| 0    | cert-manager, Cilium |
| 1    | Traefik, Longhorn |
| 2    | ExternalDNS, k8gb |
| 3    | CrowdSec, Istio |
| 4    | SeaweedFS |
| 5    | MongoDB, CloudNativePG, Temporal |
| 6    | Apps |
| 7    | Monitoring |
| 8    | Backups |

## Secrets

All secrets are created by the NixOS host config (agenix decryption at boot) or manually via `kubectl create secret`. The manifest files in this repo reference them by name only. Placeholder files document the expected shape.

## What's NOT Here

- NixOS configurations → [dotfiles repo](https://github.com/John2143/dotfiles)
- ArgoCD installation → bootstrapped during NixOS provisioning
- PowerDNS/Galera config → NixOS host modules
- Bunny CDN → manual DNS change
- Backblaze B2 bucket → manual one-time creation
