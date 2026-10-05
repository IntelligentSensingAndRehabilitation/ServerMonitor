# Server Monitor

![Dashboard](images/dashboard.png)

A server monitoring stack built on Prometheus, Node Exporter, DCGM Exporter and Grafana. Monitors CPU,
memory, network, disk I/O, GPUs and physical-drive storage, with storage-growth projections and Slack
alerting. Drives are discovered automatically — adding a disk needs no config change.

## Components

- **Prometheus**: Collects and stores metrics; also evaluates the recording rules that define the
  monitored drive set and the storage projections
- **Node Exporter**: Exposes host system metrics
- **DCGM Exporter**: Exposes NVIDIA GPU metrics; simply absent on hosts without GPUs
- **Grafana**: Visualizes metrics and evaluates/routes alerts

## Prerequisites

- Docker and Docker Compose
- A Linux host with the drives you want to monitor
- For GPU metrics: NVIDIA drivers and the NVIDIA Container Toolkit

## Deployment

### 1. Clone the repository

```bash
git clone <repository-url>
cd ServerMonitor
```

### 2. Configure environment variables

Create a `.env` file. Every variable is required — the stack fails to start rather than falling back
to a silent default.

```bash
NODE_EXPORTER_CONTAINER=node-exporter-c
NODE_EXPORTER_PORT=9100

# Host port node-exporter binds. It uses host networking (see "Why host networking"
# below), so this must be free. Use 9101 on Kubernetes nodes, where the cluster's
# own node-exporter DaemonSet already owns 9100.
NODE_EXPORTER_HOST_PORT=9100

PROMETHEUS_CONTAINER=prometheus-c
PROMETHEUS_PORT=9090

GRAFANA_CONTAINER=grafana-c
GRAFANA_PORT=5601
GRAFANA_ROOT_URL=http://YOUR_HOSTNAME:5601
GRAFANA_ADMIN_PASSWORD=<choose-a-password>

SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

Notes:
- `GRAFANA_ROOT_URL` makes links in Slack notifications point at the server rather than localhost.
  Keep its port in sync with `GRAFANA_PORT`.
- `GRAFANA_ADMIN_PASSWORD` is applied on every start, so it survives container recreation. A password
  changed through the UI does not.

### 3. Configure alerts

Edit `config/alerts_config.json`. This file is the single source of truth for thresholds, timings and
the definition of a monitored drive.

```json
{
  "physical_drives": {
    "fstypes": ["ext4", "ext3", "xfs", "btrfs", "zfs"],
    "mountpoint_exclude_regex": "/(boot|snap|run|dev|proc|sys|var/lib|autofs)(|/.*)"
  },
  "rule_group_intervals": {
    "watchdog": "1m",
    "system": "1m",
    "storage": "5m",
    "storage_projection": "15m",
    "gpu": "1m"
  },
  "storage_alerts": {
    "enabled": true,
    "threshold_percent": 90,
    "sustained_duration": "15m",
    "notification_interval": "30m"
  },
  "storage_projection_alerts": {
    "enabled": true,
    "days_until_full_threshold": 30,
    "growth_window": "7d",
    "confirm_window": "28d",
    "min_used_percent": 75,
    "sustained_duration": "6h",
    "notification_interval": "7d"
  }
}
```

Common options:

| Key | Meaning |
|-----|---------|
| `enabled` | Enable or disable this alert type |
| `threshold_percent` | Percentage that triggers the alert |
| `sustained_duration` | How long the condition must hold before firing (Grafana's `for`) |
| `notification_interval` | How often Slack is re-notified while an alert is active |
| `rule_group_intervals` | How often each alert type is evaluated |

Valid duration formats are a whole number plus one of `s`, `m`, `h`, `d` — for example `30s`, `15m`,
`6h`, `7d`. The format is strictly validated; `5mm` is an error rather than being read as 5 minutes.

`generate_alerts.py` also cross-checks the config and refuses to write files if, for example, a
`sustained_duration` is shorter than its rule group interval, or `confirm_window` is not longer than
`growth_window`.

### 4. Generate rules

```bash
python3 generate_alerts.py
```

This writes three files, none of which should be hand-edited:

- `config/recording_rules.yml` — Prometheus recording rules (monitored drive set, growth, projection)
- `config/alert_rules.yml` — Grafana alert rules
- `config/notification_policies.yml` — Slack routing and repeat intervals

### 5. Start the stack

```bash
docker compose up -d
```

### 6. Access Grafana

Browse to `http://<server>:<GRAFANA_PORT>`. Viewing requires no login (anonymous read-only access is
enabled); administration uses `admin` with `GRAFANA_ADMIN_PASSWORD`.

