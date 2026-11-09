variable "zone" {
  description = "The UpCloud zone to deploy in"
  default     = "de-fra1"
}

variable "lb_plan" {
  description = "The plan to use for the scheduler server"
  default     = "PREMIUM-4xCPU-16GB"
}

variable "worker_plan" {
  description = "The plan to use for the worker servers"
  default     = "PREMIUM-4xCPU-16GB"
}

variable "storage_size" {
  description = "The OS storage size in GB, must match the plan"
  default     = 150
}

variable "template" {
  description = "The OS template to use for the servers"
  default     = "Ubuntu Server 22.04 LTS (Jammy Jellyfish)"
}

variable "private_network" {
  description = "The address range of the private network"
  default     = "10.0.1.0/24"
}

variable "n_workers" {
  description = "The number of worker servers to deploy"
  default     = 5
}

variable "n_extra_schedulers" {
  description = "Additional schedulers beyond the first, for the multi-scheduler experiment"
  default     = 0
}

variable "extra_lb_plan" {
  description = "The plan for the additional schedulers, if it differs from lb_plan"
  default     = null
}

variable "client_plan" {
  description = "The plan for the load-generator servers, if it differs from worker_plan"
  default     = null
}

variable "small_storage_size" {
  description = "The OS storage size in GB for servers on extra_lb_plan or client_plan"
  default     = 50
}

variable "n_clients" {
  description = "The number of dedicated load-generator servers to deploy"
  default     = 0
}

variable "ssh_user" {
  description = "The SSH username provisioned on the servers"
  default     = "ubuntu"
}

variable "ssh_pub_key" {
  description = "Path to the SSH public key"
  default     = "~/.ssh/id_rsa.pub"
}
