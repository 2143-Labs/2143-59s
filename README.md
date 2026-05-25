# 2143-59s — ArgoCD GitOps Infrastructure

Single source of truth for all cluster infrastructure deployed by ArgoCD across 3 independent k3s clusters (Ashburn, Hillsboro, Nuremberg).

**Domain**: `9s.pics`

## Architecture

Reference: [hosting-research.md](https://github.com/John2143/dotfiles) · [hosting-next-steps.md](https://github.com/John2143/dotfiles) · [new-k8s-infra.md](https://github.com/John2143/dotfiles) · [Research: ArgoCD GitOps Best Practices](ai_research/research-the-best-way-to-design-an-argocd-repo-to-use-an-app-o/final_report.md)

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

## Repository Structure

```
argocd/
├── root-app.yaml              # Root Application (applied imperatively at bootstrap)
├── wave--2/namespaces.yaml    # Wave -2: Namespaces
├── wave-0/                    # Wave 0: cert-manager (operator via systemd bootstrap)
├── wave-1/                    # Wave 1: Traefik, Longhorn
├── wave-2/                    # Wave 2: ExternalDNS, k8gb
├── wave-3/                    # Wave 3: CrowdSec, Istio
├── wave-4/                    # Wave 4: SeaweedFS
├── wave-5/                    # Wave 5: MongoDB, CloudNativePG, Temporal
├── wave-6/                    # Wave 6: Applications
├── wave-7/                    # Wave 7: Monitoring
└── wave-8/                    # Wave 8: Backups
base/
├── namespaces.yaml
├── argocd-bootstrap/          # Bootstrap helpers (secret injection now via systemd)
├── k8gb/                      # Gslb CRDs
├── externaldns/               # RFC2136 secret + config
├── cert-manager/              # ClusterIssuers + certificates
├── traefik/                   # Dashboard + middlewares
├── crowdsec/                  # LAPI + agent + firewall bouncer
├── istio/                     # IstioOperator + mTLS + telemetry
├── cilium/                    # CNI config (ruled out — using k3s default Flannel)
├── longhorn/                  # Storage values
├── seaweedfs/                 # Object storage HelmRelease + buckets
├── mongodb/                   # Deployment + PVC + encryption + backup
├── cloudnativepg/             # PostgreSQL Cluster CR
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

Wave-grouped directories make deployment order visible from the filesystem.

| Wave | Directory | Component |
|------|-----------|-----------|
| -2   | `wave--2/` | Namespaces |
| 0    | `wave-0/`  | cert-manager (operator via bootstrap) |
| 1    | `wave-1/`  | Traefik, Longhorn |
| 2    | `wave-2/`  | ExternalDNS, k8gb |
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

## Future: ApplicationSet Migration

The current per-wave Application CRD approach is correct for the current scale (~28 components across 3 clusters). If cluster count or application count grows significantly, consider migrating to an [ApplicationSet matrix generator](https://argo-cd.readthedocs.io/en/stable/user-guide/application-set/) combining a Git directory generator with a cluster generator. This would eliminate per-cluster Application CRD duplication and auto-discover new clusters via label matching.

## What's NOT Here

- NixOS configurations → [dotfiles repo](https://github.com/John2143/dotfiles)
- ArgoCD installation → bootstrapped during NixOS provisioning
- PowerDNS/Galera config → NixOS host modules
- Bunny CDN → manual DNS change
- Backblaze B2 bucket → manual one-time creation
