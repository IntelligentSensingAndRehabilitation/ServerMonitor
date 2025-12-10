#!/usr/bin/env python3
"""
Script to create a simplified Grafana dashboard focused on specific storage drives
"""

import json
import os
import yaml

# Datasource UID - defined in config/datasources.yml
DATASOURCE_UID = "prometheus"

# Load monitored drives from config file
config_path = os.path.join(os.path.dirname(__file__), 'config', 'monitored_drives.json')
with open(config_path, 'r') as f:
    config = json.load(f)

MONITORED_DRIVES = config['drives']
MONITORED_MOUNTPOINTS = [d['mountpoint'] for d in MONITORED_DRIVES]

# Load alerts configuration
alerts_config_path = os.path.join(os.path.dirname(__file__), 'config', 'alerts_config.json')
with open(alerts_config_path, 'r') as f:
    alerts_config = json.load(f)

# Store alert rules for unified alerting
alert_rules = []

def create_unified_alert_rule(uid, title, expr, summary, description, for_duration, threshold):
    """Helper function to create a Grafana unified alert rule"""
    return {
        "uid": uid,
        "title": title,
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "relativeTimeRange": {
                    "from": 600,
                    "to": 0
                },
                "datasourceUid": DATASOURCE_UID,
                "model": {
                    "expr": expr,
                    "interval": "",
                    "refId": "A",
                    "datasource": {
                        "type": "prometheus",
                        "uid": DATASOURCE_UID
                    }
                }
            },
            {
                "refId": "B",
                "relativeTimeRange": {
                    "from": 0,
                    "to": 0
                },
                "datasourceUid": "-100",
                "model": {
                    "datasource": {
                        "type": "__expr__",
                        "uid": "-100"
                    },
                    "expression": "A",
                    "reducer": "last",
                    "refId": "B",
                    "type": "reduce"
                }
            },
            {
                "refId": "C",
                "relativeTimeRange": {
                    "from": 0,
                    "to": 0
                },
                "datasourceUid": "-100",
                "model": {
                    "datasource": {
                        "type": "__expr__",
                        "uid": "-100"
                    },
                    "conditions": [
                        {
                            "evaluator": {
                                "params": [threshold],
                                "type": "gt"
                            },
                            "operator": {
                                "type": "and"
                            },
                            "query": {
                                "params": ["B"]
                            },
                            "type": "query"
                        }
                    ],
                    "expression": "B",
                    "refId": "C",
                    "type": "threshold"
                }
            }
        ],
        "noDataState": "NoData",
        "execErrState": "Alerting",
        "for": for_duration,
        "annotations": {
            "summary": summary,
            "description": description
        },
        "labels": {},
        "isPaused": False
    }


dashboard = {
    "annotations": {
        "list": [
            {
                "builtIn": 1,
                "datasource": {"type": "datasource", "uid": "grafana"},
                "enable": True,
                "hide": True,
                "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts",
                "target": {"limit": 100, "matchAny": False, "tags": [], "type": "dashboard"},
                "type": "dashboard"
            }
        ]
    },
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 1,
    "id": None,
    "links": [],
    "panels": [],
    "refresh": "30s",
    "schemaVersion": 39,
    "tags": ["linux"],
    "templating": {"list": []},
    "time": {"from": "now-1h", "to": "now"},
    "timepicker": {},
    "timezone": "browser",
    "title": "Server Monitor - Simplified",
    "uid": "server-monitor-simple",
    "version": 0,
    "weekStart": ""
}

# Panel counter for positioning
panel_id = 1
y_pos = 0

panels = []

