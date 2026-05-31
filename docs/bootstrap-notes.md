# Bootstrap Notes

## deSEC API Rate Limits

deSEC uses a 300-second rolling window where every request counts — GET, PUT, POST, DELETE all reset the timer. After any request, wait at least 5 minutes before the next one. A single GET to check state is enough to restart the clock, so batch operations carefully. Best practice: wait 320 seconds, make ONE write request, then stop.

## DNS Cleanup Between Bootstrap Rounds

Before reprovisioning, check for and delete stale deSEC A records that would shadow the `*.9s.pics` wildcard: `john2143.9s.pics` and `openfront.9s.pics`. Explicit A records take precedence over wildcards, so any leftover from a previous round will break the new setup. After creating the wildcard, wait at least one TTL (3600s) at public resolvers before cert-manager challenges will succeed.

## Tailscale MagicDNS Caching

k3s nodes resolve through Tailscale MagicDNS (`100.100.100.100`), which caches aggressively and ignores short TTLs. After updating deSEC records, pods may resolve stale IPs for 30+ minutes. If stuck, a working workaround: temporarily replace `/etc/resolv.conf` on the node with Google DNS (`8.8.8.8`, `8.8.4.4`), restart the cert-manager controller pod, then restore Tailscale DNS.

## FIP Labels

The `floating-ip-health` systemd service discovers floating IPs by their `region` label. Without it, the health checker can't find the FIP and won't attach it to local interfaces. Labels are set during provisioning (`hcloud floating-ip add-label <FIP_ID> region=<region>`), but if they're missing, fix them manually: `hcloud floating-ip add-label <FIP_ID> region=<ashburn|hillsboro|nuremberg>`.
