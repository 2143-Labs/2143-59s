# ── DigitalOcean Outputs ────────────────────────────────────────────

output "do_nyc_k3s_server_ip" {
  description = "DO NYC droplet primary IPv4"
  value       = digitalocean_droplet.k3s["do-nyc-k3s"].ipv4_address
}

output "do_nyc_k3s_fip" {
  description = "DO NYC reserved IP"
  value       = digitalocean_reserved_ip.k3s["do-nyc-k3s"].ip_address
}

# ── Hetzner Outputs ─────────────────────────────────────────────────

output "hetzner_ashburn_k3s_server_ip" {
  description = "Hetzner Ashburn server IPv4"
  value       = module.cluster["hetzner-ashburn-k3s"].server_ipv4
}

output "hetzner_ashburn_k3s_fip" {
  description = "Hetzner Ashburn floating IP"
  value       = module.cluster["hetzner-ashburn-k3s"].floating_ip
}

output "hetzner_hillsboro_k3s_server_ip" {
  description = "Hetzner Hillsboro server IPv4"
  value       = module.cluster["hetzner-hillsboro-k3s"].server_ipv4
}

output "hetzner_hillsboro_k3s_fip" {
  description = "Hetzner Hillsboro floating IP"
  value       = module.cluster["hetzner-hillsboro-k3s"].floating_ip
}

# ── Aggregate (for deploy_all.py) ──────────────────────────────────

output "cluster_count" {
  description = "Number of managed clusters"
  value       = length(local.clusters)
}

output "cluster_names" {
  description = "All cluster names"
  value       = keys(local.clusters)
}

output "fip_registry" {
  description = "IP registry for CoreDNS zone generator"
  value = {
    "do-nyc-k3s" = {
      ip    = digitalocean_reserved_ip.k3s["do-nyc-k3s"].ip_address
      cloud = "digitalocean"
      geo   = "us-nyc"
    }
    "hetzner-ashburn-k3s" = {
      ip    = module.cluster["hetzner-ashburn-k3s"].floating_ip
      cloud = "hetzner"
      geo   = "us-ashburn"
    }
    "hetzner-hillsboro-k3s" = {
      ip    = module.cluster["hetzner-hillsboro-k3s"].floating_ip
      cloud = "hetzner"
      geo   = "us-hillsboro"
    }
  }
}