The "Server Monitor - Dynamic" dashboard is provisioned automatically. Use the **Host** and
**mountpoint** dropdowns to filter.

## Which drives are monitored

"Physical drive" is defined exactly once, in `physical_drives` in `config/alerts_config.json`, and
compiled into the `fs:physical:*` recording rules that every alert and dashboard panel reads.

It is an **allowlist of local block-backed filesystem types**, not a list of mountpoints:

```promql
node_filesystem_size_bytes{fstype=~"ext4|ext3|xfs|btrfs|zfs", mountpoint!~"..."}
```

This has a useful consequence for a fleet with shared storage. A disk is `ext4`/`xfs` on the host that
physically owns it and `nfs4`/`cifs` on every host that mounts it remotely, so each physical drive is
counted exactly once — on its owner — with no per-host configuration. Network shares, CIFS mounts and
autofs paths are excluded everywhere.

An allowlist is deliberate: a future `sshfs` or `s3fs` mount would silently pass a denylist, whereas
here anything unrecognized is excluded until it is added on purpose.

Recording rules in the `physical_drives` group read the raw `node_filesystem_*` metrics and never
another recorded series. Recording rules do not emit staleness markers, so a rule that instant-selects
a recorded series keeps finding the previous sample inside Prometheus's 5-minute lookback and writes a
fresh one from it indefinitely — which would leave unmounted drives reporting, and alerting, forever.

## Storage projections

The projection answers "is this drive actually filling up, and how long do I have?" It is deliberately
**not** a least-squares fit. A single bulk copy or a single large delete would dominate such a fit: on
one host the 7-day and 28-day trends for `/home` disagreed in sign (−85 vs +8 GB/day), so the answer
depended entirely on the window chosen.

Instead, growth is the difference between two 1-day averages a fixed interval apart, so one burst can
move at most one endpoint:

```promql
(avg_over_time(fs:physical:used_bytes[1d]) - avg_over_time(fs:physical:used_bytes[1d] offset 7d)) / 7
```

`fs:physical:days_until_full` is then available bytes divided by that rate. It is **absent when a
drive is not filling** — absence is the healthy state, which is why the alert sets `noDataState: OK`
and the dashboard shows "not filling".

The alert fires only when all three of these hold, for `sustained_duration`:

1. `days_until_full` is below `days_until_full_threshold`
2. the `confirm_window` (28d) trend also shows growth — one burst cannot satisfy both windows
3. the drive is past `min_used_percent` — below that, nobody would act

Because a cleanup immediately changes the recent average, the alert clears after the cleanup instead
of staying latched on a stale trend.

**History requirement.** The projection needs history to exist before it can say anything. From a
fresh Prometheus, or after mountpoint labels change:

- `days_until_full` appears after about `growth_window + 1d` (~8 days)
- projection **alerts** can first fire after about `confirm_window + 1d` (~29 days)

Until then the gating simply finds no data and stays silent, which is the safe direction. This is also
why retention is 90d rather than 30d — a 28-day comparison window had no headroom at 30d.

For "who filled this drive" rather than "when will it fill", per-directory accounting is needed — a
nightly `du` into node-exporter's textfile collector. That is not part of this stack.

## Alerts

| Alert | Fires when |
|-------|-----------|
| Scrape Target Down | Any Prometheus target has `up < 1`, or vanishes entirely |
| Memory Usage | Memory usage above threshold for the sustained duration |
| Storage | A monitored drive is fuller than `threshold_percent` |
| Storage Projection | A drive is projected to fill, gated as described above |
| GPU Temperature / Memory / XID | Per-GPU temperature, framebuffer usage, or any XID error |

