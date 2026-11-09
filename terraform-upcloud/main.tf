terraform {
  required_providers {
    upcloud = {
      source  = "UpCloudLtd/upcloud"
      version = "~> 5.0"
    }
  }
}

provider "upcloud" {}

resource "upcloud_network" "hiku" {
  name = "hiku"
  zone = var.zone

  ip_network {
    address = var.private_network
    dhcp    = true
    family  = "IPv4"
  }
}

resource "upcloud_server" "scheduler" {
  hostname = "scheduler"
  zone     = var.zone
  plan     = var.lb_plan
  firewall = false
  metadata = true

  template {
    size    = var.storage_size
    storage = var.template
  }

  network_interface {
    type = "public"
  }

  network_interface {
    type    = "private"
    network = upcloud_network.hiku.id

    # the scheduler answers on behalf of addresses it does not own, which the SDN otherwise drops
    # as spoofing. Same opt-in any L4 load balancer needs: AWS source/dest check, GCP IP forwarding.
    source_ip_filtering = false
  }

  login {
    user            = var.ssh_user
    keys            = [file(pathexpand(var.ssh_pub_key))]
    create_password = false
  }
}

resource "upcloud_server" "schedulers_extra" {
  count    = var.n_extra_schedulers
  hostname = "scheduler-${count.index + 2}"
  zone     = var.zone
  plan     = coalesce(var.extra_lb_plan, var.lb_plan)
  firewall = false
  metadata = true

  template {
    size    = var.extra_lb_plan == null ? var.storage_size : var.small_storage_size
    storage = var.template
  }

  network_interface {
    type = "public"
  }

  network_interface {
    type    = "private"
    network = upcloud_network.hiku.id

    # same opt-out as the primary scheduler: these steer the same pool and answer on behalf of the
    # same addresses, so without it every reply they send is dropped as spoofing
    source_ip_filtering = false
  }

  login {
    user            = var.ssh_user
    keys            = [file(pathexpand(var.ssh_pub_key))]
    create_password = false
  }
}

resource "upcloud_server" "client" {
  count    = var.n_clients
  hostname = "client"
  zone     = var.zone
  plan     = coalesce(var.client_plan, var.worker_plan)
  firewall = false
  metadata = true

  template {
    size    = var.client_plan == null ? var.storage_size : var.small_storage_size
    storage = var.template
  }

  network_interface {
    type = "public"
  }

  network_interface {
    type    = "private"
    network = upcloud_network.hiku.id
  }

  login {
    user            = var.ssh_user
    keys            = [file(pathexpand(var.ssh_pub_key))]
    create_password = false
  }
}

resource "upcloud_server" "workers" {
  count    = var.n_workers
  hostname = "worker-${count.index + 1}"
  zone     = var.zone
  plan     = var.worker_plan
  firewall = false
  metadata = true

  template {
    size    = var.storage_size
    storage = var.template
  }

  network_interface {
    type = "public"
  }

  network_interface {
    type    = "private"
    network = upcloud_network.hiku.id
  }

  login {
    user            = var.ssh_user
    keys            = [file(pathexpand(var.ssh_pub_key))]
    create_password = false
  }
}