# Row 1: CPU and Memory (side by side)
# CPU Usage
cpu_panel = {
    "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {
                "axisBorderShow": False,
                "axisCenteredZero": False,
                "axisColorMode": "text",
                "axisLabel": "",
                "axisPlacement": "auto",
                "barAlignment": 0,
                "drawStyle": "line",
                "fillOpacity": 20,
                "gradientMode": "none",
                "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                "lineInterpolation": "linear",
                "lineWidth": 1,
                "pointSize": 5,
                "scaleDistribution": {"type": "linear"},
                "showPoints": "never",
                "spanNulls": False,
                "stacking": {"group": "A", "mode": "none"},
                "thresholdsStyle": {"mode": "off"}
            },
            "mappings": [],
            "max": 100,
            "min": 0,
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "red", "value": alerts_config["cpu_alerts"]["threshold_percent"]}
                ]
            },
            "unit": "percent"
        },
        "overrides": []
    },
    "gridPos": {"h": 8, "w": 12, "x": 0, "y": y_pos},
    "id": panel_id,
    "options": {
        "legend": {"calcs": ["lastNotNull", "mean"], "displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "multi", "sort": "none"}
    },
    "targets": [
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": "100 - (avg by(instance) (irate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)",
            "legendFormat": "CPU Usage",
            "refId": "A"
        }
    ],
    "title": "CPU Usage",
    "type": "timeseries"
}

# Add CPU alert if enabled
if alerts_config["cpu_alerts"]["enabled"]:
    cpu_expr = f"100 - (avg by(instance) (irate(node_cpu_seconds_total{{mode=\"idle\"}}[5m])) * 100)"
    alert_rules.append(create_unified_alert_rule(
        uid="cpu-usage-alert",
        title="CPU Usage Alert",
        expr=cpu_expr,
        summary=alerts_config["cpu_alerts"]["message_template"].replace("{{threshold}}", str(alerts_config["cpu_alerts"]["threshold_percent"])).replace("{{duration}}", alerts_config["cpu_alerts"]["sustained_duration"]),
        description=f"CPU usage has exceeded {alerts_config['cpu_alerts']['threshold_percent']}% for {alerts_config['cpu_alerts']['sustained_duration']}",
        for_duration=alerts_config["cpu_alerts"]["sustained_duration"],
        threshold=alerts_config["cpu_alerts"]["threshold_percent"]
    ))

panels.append(cpu_panel)
panel_id += 1

# Memory Usage
memory_panel = {
    "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {
                "axisBorderShow": False,
                "axisCenteredZero": False,
                "axisColorMode": "text",
                "axisLabel": "",
                "axisPlacement": "auto",
                "barAlignment": 0,
                "drawStyle": "line",
                "fillOpacity": 20,
                "gradientMode": "none",
                "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                "lineInterpolation": "linear",
                "lineWidth": 1,
                "pointSize": 5,
                "scaleDistribution": {"type": "linear"},
                "showPoints": "never",
                "spanNulls": False,
                "stacking": {"group": "A", "mode": "none"},
                "thresholdsStyle": {"mode": "off"}
            },
            "mappings": [],
            "max": 100,
            "min": 0,
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "red", "value": alerts_config["memory_alerts"]["threshold_percent"]}
                ]
            },
            "unit": "percent"
        },
        "overrides": []
    },
    "gridPos": {"h": 8, "w": 12, "x": 12, "y": y_pos},
    "id": panel_id,
    "options": {
        "legend": {"calcs": ["lastNotNull", "mean"], "displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "multi", "sort": "none"}
    },
    "targets": [
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": "100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))",
            "legendFormat": "Memory Usage",
            "refId": "A"
        }
    ],
    "title": "Memory Usage",
    "type": "timeseries"
}

# Add Memory alert if enabled
if alerts_config["memory_alerts"]["enabled"]:
    memory_expr = f"100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))"
    alert_rules.append(create_unified_alert_rule(
        uid="memory-usage-alert",
        title="Memory Usage Alert",
        expr=memory_expr,
        summary=alerts_config["memory_alerts"]["message_template"].replace("{{value}}", str(alerts_config["memory_alerts"]["threshold_percent"])).replace("{{threshold}}", str(alerts_config["memory_alerts"]["threshold_percent"])),
        description=f"Memory usage has exceeded {alerts_config['memory_alerts']['threshold_percent']}% for {alerts_config['memory_alerts']['sustained_duration']}",
        for_duration=alerts_config["memory_alerts"]["sustained_duration"],
        threshold=alerts_config["memory_alerts"]["threshold_percent"]
    ))

panels.append(memory_panel)
panel_id += 1
y_pos += 8

# Row 2: Storage gauge panels
num_drives = len(MONITORED_DRIVES)
gauge_width = 24 // num_drives  # Divide width evenly

