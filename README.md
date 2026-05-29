# 2143-59s — ArgoCD GitOps Infrastructure

Single source of truth for all cluster infrastructure deployed by ArgoCD across 3 independent k3s clusters (Ashburn, Hillsboro, Nuremberg).

**Domain**: `9s.pics`

## Architecture

Reference: [hosting-research.md](https://github.com/John2143/dotfiles) · [hosting-next-steps.md](https://github.com/John2143/dotfiles) · [new-k8s-infra.md](https://github.com/John2143/dotfiles) · [Research: ArgoCD GitOps Best Practices](ai_research/research-the-best-way-to-design-an-argocd-repo-to-use-an-app-o/final_report.md)

- 3 independent k3s clusters (not stretched) — SQLite per cluster
- ArgoCD App-of-Apps with sync-wave ordering
- **deSEC.io** for all DNS (NS delegation + A records + cert-manager DNS01 via webhook)
- Floating IPs for per-region node-level failover (auto-reassign on health check failure)
- Traefik ingress + CrowdSec + split-IP DDoS
- Istio service mesh (mTLS STRICT)
- SeaweedFS encrypted object storage (local SSD, 3-way replication)
- MongoDB self-hosted with encryption at rest
- CloudNativePG for PostgreSQL (used by Temporal)
- Temporal for durable execution
- Backups: Backblaze B2 + home RustFS (rclone crypt)

## Repository Structure

```
argocd/
├── root-app.yaml              # Root Application (applied imperatively at bootstrap)
├── wave--2/namespaces.yaml    # Wave -2: Namespaces
├── wave-0/                    # Wave 0: cert-manager, deSEC webhook, ClusterIssuers
├── wave-1/                    # Wave 1: Traefik, Longhorn
├── wave-2/                    # Wave 2: (removed — no more ExternalDNS/k8gb)
├── wave-3/                    # Wave 3: CrowdSec, Istio
├── wave-4/                    # Wave 4: SeaweedFS
├── wave-5/                    # Wave 5: MongoDB, CloudNativePG, Temporal
├── wave-6/                    # Wave 6: Applications
├── wave-7/                    # Wave 7: Monitoring
└── wave-8/                    # Wave 8: Backups
base/
├── namespaces.yaml
├── cert-manager/              # ClusterIssuers + certificates + deSEC webhook
├── traefik/                   # Dashboard + middlewares
├── crowdsec/                  # LAPI + agent + firewall bouncer
├── istio/                     # IstioOperator + mTLS + telemetry
├── longhorn/                  # Storage values
├── seaweedfs/                 # Object storage HelmRelease + buckets
├── mongodb/                   # Deployment + PVC + encryption + backup
├── cloudnativepg/             # PostgreSQL Cluster CR (Temporal only)
├── temporal/                  # Server + worker values
├── monitoring/                # Prometheus + Grafana + Healthchecks
├── backups/                   # rclone config + backup CronJob
└── apps/                      # 8 application services
clusters/
├── base-values.yaml           # Shared Helm defaults across all clusters
├── ashburn/                   # US East region-specific overrides
├── hillsboro/                 # US West region-specific overrides
└── nuremberg/                 # EU region-specific overrides
```

## Sync Wave Order

| Wave | Directory | Component |
|------|-----------|-----------|
| -2   | `wave--2/` | Namespaces |
| 0    | `wave-0/`  | cert-manager, deSEC webhook, ClusterIssuers |
| 1    | `wave-1/`  | Traefik, Longhorn |
| 3    | `wave-3/`  | CrowdSec, Istio |
| 4    | `wave-4/`  | SeaweedFS |
| 5    | `wave-5/`  | MongoDB, CloudNativePG, Temporal |
| 6    | `wave-6/`  | Apps |
| 7    | `wave-7/`  | Monitoring |
| 8    | `wave-8/`  | Backups |

## Secrets

All secrets are created by the NixOS host config (`k8s-secrets-bootstrap` systemd oneshot, agenix decryption at boot). The manifests in this repo reference secrets by name only.

**No placeholder secrets in GitOps**: Empty secrets (even with `IgnoreExtraneous` annotation and no `data:` field) are an anti-pattern — ArgoCD selfHeal WILL reconcile them and overwrite runtime-injected values. The annotation prevents drift detection, not selfHeal overwrite. All secrets injected by `k8s-secrets-bootstrap` MUST NOT exist in this repo at all.

No secret material (encrypted or otherwise) ever enters git history. This repo is safe to make public.

## DNS Architecture

All DNS is handled by **deSEC.io**. No self-hosted PowerDNS or k8gb.

- **NS delegation**: `9s.pics` NS records at deSEC delegate to `ns1/ns2/ns3.9s.pics` with glue A records pointing to per-region floating IPs
- **Service records**: Static A records (`john2143.9s.pics`, `openfront.9s.pics`, etc.) point to floating IPs — set once during provisioning, never need updating
- **cert-manager DNS01**: deSEC webhook creates ACME challenge TXT records
- **headscale.9s.pics**: Updated via deSEC DDNS timer on home-pi (dynamic public IP)

Node-level failover is handled entirely by **floating IP reassignment** (2-5s via Hetzner API), not DNS TTL changes.

## What's NOT Here

- NixOS configurations → [dotfiles repo](https://github.com/John2143/dotfiles)
- ArgoCD installation → bootstrapped during NixOS provisioning
- DNS management (PowerDNS/k8gb removed) → deSEC.io
- Bunny CDN → manual DNS change
- Backblaze B2 bucket → manual one-time creation
