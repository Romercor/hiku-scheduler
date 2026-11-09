# Hiku: OpenLambda Scheduler, with an In-Kernel L4 Mode

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

This repository is a fork of [Hiku](https://github.com/saman-akbari/hiku-scheduler), the pull-based HTTP request
scheduler for serverless functions in [OpenLambda](https://github.com/open-lambda/open-lambda). It keeps Hiku's
scheduler (`hiku start`) and adds a second mode, `hiku l4`, which performs the same pull-based scheduling inside the
Linux kernel with eBPF, so that no user-space process handles a request.

The fork was developed for the bachelor thesis *eBPF-Accelerated Pull-Based Scheduling for Serverless Functions*
(Timofei Babin, Technische Universität Berlin), which holds the results of the evaluation.

## Features

- **Two modes:** Hiku's reverse proxy at L7 and an eBPF scheduler at L4, in one binary.
- **Pull-based in the kernel:** workers announce their free slots per function over UDP; an XDP program stores them,
  and a TC program selects a worker at the first packet of each connection.
- **Ready to Use:** scripts for automated deployment and evaluation on UpCloud, AWS and local environments.

## Paper

S. Akbari and M. Hauswirth, ‘Hiku: Pull-Based Scheduling for Serverless Computing’, in 2025 IEEE 25th International
Symposium on Cluster, Cloud and Internet Computing (CCGrid), 2025, pp. 450–461.

[![DOI](https://zenodo.org/badge/doi/10.1109/CCGRID64434.2025.00034.svg)](https://dx.doi.org/10.1109/CCGRID64434.2025.00034)
[![arXiv](https://img.shields.io/badge/arXiv-2502.15534-B31B1B.svg)](https://arxiv.org/abs/2502.15534)

### Citation

```bibtex
@inproceedings{akbari2025hiku,
  title={Hiku: Pull-Based Scheduling for Serverless Computing},
  author={Akbari, Saman and Hauswirth, Manfred},
  booktitle={2025 IEEE 25th International Symposium on Cluster, Cloud and Internet Computing (CCGrid)},
  pages={450--461},
  year={2025},
  organization={IEEE}
}
```

## Prerequisites

- **Go** 1.25+
- For the L4 mode: **Linux 6.6+** on the scheduler, root, and **clang** (installed by `scripts/setup_l4.sh`)

Optional: **Docker** for OpenLambda workers, **Terraform** for cloud deployment, **k6** for load testing,
**Python** for evaluation.

```bash
git clone https://github.com/Romercor/hiku-scheduler
```

## Usage

### L7 Scheduler

Used exactly as in [Hiku](https://github.com/saman-akbari/hiku-scheduler):

```bash
hiku start -c config.json
```

### L4 Scheduler

On the scheduler node, from the repository root:

```bash
bash scripts/setup_l4.sh
sudo /app/hiku l4 -c /app/l4.json
```

The main fields of `src/l4/config.json` are `iface`, `workers` (`ip:port`, at most 15), `function_addrs`
(`name:IPv4` per function), and `strategy` and `fallback`; the file lists all fields. Clients route the function
addresses to the scheduler and open one connection per call. Workers run OpenLambda with the changes in
[open-lambda-mod](open-lambda-mod) and send their announcements to `scheduler_url`.

## Evaluation and Benchmarking

The scripts are in `scripts/`, the benchmarks from [FunctionBench](https://github.com/ddps-lab/serverless-faas-workbench)
in `evaluation/`, and the experiments of the L4 scheduler in `evaluation/l4/`.

### Scripts Overview

The scripts are those of Hiku. They deploy to UpCloud (`terraform-upcloud/`) by default; `TF_DIR=terraform` selects
Hiku's AWS configuration.

```bash
./scripts/1_deploy.sh <n_workers>
./scripts/2_setup.sh -m <mode> <n_workers> <n_copies>
./scripts/3_clean.sh -m <mode>
./scripts/run_experiments.sh -m <mode> -n <n_iterations> <n_workers> <n_copies>
```

### Load Testing

```bash
k6 run  -e N_COPIES=<n_copies>
        -e SEED=<seed>
        -e SCHEDULER_DNS=<scheduler_url>
        --out json=<result_path>
        evaluation/load_test.js
```

`MODE=l4addr` addresses the L4 scheduler, `NOKA=1` opens one connection per call, and `RATE` gives an open loop; the
comments in `load_test.js` list all options.

### Experiments with the L4 Scheduler

`evaluation/l4/harness/` runs the experiments of the thesis on a cluster in `terraform-upcloud/`. Each experiment is an
arms file in `harness/arms/`, run by `matrix.sh` (OpenLambda workers), `multi.sh` (several schedulers) or `pool.sh`
(synthetic workers); `paired.py` computes the paired differences. The comment at the top of each script gives its
usage.

### Supported Load Balancing Strategies

- **L7:** `pull-based`, `hashing-bounded`, `random` and `least-connections` from Hiku, and `pull-ordered` (Hiku's
  queue with the ordered selection of the L4 scheduler).
- **L4 strategies:** `ordered` (default), `p2c`, `jsq`, `weighted-random`.
- **L4 fallbacks:** `least-loaded` (default), `random`, `hashed`, `hashed2`, `bounded`.

### Changes to OpenLambda and Hiku

In addition to Hiku's changes to OpenLambda, the workers announce their free slots per function
(`open-lambda-mod/src/worker/lambda/signal.go`); the `openlambda` binary in the repository root includes this. Hiku's
proxy logs less and keeps more idle connections, so that it is not limited by its own implementation; its load
balancing algorithms are unchanged.

## Limitations of the L4 Mode

- IPv4 only, and one TCP connection per call, so a gateway in front of the scheduler is assumed.
- At most 15 workers, fixed when the kernel program is built, and fixed tables of workers and functions.

## License

This project is licensed under the [Apache License 2.0](LICENSE). The kernel program `src/l4/bpf/scheduler.bpf.c` is
licensed GPL-2.0.

## Acknowledgments

This project builds on [Hiku](https://github.com/saman-akbari/hiku-scheduler), which extends
[olscheduler](https://github.com/disel-espol/olscheduler) for [OpenLambda](https://github.com/open-lambda/open-lambda)
and integrates benchmarks from [FunctionBench](https://github.com/ddps-lab/serverless-faas-workbench), all licensed
under the Apache License 2.0. The L4 loader uses [cilium/ebpf](https://github.com/cilium/ebpf). The workloads use the
[Azure Functions 2021](https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsInvocationTrace2021.md),
[Huawei 2025](https://github.com/sir-lab/data-release) and
[IBM Cloud Code Engine](https://github.com/ubc-cirrus-lab/ibm-cloud-code-engine-traces) traces.
