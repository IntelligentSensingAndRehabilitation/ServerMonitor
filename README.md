# Server Monitor

A simplified server monitoring dashboard using Prometheus, Node Exporter, and Grafana. Monitors CPU, memory, network, disk I/O, and storage usage for specific drives.

## Components

- **Prometheus**: Collects and stores metrics
- **Node Exporter**: Exposes system metrics
- **Grafana**: Visualizes metrics in a dashboard

## Prerequisites

- Docker and Docker Compose installed
- Linux server with the drives you want to monitor

## Deployment

### 1. Clone or Copy Repository

```bash
git clone <repository-url>
cd server_monitor
```

### 2. Configure Environment Variables

Create a `.env` file:

```bash
NODE_EXPORTER_CONTAINER=node-exporter-c
NODE_EXPORTER_PORT=9100

PROMETHEUS_CONTAINER=prometheus-c
PROMETHEUS_PORT=9090

GRAFANA_CONTAINER=grafana-c
GRAFANA_PORT=3000

SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

Replace the `SLACK_WEBHOOK_URL` with your actual Slack webhook URL for alert notifications.

### 3. Configure Monitored Drives

Edit `config/monitored_drives.json` to specify which drives to monitor. Update the mountpoints based on your server's configuration.

**Important**: Mountpoints will be prefixed with `/rootfs` when accessed by Node Exporter running in Docker.

Example configuration:

```json
{
  "comment": "Configuration for monitored storage drives",
  "drives": [
    {
      "mountpoint": "/rootfs",
      "label": "Root /",
      "description": "Root filesystem"
    },
    {
      "mountpoint": "/rootfs/home",
      "label": "Home",
      "description": "Home partition"
    },
    {
      "mountpoint": "/rootfs/mnt/data0",
      "label": "Data0 (RAID1)",
      "description": "RAID1 array"
    }
  ]
}
```

To find your mountpoints, run `df -h` on the host and prefix each path with `/rootfs`.

### 4. Configure Alerts

Edit `config/alerts_config.json` to customize alert thresholds and notification intervals:

```json
{
  "slack": {
    "webhook_url": "REPLACE_WITH_YOUR_SLACK_WEBHOOK_URL",
    "channel": "#alerts",
    "mention_users": []
  },
  "storage_alerts": {
    "enabled": true,
    "threshold_percent": 90,
    "evaluation_interval": "5m",
    "notification_interval": "24h"
  },
  "cpu_alerts": {
    "enabled": true,
    "threshold_percent": 80,
    "sustained_duration": "10m",
    "evaluation_interval": "1m",
    "notification_interval": "1h"
  },
  "memory_alerts": {
    "enabled": true,
    "threshold_percent": 90,
    "sustained_duration": "5m",
    "evaluation_interval": "1m",
    "notification_interval": "1h"
  }
}
```

Configuration options:
- **enabled**: Enable or disable alerts for this metric
- **threshold_percent**: Percentage threshold that triggers the alert
- **sustained_duration**: How long the threshold must be exceeded before alerting (CPU/Memory only)
- **evaluation_interval**: How often to check the metric
- **notification_interval**: How often to send notifications when alert is active

### 5. Generate Dashboard

The dashboard generation script reads both the monitored drives and alerts configuration to create the dashboard with alert rules:

```bash
python3 simplify_dashboard.py
```

### 6. Start Services

```bash
docker compose up -d
```

### 7. Access Grafana

Open your browser and navigate to `http://<server-ip>:<port>` where `<port>` is the value you set for `GRAFANA_PORT` in your `.env` file (default: 3000).

Default credentials:
- Username: `admin`
- Password: `admin`

The dashboard "Server Monitor - Simplified" should be automatically loaded.

Note: If you changed `GRAFANA_PORT` to something other than 3000 (e.g., 4000), you'll access Grafana at that port on the host, but the container internally still runs on port 3000.

## Dashboard Layout

- **Row 1**: CPU Usage and Memory Usage (side by side)
- **Row 2**: Storage gauges showing usage percentage for each monitored drive
- **Row 3**: Network Traffic and Disk I/O (side by side)
- **Row 4**: Storage Details table with size, usage, and availability

## Updating Configuration

### Modifying Monitored Drives

To add or remove monitored drives:

1. Edit `config/monitored_drives.json`
2. Run `python3 simplify_dashboard.py`
3. Restart Grafana: `docker compose restart grafana`

### Modifying Alert Settings

To change alert thresholds or notification intervals:

1. Edit `config/alerts_config.json`
2. Run `python3 simplify_dashboard.py`
3. Restart Grafana: `docker compose restart grafana`

## Monitoring Metrics

- **CPU Usage**: Overall CPU utilization percentage
- **Memory Usage**: Memory consumption percentage
- **Network Traffic**: Network I/O by interface (receive/transmit)
- **Disk I/O**: Disk read/write throughput for NVMe and MD devices
- **Storage**: Usage percentage, total, used, and available space for configured drives

## Alerts

The dashboard includes configurable alerts for:

- **Storage Alerts**: Triggered when any monitored drive exceeds the configured threshold (default: 90%). Notifications sent daily when active.
- **CPU Alerts**: Triggered when CPU usage exceeds the threshold for a sustained duration (default: 80% for 10 minutes). Notifications sent hourly.
- **Memory Alerts**: Triggered when memory usage exceeds the threshold for a sustained duration (default: 90% for 5 minutes). Notifications sent hourly.

All alerts send notifications to the configured Slack webhook URL. Alert thresholds, durations, and notification intervals are fully configurable via `config/alerts_config.json`.

## Troubleshooting

### Dashboard shows "No Data"

- Check that all containers are running: `docker ps`
- Verify Prometheus is scraping metrics: `http://<server-ip>:9090/targets`
- Verify the datasource is configured correctly in Grafana's settings

### Drives not appearing

- Verify mountpoints in `config/monitored_drives.json` are correct
- Remember to prefix host mountpoints with `/rootfs`
- Check available metrics: `docker exec prometheus-c wget -qO- "http://localhost:9090/api/v1/query?query=node_filesystem_size_bytes"`

### Port conflicts

- Update ports in `.env` file if defaults are already in use
- Restart services: `docker compose down && docker compose up -d`

## File Structure

```
server_monitor/
├── config/
│   ├── alerts_config.json      # Alert configuration
│   ├── alerting.yml            # Grafana alerting provisioning config
│   ├── dashboard.json          # Generated Grafana dashboard
│   ├── dashboard.yml           # Dashboard provisioning config
│   ├── datasources.yml         # Prometheus datasource config
│   ├── monitored_drives.json   # Drive monitoring configuration
│   └── prometheus.yml          # Prometheus scrape config
├── docker-compose.yaml         # Docker services definition
├── simplify_dashboard.py       # Dashboard generation script
├── .env                        # Environment variables
└── README.md                   # This file
```