x_pos = 0
for drive in MONITORED_DRIVES:
    mountpoint = drive['mountpoint']
    label = drive['label']

    storage_panel = {
        "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": [],
                "max": 100,
                "min": 0,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 70},
                        {"color": "orange", "value": 85},
                        {"color": "red", "value": alerts_config["storage_alerts"]["threshold_percent"]}
                    ]
                },
                "unit": "percent"
            },
            "overrides": []
        },
        "gridPos": {"h": 7, "w": gauge_width, "x": x_pos, "y": y_pos},
        "id": panel_id,
        "options": {
            "minVizHeight": 75,
            "minVizWidth": 75,
            "orientation": "auto",
            "reduceOptions": {
                "values": False,
                "calcs": ["lastNotNull"],
                "fields": ""
            },
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
            "sizing": "auto"
        },
        "pluginVersion": "11.6.1",
        "targets": [
            {
                "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
                "expr": f"100 * (1 - (node_filesystem_avail_bytes{{mountpoint=\"{mountpoint}\",fstype!=\"tmpfs\"}} / node_filesystem_size_bytes{{mountpoint=\"{mountpoint}\",fstype!=\"tmpfs\"}}))",
                "refId": "A"
            }
        ],
        "title": label,
        "type": "gauge"
    }

    # Add storage alert if enabled
    if alerts_config["storage_alerts"]["enabled"]:
        storage_expr = f"100 * (1 - (node_filesystem_avail_bytes{{mountpoint=\"{mountpoint}\",fstype!=\"tmpfs\"}} / node_filesystem_size_bytes{{mountpoint=\"{mountpoint}\",fstype!=\"tmpfs\"}}))"
        # Get device name for the alert
        device_label = drive.get('description', label)
        alert_rules.append(create_unified_alert_rule(
            uid=f"storage-alert-{label.lower().replace(' ', '-').replace('/', '')}",
            title=f"Storage Alert - {label}",
            expr=storage_expr,
            summary=alerts_config["storage_alerts"]["message_template"].replace("{{mountpoint}}", mountpoint).replace("{{device}}", device_label).replace("{{value}}", str(alerts_config["storage_alerts"]["threshold_percent"])),
            description=f"Storage on {label} ({mountpoint}) has exceeded {alerts_config['storage_alerts']['threshold_percent']}%",
            for_duration=alerts_config["storage_alerts"]["evaluation_interval"],
            threshold=alerts_config["storage_alerts"]["threshold_percent"]
        ))

    panels.append(storage_panel)
    panel_id += 1
    x_pos += gauge_width

y_pos += 7

