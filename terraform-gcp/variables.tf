variable "project_id" {
  description = "The GCP project to deploy in"
}

variable "region" {
  description = "The GCP region to deploy in"
  default     = "europe-west3"
}

variable "zone" {
  description = "The GCP zone to deploy in"
  default     = "europe-west3-a"
}

variable "lb_instance_type" {
  description = "The machine type to use for the scheduler instance"
  default     = "e2-standard-4"
}

variable "worker_instance_type" {
  description = "The machine type to use for the worker instances"
  default     = "e2-standard-4"
}

variable "image" {
  description = "The boot image to use for the instances"
  default     = "ubuntu-os-cloud/ubuntu-2204-lts"
}

variable "n_workers" {
  description = "The number of worker instances to deploy"
  default     = 5
}

variable "ssh_user" {
  description = "The SSH username provisioned on the instances"
  default     = "ubuntu"
}

variable "ssh_pub_key" {
  description = "Path to the SSH public key"
  default     = "~/.ssh/id_rsa.pub"
}
