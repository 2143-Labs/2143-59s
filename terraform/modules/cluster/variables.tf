variable "name" {
  description = "Hostname for the server and resource naming prefix"
  type        = string
}

variable "server_type" {
  description = "Hetzner server type (e.g. cpx21, cpx31)"
  type        = string
}

variable "location" {
  description = "Hetzner location (ash, hil, fsn1, nbg1, hel1)"
  type        = string
}

variable "image" {
  description = "OS image name"
  type        = string
  default     = "ubuntu-24.04"
}

variable "labels" {
  description = "Labels to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "ssh_key_id" {
  description = "Hetzner SSH key ID (from imported hcloud_ssh_key)"
  type        = number
}

variable "user_data" {
  description = "Cloud-init user data for the server"
  type        = string
  default     = ""
}