# Row 3: Network Traffic
panels.append({
    "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {
                "axisBorderShow": False,
                "axisCenteredZero": False,
                "axisColorMode": "text",
                "axisLabel": "",
                "axisPlacement": "auto",
                "barAlignment": 0,
                "drawStyle": "line",
                "fillOpacity": 20,
                "gradientMode": "none",
                "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                "lineInterpolation": "linear",
                "lineWidth": 1,
                "pointSize": 5,
                "scaleDistribution": {"type": "linear"},
                "showPoints": "never",
                "spanNulls": False,
                "stacking": {"group": "A", "mode": "none"},
                "thresholdsStyle": {"mode": "off"}
            },
            "mappings": [],
            "thresholds": {
                "mode": "absolute",
                "steps": [{"color": "green", "value": None}]
            },
            "unit": "Bps"
        },
        "overrides": [
            {"matcher": {"id": "byRegexp", "options": ".*Transmit.*"}, "properties": [{"id": "custom.transform", "value": "negative-Y"}]}
        ]
    },
    "gridPos": {"h": 8, "w": 12, "x": 0, "y": y_pos},
    "id": panel_id,
    "options": {
        "legend": {"calcs": ["lastNotNull"], "displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "multi", "sort": "none"}
    },
    "targets": [
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": "irate(node_network_receive_bytes_total{device!~\"lo|docker.*|veth.*\"}[5m])",
            "legendFormat": "{{device}} Receive",
            "refId": "A"
        },
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": "irate(node_network_transmit_bytes_total{device!~\"lo|docker.*|veth.*\"}[5m])",
            "legendFormat": "{{device}} Transmit",
            "refId": "B"
        }
    ],
    "title": "Network Traffic",
    "type": "timeseries"
})
panel_id += 1

# Disk I/O
panels.append({
    "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "palette-classic"},
            "custom": {
                "axisBorderShow": False,
                "axisCenteredZero": False,
                "axisColorMode": "text",
                "axisLabel": "",
                "axisPlacement": "auto",
                "barAlignment": 0,
                "drawStyle": "line",
                "fillOpacity": 20,
                "gradientMode": "none",
                "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                "lineInterpolation": "linear",
                "lineWidth": 1,
                "pointSize": 5,
                "scaleDistribution": {"type": "linear"},
                "showPoints": "never",
                "spanNulls": False,
                "stacking": {"group": "A", "mode": "none"},
                "thresholdsStyle": {"mode": "off"}
            },
            "mappings": [],
            "thresholds": {
                "mode": "absolute",
                "steps": [{"color": "green", "value": None}]
            },
            "unit": "Bps"
        },
        "overrides": [
            {"matcher": {"id": "byRegexp", "options": ".*Write.*"}, "properties": [{"id": "custom.transform", "value": "negative-Y"}]}
        ]
    },
    "gridPos": {"h": 8, "w": 12, "x": 12, "y": y_pos},
    "id": panel_id,
    "options": {
        "legend": {"calcs": ["lastNotNull"], "displayMode": "list", "placement": "bottom", "showLegend": True},
        "tooltip": {"mode": "multi", "sort": "none"}
    },
    "targets": [
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": "irate(node_disk_read_bytes_total{device=~\"nvme.*|md.*\"}[5m])",
            "legendFormat": "{{device}} Read",
            "refId": "A"
        },
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": "irate(node_disk_written_bytes_total{device=~\"nvme.*|md.*\"}[5m])",
            "legendFormat": "{{device}} Write",
            "refId": "B"
        }
    ],
    "title": "Disk I/O",
    "type": "timeseries"
})
panel_id += 1
y_pos += 8

# Row 4: Detailed storage table
panels.append({
    "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
    "fieldConfig": {
        "defaults": {
            "color": {"mode": "thresholds"},
            "custom": {
                "align": "auto",
                "cellOptions": {"type": "auto"},
                "inspect": False
            },
            "mappings": [],
            "thresholds": {
                "mode": "absolute",
                "steps": [{"color": "green", "value": None}, {"color": "red", "value": 80}]
            }
        },
        "overrides": [
            {
                "matcher": {"id": "byName", "options": "Used %"},
                "properties": [
                    {"id": "unit", "value": "percent"},
                    {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                    {"id": "thresholds", "value": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": None},
                            {"color": "yellow", "value": 70},
                            {"color": "orange", "value": 85},
                            {"color": "red", "value": 95}
                        ]
                    }}
                ]
            },
            {
                "matcher": {"id": "byName", "options": "Total"},
                "properties": [{"id": "unit", "value": "bytes"}]
            },
            {
                "matcher": {"id": "byName", "options": "Used"},
                "properties": [{"id": "unit", "value": "bytes"}]
            },
            {
                "matcher": {"id": "byName", "options": "Available"},
                "properties": [{"id": "unit", "value": "bytes"}]
            }
        ]
    },
    "gridPos": {"h": 8, "w": 24, "x": 0, "y": y_pos},
    "id": panel_id,
    "options": {
        "cellHeight": "sm",
        "footer": {
            "countRows": False,
            "fields": "",
            "reducer": ["sum"],
            "show": False
        },
        "showHeader": True
    },
    "pluginVersion": "11.6.1",
    "targets": [
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": f"node_filesystem_size_bytes{{mountpoint=~\"{'|'.join(MONITORED_MOUNTPOINTS)}\",fstype!=\"tmpfs\"}}",
            "format": "table",
            "instant": True,
            "refId": "A"
        },
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": f"node_filesystem_avail_bytes{{mountpoint=~\"{'|'.join(MONITORED_MOUNTPOINTS)}\",fstype!=\"tmpfs\"}}",
            "format": "table",
            "instant": True,
            "refId": "B"
        },
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": f"node_filesystem_size_bytes{{mountpoint=~\"{'|'.join(MONITORED_MOUNTPOINTS)}\",fstype!=\"tmpfs\"}} - node_filesystem_avail_bytes{{mountpoint=~\"{'|'.join(MONITORED_MOUNTPOINTS)}\",fstype!=\"tmpfs\"}}",
            "format": "table",
            "instant": True,
            "refId": "C"
        },
        {
            "datasource": {"type": "prometheus", "uid": DATASOURCE_UID},
            "expr": f"100 * (1 - (node_filesystem_avail_bytes{{mountpoint=~\"{'|'.join(MONITORED_MOUNTPOINTS)}\",fstype!=\"tmpfs\"}} / node_filesystem_size_bytes{{mountpoint=~\"{'|'.join(MONITORED_MOUNTPOINTS)}\",fstype!=\"tmpfs\"}}))",
            "format": "table",
            "instant": True,
            "refId": "D"
        }
    ],
    "title": "Storage Details",
    "transformations": [
        {
            "id": "merge",
            "options": {}
        },
        {
            "id": "organize",
            "options": {
                "excludeByName": {
                    "Time": True,
                    "__name__": True,
                    "fstype": True,
                    "instance": True,
                    "job": True
                },
                "indexByName": {
                    "mountpoint": 0,
                    "device": 1,
                    "Value #A": 2,
                    "Value #C": 3,
                    "Value #B": 4,
                    "Value #D": 5
                },
                "renameByName": {
                    "Value #A": "Total",
                    "Value #B": "Available",
                    "Value #C": "Used",
                    "Value #D": "Used %",
                    "device": "Device",
                    "mountpoint": "Mount Point"
                }
            }
        },
        {
            "id": "groupBy",
            "options": {
                "fields": {
                    "Available": {
                        "aggregations": ["lastNotNull"],
                        "operation": "aggregate"
                    },
                    "Device": {
                        "aggregations": [],
                        "operation": "groupby"
                    },
                    "Mount Point": {
                        "aggregations": [],
                        "operation": "groupby"
                    },
                    "Total": {
                        "aggregations": ["lastNotNull"],
                        "operation": "aggregate"
                    },
                    "Used": {
                        "aggregations": ["lastNotNull"],
                        "operation": "aggregate"
                    },
                    "Used %": {
                        "aggregations": ["lastNotNull"],
                        "operation": "aggregate"
                    }
                }
            }
        },
        {
            "id": "organize",
            "options": {
                "excludeByName": {},
                "indexByName": {
                    "Mount Point": 0,
                    "Device": 1,
                    "Total (lastNotNull)": 2,
                    "Used (lastNotNull)": 3,
                    "Available (lastNotNull)": 4,
                    "Used % (lastNotNull)": 5
                },
                "renameByName": {
                    "Available (lastNotNull)": "Available",
                    "Total (lastNotNull)": "Total",
                    "Used (lastNotNull)": "Used",
                    "Used % (lastNotNull)": "Used %"
                }
            }
        }
    ],
    "type": "table"
})

dashboard["panels"] = panels

# Write the dashboard
with open('config/dashboard.json', 'w') as f:
    json.dump(dashboard, f, indent=2)

# Write the alert rules with notification policy
alert_rules_config = {
    "apiVersion": 1,
    "groups": [
        {
            "orgId": 1,
            "name": "server_monitoring_alerts",
            "folder": "Server Monitoring",
            "interval": "1m",
            "rules": alert_rules
        }
    ]
}

# Create notification policy that routes all alerts to slack-alerts
notification_policies = {
    "apiVersion": 1,
    "policies": [
        {
            "receiver": "slack-alerts",
            "group_by": ["alertname"],
            "group_wait": "30s",
            "group_interval": "5m",
            "repeat_interval": alerts_config.get("storage_alerts", {}).get("notification_interval", "5m")
        }
    ]
}

with open('config/alert_rules.yml', 'w') as f:
    yaml.dump(alert_rules_config, f, default_flow_style=False, sort_keys=False)

with open('config/notification_policies.yml', 'w') as f:
    yaml.dump(notification_policies, f, default_flow_style=False, sort_keys=False)

print("Dashboard created successfully!")
print(f"Total panels: {len(panels)}")
print(f"Total alert rules: {len(alert_rules)}")
print(f"Monitored drives: {num_drives}")
for drive in MONITORED_DRIVES:
    print(f"  - {drive['label']}: {drive['mountpoint']}")
