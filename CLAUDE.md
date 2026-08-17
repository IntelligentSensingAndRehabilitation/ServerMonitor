# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ServerMonitor is a Docker Compose-based server monitoring stack using Prometheus, Node Exporter, DCGM
Exporter, and Grafana. It provides a dynamic dashboard for CPU, memory, network, disk I/O, GPU, and
physical-drive storage metrics, with storage-growth projections and Slack alerting.

## Architecture

The system has two layers: **runtime** (Docker containers) and **code generation** (Python script that
produces Prometheus recording rules and Grafana config).

### Runtime Stack (docker-compose.yaml)
- **Node Exporter** - host system metrics. Runs with `network_mode: host` (see Important Details) and
  binds `NODE_EXPORTER_HOST_PORT`
- **DCGM Exporter** - NVIDIA GPU metrics on port 9400; simply absent on non-GPU servers
- **Prometheus** - collects metrics, evaluates recording rules, stores in TSDB with 90-day retention
  and a 20GB size cap on a named volume (`prometheus_data`)
- **Grafana** - visualizes metrics, provisions dashboards/alerts/datasources from `config/` files;
  state persists in the `grafana_data` volume

Prometheus, DCGM Exporter and Grafana share the `monitoring` bridge network. Node Exporter is on the
host network instead, so Prometheus reaches it via `host.docker.internal` (see `extra_hosts`).

### Alert Generation Pipeline
`generate_alerts.py` reads `config/alerts_config.json` and produces three auto-generated files:
- `config/recording_rules.yml` - Prometheus recording rules: the monitored drive set and projections
- `config/alert_rules.yml` - Grafana unified alerting rules, one group per alert type
- `config/notification_policies.yml` - notification routing/timing per alert type

It validates the config first and raises rather than writing anything inconsistent.

Alert types have separate Slack contact points in `config/alerting.yml`: `system` (memory, watchdog),
`storage`, `storage_projection`, and `gpu`.

### Key Config Files
| File | Purpose | Auto-generated? |
|------|---------|-----------------|
| `config/alerts_config.json` | Thresholds, intervals, drive definition (source of truth) | No |
| `config/recording_rules.yml` | Prometheus recording rules | Yes |
| `config/alert_rules.yml` | Grafana alert rules | Yes |
| `config/notification_policies.yml` | Notification routing | Yes |
| `config/alerting.yml` | Slack contact points | No |
| `config/prometheus.yml` | Prometheus scrape targets and rule_files | No |
| `config/dcgm-counters.csv` | Which DCGM fields the GPU exporter collects | No |
| `config/datasources.yml` | Grafana datasource config | No |
| `config/dashboard.yml` | Grafana dashboard provider | No |
| `config/dashboard_dynamic.json` | The actual Grafana dashboard | No |

## Common Commands

```bash
# Regenerate rules after editing alerts_config.json
python3 generate_alerts.py

# Start/restart the stack
docker compose up -d
docker compose restart grafana      # after regenerating alert rules
docker compose restart prometheus   # after regenerating recording rules

# Reload Prometheus rules without dropping the in-memory head block
docker exec prometheus-c wget -qO- --post-data='' http://localhost:9090/-/reload

# Tests (no pytest on the compute hosts, so run them in a container)
docker run --rm -v "$PWD":/w:ro -w /w python:3.12-slim \
  sh -c 'pip install -q pytest pyyaml && python -m pytest tests/ -q'

# Validate generated rules before deploying
docker run --rm -v "$PWD/config":/etc/prometheus:ro --entrypoint promtool \
  prom/prometheus:v3.8.0 check config /etc/prometheus/prometheus.yml
```

## Environment

Configured via `.env` file (gitignored). All variables are required; the stack fails to start rather
than defaulting silently. `NODE_EXPORTER_CONTAINER`, `NODE_EXPORTER_PORT`, `NODE_EXPORTER_HOST_PORT`,
`PROMETHEUS_CONTAINER`, `PROMETHEUS_PORT`, `GRAFANA_CONTAINER`, `GRAFANA_PORT`, `GRAFANA_ROOT_URL`,
`GRAFANA_ADMIN_PASSWORD`, `SLACK_WEBHOOK_URL`.

## Important Details

- **The monitored drive set is defined once**, by `physical_drives` in `alerts_config.json`, and
  compiled into the `fs:physical:*` recording rules. Alerts and dashboard panels read those rules;
  never re-derive the drive set with a mountpoint regex. It is an fstype *allowlist*, which also means
  each physical drive is counted only on the host that owns it (it appears as nfs4/cifs elsewhere).
- **Recording rules in the `physical_drives` group must read raw `node_filesystem_*` metrics**, never
  another recorded series. Recording rules emit no staleness markers, so instant-selecting a recorded
  series re-finds the previous sample within the 5m lookback and writes a fresh one forever — phantom
  drives keep reporting and alerting after they are unmounted or relabeled. Range selectors
  (`avg_over_time(...[1d])`) are safe, which is why the projection group may read recorded series.
- **Node Exporter needs host networking.** `/proc/net/dev` is network-namespace scoped and `/proc/net`
  resolves in the reading process's namespace, so `--path.procfs` alone cannot fix network metrics; on
  a bridge network the exporter reported the monitoring container's own veth as the host's only NIC.
- `--path.rootfs=/rootfs` strips the `/rootfs` prefix from mountpoint labels so this exporter emits the
  same labels as a Kubernetes node-exporter DaemonSet, letting one Prometheus scrape a mixed fleet.
- A host's own FQDN typically resolves to `127.0.1.1`, which inside a container is the container's
  loopback — hence `host.docker.internal` plus `extra_hosts: host-gateway` for the local exporter.
- `config/` is mounted as a directory, not as individual files: a single-file bind mount pins the
  source inode, so rewriting a config leaves a running container reading the old file and makes
  `/-/reload` a silent no-op.
- `config/prometheus.yml` hardcodes hostnames, ports and `hostname` labels — Prometheus has no native
  env-var expansion. Every target needs an explicit `hostname` label, and exactly one exporter should
  be scraped per host to avoid double-counting drives.
- The `notification_interval` in alerts_config.json is adjusted by subtracting the alert type's rule
  group interval to compute Grafana's `repeat_interval` (see `repeat_interval_for()`).
- **Projections need history.** From a fresh Prometheus, `days_until_full` appears after roughly
  `growth_window + 1d`, and projection alerts can only fire after roughly `confirm_window + 1d`
  (~29 days at the default 28d). Until then the gating finds no data and stays silent.
- `noDataState` is per rule. Presence-based alerts whose metric is absent while healthy (the storage
  projection) use `OK`; the scrape watchdog uses `Alerting`, because a vanished target is the failure.
- Dashboard is fully dynamic and doesn't need regeneration when drives change.
- GPU monitoring auto-detects: the `has_gpus` template variable queries `DCGM_FI_DEV_GPU_UTIL` — if no
  DCGM metrics exist, the GPU row and all its panels are hidden. DCGM Exporter requires the NVIDIA
  Container Toolkit on the host, and uses `restart: unless-stopped` because it exits 0 when the NVIDIA
  driver is reloaded underneath it (`on-failure` treats that as success and never restarts it).
