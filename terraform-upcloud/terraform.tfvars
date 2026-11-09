zone         = "de-fra1"
lb_plan      = "PREMIUM-4xCPU-16GB"
worker_plan  = "PREMIUM-4xCPU-16GB"
storage_size = 150
n_workers    = 5
n_clients    = 1

# four schedulers inside the 32-core account limit: the three extra ones and the client are small
n_extra_schedulers = 3
extra_lb_plan      = "PREMIUM-2xCPU-4GB"
client_plan        = "PREMIUM-2xCPU-4GB"