**Scrape Target Down** is the watchdog over everything else, and it treats missing data as a failure
rather than as "no news". Without it an exporter can die unnoticed and every alert derived from it
silently stops evaluating — which is exactly how a dead DCGM exporter went unnoticed for seven weeks.

Slack message bodies render `annotations.summary`, which `generate_alerts.py` builds from the
configured thresholds. Contact points in `config/alerting.yml` must not restate a threshold or window,
or it will disagree with the config the moment someone changes it.

## Why host networking

`node-exporter` runs with `network_mode: host`. `/proc/net/dev` is scoped to a network namespace, and
`/proc/net` resolves in the *reading* process's namespace, so pointing `--path.procfs` at the host is
not enough: on a bridge network the exporter reports the monitoring container's own veth pair as the
host's only interface. This is the same reason a Kubernetes node-exporter DaemonSet sets
`hostNetwork: true`.

Two consequences:

- The exporter binds a host port directly, so Prometheus scrapes it by hostname. For the local host
  that is `host.docker.internal` (mapped via `extra_hosts`), because a host's own FQDN usually
  resolves to `127.0.1.1` in `/etc/hosts`, which inside a container is the container's loopback.
- `--path.rootfs=/rootfs` strips the `/rootfs` prefix from mountpoint labels, so this exporter emits
  the same labels (`/home`, `/mnt/data0`) as a Kubernetes DaemonSet. One central Prometheus can
  therefore scrape a mixed fleet with a single set of rules.

## Monitoring several hosts from one place

Exporters stay per-host; Prometheus and Grafana do not have to be. To scrape a fleet from one stack,
add entries to the `node-exporter` job in `config/prometheus.yml`:

```yaml
    static_configs:
      - targets: ['host.docker.internal:9101']   # the host running this stack
        labels:
          hostname: 'jc-compute03'
      - targets: ['jc-compute01.ric.org:9100']
        labels:
          hostname: 'jc-compute01'
```

Rules:

- Every target needs an explicit `hostname` label. All recording rules and dashboard panels group by
  it, and the Host dropdown is built from it.
- **Scrape exactly one exporter per host.** A Kubernetes node already runs a node-exporter DaemonSet
  on `:9100`; scraping both it and this stack's container would count that host's drives twice.
- Hosts that are not cluster members just need this stack's node-exporter reachable on
  `NODE_EXPORTER_HOST_PORT`.

Prometheus has no environment-variable expansion, which is why hostnames and ports are literal there.

## Updating configuration

### Alert thresholds or timings

```bash
python3 generate_alerts.py
docker compose restart grafana      # alert rules and routing
docker compose restart prometheus   # recording rules
```

Prometheus can also reload rules without restarting, which avoids dropping the in-memory head block:

```bash
docker exec prometheus-c wget -qO- --post-data='' http://localhost:9090/-/reload
```

`config/` is mounted as a whole directory rather than as individual files. A single-file bind mount
pins the source inode, so rewriting a config would leave a running container reading the old file and
make `/-/reload` a silent no-op.

### Adding or removing drives

Nothing to do. Drives are discovered by filesystem type, and both the alerts and the dashboard follow
the recording rules.

## Tests

```bash
python3 -m pytest tests/
```

If the host has no pytest, run them in a container:

```bash
docker run --rm -v "$PWD":/w:ro -w /w python:3.12-slim \
  sh -c 'pip install -q pytest pyyaml && python -m pytest tests/ -q'
```

Validate generated rules before deploying:

```bash
docker run --rm -v "$PWD/config":/etc/prometheus:ro --entrypoint promtool \
  prom/prometheus:v3.8.0 check config /etc/prometheus/prometheus.yml
```

## Monitored metrics

- **CPU**: utilization per host, using `rate` over 5m
- **Memory**: consumption percentage
- **Network**: throughput per physical interface; virtual interfaces (veth, lxc, cilium, bridges) are
  excluded to bound series cardinality
- **Disk I/O**: read/write throughput for NVMe, MD and SCSI devices
- **Storage**: total, used, available, used %, days until full, and 7d/28d growth rates per drive
- **GPU**: utilization, framebuffer memory, temperature, power draw and XID errors per GPU
