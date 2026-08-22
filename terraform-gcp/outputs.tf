output "scheduler_url" {
  value = google_compute_instance.scheduler.network_interface[0].access_config[0].nat_ip
}

output "worker_url" {
  value = [for instance in google_compute_instance.workers : instance.network_interface[0].access_config[0].nat_ip]
}

output "scheduler_internal" {
  value = google_compute_instance.scheduler.network_interface[0].network_ip
}

output "worker_internal" {
  value = [for instance in google_compute_instance.workers : instance.network_interface[0].network_ip]
}
