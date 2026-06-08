terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.0"
    }
  }
}
# ── Hetzner k3s Cluster Resource ───────────────────────────────────
# One server + one floating IPv4 + assignment binding.
# Shared SSH key is injected from the root module (single import).

resource "hcloud_server" "node" {
  name        = var.name
  server_type = var.server_type
  location    = var.location
  image       = var.image
  ssh_keys    = [var.ssh_key_id]
  user_data   = var.user_data
  labels      = var.labels

  lifecycle {
    ignore_changes = [
      ssh_keys,   # don't drift when root module manages keys
    ]
  }
}

resource "hcloud_floating_ip" "fip" {
  name          = "${var.name}-fip"
  type          = "ipv4"
  home_location = var.location
  labels        = merge(var.labels, { component = "floating-ip" })

  lifecycle {
    ignore_changes = [
      # labels might diverge from originals — only track core attrs
    ]
  }
}

resource "hcloud_floating_ip_assignment" "fip_assign" {
  floating_ip_id = hcloud_floating_ip.fip.id
  server_id      = hcloud_server.node.id
}
