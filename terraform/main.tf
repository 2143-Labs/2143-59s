# ── Multi-Cloud k3s Provisioning ────────────────────────────────────
# OpenTofu root module. One apply provisions/updates all clusters.
# Multi-cloud: DigitalOcean + Hetzner for geo-resilient k3s HA.

terraform {
  required_version = ">= 1.6"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.0"
    }
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2"
    }
  }

  backend "s3" {
    bucket                      = "2143tf"
    key                         = "2143-59s/terraform.tfstate"
    region                      = "nyc3"
    endpoint                    = "https://nyc3.digitaloceanspaces.com"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    use_path_style              = false
  }
}

# ── Providers ───────────────────────────────────────────────────────

variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
  default     = ""
}

variable "digitalocean_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "digitalocean" {
  token = var.digitalocean_token
}

# ── SSH Keys ────────────────────────────────────────────────────────

data "digitalocean_ssh_key" "k3s" {
  name = "k3s-cloud"
}

resource "hcloud_ssh_key" "k3s" {
  name       = "k3s-cloud"
  public_key = trimspace(file("~/.ssh/k3s-cloud.pub"))
}

# ── Cluster Definitions ─────────────────────────────────────────────

locals {
  clusters = {
    "do-nyc-k3s" = {
      cloud  = "digitalocean"
      region = "nyc1"
      size   = "s-2vcpu-4gb"
      image  = "ubuntu-24-04-x64"
      geo    = "us-nyc"
      tags   = ["k3s", "john2143", "managed-by-tofu", "k3s-server"]
    }
    "hetzner-ashburn-k3s" = {
      cloud  = "hetzner"
      region = "ashburn"
      size   = "cpx21"
      geo    = "us-ashburn"
      labels = {
        "k3s"        = "true"
        "name"       = "hetzner-ashburn-k3s"
        "owner"      = "john2143"
        "managed-by" = "tofu"
        "role"       = "k3s-server"
      }
    }
    "hetzner-hillsboro-k3s" = {
      cloud  = "hetzner"
      region = "hillsboro"
      size   = "cpx31"
      geo    = "us-hillsboro"
      labels = {
        "k3s"        = "true"
        "name"       = "hetzner-hillsboro-k3s"
        "owner"      = "john2143"
        "managed-by" = "tofu"
        "role"       = "k3s-server"
      }
    }
  }

  hetzner_location_map = {
    ashburn   = "ash"
    hillsboro = "hil"
  }

  do_clusters = {
    for name, c in local.clusters : name => c if c.cloud == "digitalocean"
  }
  hetzner_clusters = {
    for name, c in local.clusters : name => c if c.cloud == "hetzner"
  }
}

# ── DigitalOcean Clusters ───────────────────────────────────────────

resource "digitalocean_droplet" "k3s" {
  for_each = local.do_clusters

  name      = each.key
  region    = each.value.region
  size      = each.value.size
  image     = each.value.image
  tags      = each.value.tags
  ssh_keys  = [data.digitalocean_ssh_key.k3s.id]
  user_data = templatefile("${path.module}/cloud-init.yaml", {})
  backups   = false
}

resource "digitalocean_reserved_ip" "k3s" {
  for_each = local.do_clusters
  region   = each.value.region
}

resource "digitalocean_reserved_ip_assignment" "k3s" {
  for_each   = local.do_clusters
  ip_address = digitalocean_reserved_ip.k3s[each.key].ip_address
  droplet_id = digitalocean_droplet.k3s[each.key].id
}

# ── Hetzner Clusters ────────────────────────────────────────────────

module "cluster" {
  for_each = local.hetzner_clusters
  source   = "./modules/cluster"

  name        = each.key
  server_type = each.value.size
  location    = local.hetzner_location_map[each.value.region]
  image       = "ubuntu-24.04"
  labels      = each.value.labels
  ssh_key_id  = hcloud_ssh_key.k3s.id
  user_data   = templatefile("${path.module}/cloud-init-hetzner.yaml", {})
}
