terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

resource "google_compute_firewall" "ssh" {
  name    = "allow-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["ssh"]
}

resource "google_compute_firewall" "lb" {
  name    = "allow-lb"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["9020", "80"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["scheduler"]
}

resource "google_compute_firewall" "worker" {
  name    = "allow-worker"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["80", "5000-${5000 + var.n_workers - 1}"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["worker"]
}

resource "google_compute_instance" "scheduler" {
  name         = "scheduler"
  machine_type = var.lb_instance_type
  tags         = ["ssh", "scheduler"]

  boot_disk {
    initialize_params {
      image = var.image
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }

  metadata = {
    ssh-keys = "${var.ssh_user}:${file(pathexpand(var.ssh_pub_key))}"
  }
}

resource "google_compute_instance" "workers" {
  count        = var.n_workers
  name         = "worker-${count.index + 1}"
  machine_type = var.worker_instance_type
  tags         = ["ssh", "worker"]

  boot_disk {
    initialize_params {
      image = var.image
      size  = 150
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }

  metadata = {
    ssh-keys = "${var.ssh_user}:${file(pathexpand(var.ssh_pub_key))}"
  }
}
