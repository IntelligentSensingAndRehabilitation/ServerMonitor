# Server Monitor

A dynamic server monitoring dashboard using Prometheus, Node Exporter, and Grafana. Monitors CPU, memory, network, disk I/O, and storage usage with automatic drive detection and configurable alerts.

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

### 3. Configure Alerts

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
- **evaluation_interval**: How often Grafana checks if the condition is true
- **notification_interval**: ⚠️ **IMPORTANT** - Controls how frequently you receive Slack notifications while an alert is firing

**Understanding notification_interval:**
This is the PRIMARY setting that controls alert frequency. When an alert is active, Grafana will send a Slack notification at this interval.

- For testing: `"5s"` = notification every 5 seconds
- For production storage alerts: `"24h"` = one notification per day (recommended)
- For production CPU/memory alerts: `"1h"` = one notification per hour

**Note:** There's a fixed 10-second initial delay (`group_wait`) before the first notification is sent.

### 4. Generate Alerts

Generate alert rules from the configuration:

```bash
python3 generate_alerts.py
```

**Note**: Both dashboard and alerts are now fully dynamic! Alerts automatically monitor all physical drives.

### 5. Start Services

```bash
docker compose up -d
```

### 6. Access Grafana

Open your browser and navigate to `http://<server-ip>:<port>` where `<port>` is the value you set for `GRAFANA_PORT` in your `.env` file (default: 3000).

Default credentials:
- Username: `admin`
- Password: `admin`

The dashboard "Server Monitor - Dynamic" should be automatically loaded and will show all your filesystems!

Note: If you changed `GRAFANA_PORT` to something other than 3000 (e.g., 4000), you'll access Grafana at that port on the host, but the container internally still runs on port 3000.

### 7. Select Which Drives to Monitor (Optional)

In the Grafana dashboard, use the "mountpoint" dropdown at the top to select which filesystems you want to see in the storage gauges. By default, all non-tmpfs filesystems are shown.

## Dashboard Features

### Dynamic Drive Detection
The dashboard automatically detects and displays **all available filesystems** from Prometheus. No need to regenerate the dashboard when adding or removing drives!

### Interactive Controls
Use the **mountpoint dropdown** at the top of the dashboard to select which filesystems to monitor. Changes apply instantly without reloading.

### Layout
- **Row 1**: CPU Usage and Memory Usage (side by side)
- **Row 2**: Storage gauges - one per selected filesystem, showing usage percentage
- **Row 3**: Network Traffic and Disk I/O (side by side)
- **Row 4**: Storage Details table with size, usage, and availability for all selected filesystems

## Updating Configuration

### Adding/Removing Monitored Drives

**Everything is automatic!** Both dashboard and alerts discover drives dynamically.

- **Dashboard**: Use the dropdown to select which filesystems to display
- **Alerts**: Automatically monitor all physical drives (no configuration needed)

### Modifying Alert Settings

To change alert thresholds or notification intervals:

1. Edit `config/alerts_config.json`
2. Run `python3 generate_alerts.py`
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

### Drives not appearing in dropdown

- The dashboard shows all filesystems that Prometheus discovers automatically
- Check available metrics: `docker exec prometheus-c wget -qO- "http://localhost:9090/api/v1/query?query=node_filesystem_size_bytes"`
- Verify Node Exporter is running: `docker ps | grep node-exporter`

### Alerts not working

- Check Grafana alerting is enabled: Grafana → Alerting → Alert rules
- Verify Slack webhook URL in `.env` file
- Check Grafana logs: `docker compose logs grafana`

### Port conflicts

- Update ports in `.env` file if defaults are already in use
- Restart services: `docker compose down && docker compose up -d`

## File Structure

```
server_monitor/
├── config/
│   ├── alerts_config.json           # Alert thresholds and settings
│   ├── alerting.yml                 # Grafana alerting provisioning config
│   ├── alert_rules.yml              # Generated alert rules (auto-generated)
│   ├── notification_policies.yml    # Notification routing (auto-generated)
│   ├── dashboard_dynamic.json       # Dynamic Grafana dashboard
│   ├── dashboard.yml                # Dashboard provisioning config
│   ├── datasources.yml              # Prometheus datasource config
│   └── prometheus.yml               # Prometheus scrape config
├── docker-compose.yaml              # Docker services definition
├── generate_alerts.py               # Alert generation script
├── .env                             # Environment variables
└── README.md                        # This file
```

## Benefits

- ✅ **Zero configuration**: Dashboard and alerts automatically discover all drives
- ✅ **No manual drive lists**: Everything is dynamic from Prometheus
- ✅ **Minimal files**: Only essential configuration needed
- ✅ **Easy maintenance**: Change thresholds in one place
- ✅ **Network drive filtering**: Automatically excludes NFS/SMB mounts
- ✅ **Device names in alerts**: Slack shows "nvme3n1p4 is 87% full"