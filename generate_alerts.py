#!/usr/bin/env python3
"""
Script to generate Grafana alert rules from configuration.
Both the dashboard and alerts are now fully dynamic!
"""

import json
import os
import yaml

# Datasource UID - defined in config/datasources.yml
DATASOURCE_UID = "prometheus"

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

# Add storage alert if enabled (single alert for all physical drives)
if alerts_config["storage_alerts"]["enabled"]:
    # Single query that matches all physical drives (excludes network mounts and system paths)
    # Matches: /rootfs, /rootfs/home, /rootfs/mnt/data0, /rootfs/mnt/data1
    storage_expr = f"100 * (1 - (node_filesystem_avail_bytes{{mountpoint=~\"^/rootfs$|/rootfs/home$|/rootfs/mnt/data[0-9]+$\",fstype!=\"tmpfs\"}} / node_filesystem_size_bytes{{mountpoint=~\"^/rootfs$|/rootfs/home$|/rootfs/mnt/data[0-9]+$\",fstype!=\"tmpfs\"}}))"

    alert_rules.append(create_unified_alert_rule(
        uid="storage-alert-physical-drives",
        title="Storage Alert - Physical Drives",
        expr=storage_expr,
        summary="Storage alert: drive is above threshold",
        description=f"Physical drive storage has exceeded {alerts_config['storage_alerts']['threshold_percent']}%",
        for_duration=alerts_config["storage_alerts"]["evaluation_interval"],
        threshold=alerts_config["storage_alerts"]["threshold_percent"]
    ))

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
            "group_wait": "10s",
            "group_interval": alerts_config.get("storage_alerts", {}).get("notification_interval", "5m"),
            "repeat_interval": alerts_config.get("storage_alerts", {}).get("notification_interval", "5m")
        }
    ]
}

with open('config/alert_rules.yml', 'w') as f:
    yaml.dump(alert_rules_config, f, default_flow_style=False, sort_keys=False)

with open('config/notification_policies.yml', 'w') as f:
    yaml.dump(notification_policies, f, default_flow_style=False, sort_keys=False)

print("Alert rules generated successfully!")
print(f"Total alert rules: {len(alert_rules)}")
print("Storage alerts: Dynamic (all physical drives automatically monitored)")
