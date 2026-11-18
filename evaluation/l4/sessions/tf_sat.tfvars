zone         = "nl-ams1"
lb_plan      = "PREMIUM-4xCPU-16GB"
worker_plan  = "PREMIUM-2xCPU-4GB"
storage_size = 150
n_workers    = 5
n_clients    = 1
# saturation: small synthetic workers, a 16-vCPU client so that the client is not the limit (30 cores)
client_plan  = "PREMIUM-16xCPU-32GB"
