output "scheduler_url" {
  value = upcloud_server.scheduler.network_interface[0].ip_address
}

output "worker_url" {
  value = [for server in upcloud_server.workers : server.network_interface[0].ip_address]
}

output "scheduler_internal" {
  value = upcloud_server.scheduler.network_interface[1].ip_address
}

output "worker_internal" {
  value = [for server in upcloud_server.workers : server.network_interface[1].ip_address]
}

output "client_url" {
  value = [for server in upcloud_server.client : server.network_interface[0].ip_address]
}

output "client_internal" {
  value = [for server in upcloud_server.client : server.network_interface[1].ip_address]
}

output "scheduler_extra_url" {
  value = [for server in upcloud_server.schedulers_extra : server.network_interface[0].ip_address]
}

output "scheduler_extra_internal" {
  value = [for server in upcloud_server.schedulers_extra : server.network_interface[1].ip_address]
}
