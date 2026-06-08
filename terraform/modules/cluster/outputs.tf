output "server_ipv4" {
  description = "Primary IPv4 address of the server"
  value       = hcloud_server.node.ipv4_address
}

output "floating_ip" {
  description = "Floating IP address"
  value       = hcloud_floating_ip.fip.ip_address
}

output "server_id" {
  description = "Hetzner server ID"
  value       = hcloud_server.node.id
}

output "floating_ip_id" {
  description = "Hetzner floating IP ID"
  value       = hcloud_floating_ip.fip.id
}
