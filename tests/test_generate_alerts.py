"""Tests for generate_alerts.py.

PromQL label matchers are fully anchored, so `mountpoint!~"<re>"` excludes a
mountpoint only when the regex matches the WHOLE string. re.fullmatch reproduces
that semantics, which lets the physical-drive selector be tested without a
running Prometheus.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import generate_alerts  # noqa: E402


@pytest.fixture
def config() -> dict:
    with (REPO_ROOT / "config" / "alerts_config.json").open() as handle:
        return json.load(handle)


def is_monitored(config: dict, fstype: str, mountpoint: str) -> bool:
    """Whether a filesystem is counted as a monitored physical drive."""
    drives = config["physical_drives"]
    excluded = re.fullmatch(drives["mountpoint_exclude_regex"], mountpoint) is not None
    return fstype in drives["fstypes"] and not excluded


class TestPhysicalDriveSelection:
    def test_scratch01_is_monitored(self, config: dict) -> None:
        """Regression: /mnt/scratch01 is a 7.3 TB ext4 drive on jc-compute03 that the
        previous mountpoint regex (^/rootfs$|/rootfs/home$|/rootfs/mnt/data[0-9]+$)
        silently omitted, leaving it unalerted at 84% full."""
        assert is_monitored(config, "ext4", "/mnt/scratch01")

    @pytest.mark.parametrize(
        "mountpoint",
        ["/", "/home", "/mnt/data0", "/mnt/data1", "/mnt/data2", "/mnt/anything_new"],
    )
    def test_local_drives_are_monitored(self, config: dict, mountpoint: str) -> None:
        """Any future local drive is picked up without editing a mountpoint list."""
        assert is_monitored(config, "ext4", mountpoint)

    @pytest.mark.parametrize(
        ("fstype", "mountpoint"),
        [
            ("nfs4", "/datajoint_external"),  # physical drive owned by jc-compute01
            ("nfs4", "/mnt/scratch01"),  # same drive seen from a host that mounts it remotely
            ("cifs", "/mnt/CottonLab"),
            ("cifs", "/autofs/CottonLab/kshah"),
            ("fuse.sshfs", "/mnt/somewhere"),  # unknown type excluded by the allowlist
        ],
    )
    def test_network_filesystems_are_not_monitored(self, config: dict, fstype: str, mountpoint: str) -> None:
        """A drive is ext4 on its owner and nfs4/cifs elsewhere, so an fstype allowlist
        counts each physical drive exactly once across all hosts."""
        assert not is_monitored(config, fstype, mountpoint)

    @pytest.mark.parametrize(
        ("fstype", "mountpoint"),
        [
            ("vfat", "/boot/efi"),
            ("ext4", "/boot"),
            ("ext4", "/var/lib/kubelet/pods/abc/volume"),  # k8s PVCs are ext4
            ("ext4", "/var/lib/docker/overlay2/xyz"),
            ("squashfs", "/snap/core/1234"),
            ("tmpfs", "/run/user/1001"),
        ],
    )
    def test_system_paths_are_not_monitored(self, config: dict, fstype: str, mountpoint: str) -> None:
        assert not is_monitored(config, fstype, mountpoint)


class TestDurationParsing:
    @pytest.mark.parametrize(
        ("duration", "expected"),
        [("30s", 30), ("15m", 900), ("6h", 21600), ("7d", 604800), ("0s", 0)],
    )
    def test_valid_durations(self, duration: str, expected: int) -> None:
        assert generate_alerts.parse_duration_to_seconds(duration) == expected

    @pytest.mark.parametrize("duration", ["5mm", "5m30s", "m5", "5", "", "5y", " 5m"])
    def test_invalid_durations_raise(self, duration: str) -> None:
        """The pattern is anchored: '5mm' previously parsed as 5 minutes."""
        with pytest.raises(ValueError):
            generate_alerts.parse_duration_to_seconds(duration)

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(604800, "7d"), (21600, "6h"), (900, "15m"), (30, "30s"), (90, "90s")],
    )
    def test_roundtrip(self, seconds: int, expected: str) -> None:
        assert generate_alerts.seconds_to_duration(seconds) == expected


class TestValidation:
    def test_accepts_shipped_config(self, config: dict) -> None:
        generate_alerts.validate(config)

    def test_rejects_sustained_shorter_than_group_interval(self, config: dict) -> None:
        config["storage_alerts"]["sustained_duration"] = "10s"  # group interval is 5m
        with pytest.raises(ValueError, match="sustained_duration"):
            generate_alerts.validate(config)

    def test_rejects_out_of_range_percentage(self, config: dict) -> None:
        config["storage_alerts"]["threshold_percent"] = 150
        with pytest.raises(ValueError, match="threshold_percent"):
            generate_alerts.validate(config)

    def test_rejects_confirm_window_not_longer_than_growth_window(self, config: dict) -> None:
        config["storage_projection_alerts"]["confirm_window"] = "7d"
        with pytest.raises(ValueError, match="confirm_window"):
            generate_alerts.validate(config)

    def test_missing_section_raises(self, config: dict) -> None:
        """Fail fast: a missing section must not be silently substituted."""
        del config["memory_alerts"]
        with pytest.raises(KeyError):
            generate_alerts.validate(config)


class TestProjectionAlert:
    @pytest.fixture
    def rules_by_title(self, config: dict) -> dict[str, dict]:
        groups = generate_alerts.build_alert_groups(config)
        return {rule["title"]: rule for group in groups for rule in group["rules"]}

    def test_projection_treats_no_data_as_ok(self, rules_by_title: dict) -> None:
        """fs:physical:days_until_full is absent when a drive is not filling, so
        absence is the healthy case and must not surface as NoData."""
        assert rules_by_title["Storage Projection Alert"]["noDataState"] == "OK"

    def test_watchdog_treats_no_data_as_alerting(self, rules_by_title: dict) -> None:
        """A target that disappears produces no `up` series; that is the failure."""
        assert rules_by_title["Scrape Target Down"]["noDataState"] == "Alerting"

    def test_projection_requires_long_window_agreement(self, config: dict, rules_by_title: dict) -> None:
        """A single bulk copy can satisfy the short window but not both windows."""
        expr = rules_by_title["Storage Projection Alert"]["data"][0]["model"]["expr"]
        confirm = config["storage_projection_alerts"]["confirm_window"]
        assert f"fs:physical:growth_bytes_per_day_{confirm} > 0" in expr

    def test_projection_requires_minimum_usage(self, config: dict, rules_by_title: dict) -> None:
        expr = rules_by_title["Storage Projection Alert"]["data"][0]["model"]["expr"]
        min_used = config["storage_projection_alerts"]["min_used_percent"]
        assert f"fs:physical:used_percent > {min_used}" in expr

    def test_no_predict_linear_anywhere(self, rules_by_title: dict) -> None:
        """predict_linear weighted one bulk delete as heavily as steady growth."""
        for rule in rules_by_title.values():
            assert "predict_linear" not in rule["data"][0]["model"]["expr"]

    def test_storage_summary_names_the_mountpoint(self, rules_by_title: dict) -> None:
        """The old storage summary said only 'Drive is more than 90% full'."""
        assert "$labels.mountpoint" in rules_by_title["Storage Alert"]["annotations"]["summary"]


class TestRecordingRulesCannotSelfPerpetuate:
    """Recording rules emit no staleness markers, so a rule that instant-selects
    another recorded series keeps finding the previous sample inside the 5-minute
    lookback and writes a fresh one from it forever. Observed in practice: after
    mountpoint labels changed, the old /rootfs-prefixed drives kept reporting
    indefinitely and would have alerted on drives that no longer existed.
    """

    @pytest.fixture
    def instant_rules(self, config: dict) -> list[dict]:
        """Rules in the physical_drives group, which are evaluated as instant queries."""
        groups = generate_alerts.build_recording_rules(config)["groups"]
        return next(g for g in groups if g["name"] == "physical_drives")["rules"]

    def test_instant_rules_do_not_read_recorded_series(self, instant_rules: list[dict]) -> None:
        for rule in instant_rules:
            assert "fs:physical:" not in rule["expr"], (
                f"{rule['record']} instant-selects a recorded series, which will "
                "self-perpetuate after the underlying metric goes stale"
            )

    def test_instant_rules_read_raw_metrics(self, instant_rules: list[dict]) -> None:
        for rule in instant_rules:
            assert "node_filesystem_" in rule["expr"]

    def test_projection_rules_only_read_recorded_series_over_ranges(self, config: dict) -> None:
        """Range selectors return only real samples, so reading recorded series there
        is safe and bounded by the range length."""
        groups = generate_alerts.build_recording_rules(config)["groups"]
        rules = next(g for g in groups if g["name"] == "storage_projection")["rules"]

        for rule in rules:
            for reference in re.findall(r"fs:physical:[a-z_0-9]+", rule["expr"]):
                if reference == rule["record"]:
                    continue
                # Every read of a recorded series must be inside a range selector.
                bare = re.search(rf"{re.escape(reference)}(?!\s*\[)", rule["expr"])
                assert bare is None or "growth_bytes_per_day" in reference, (
                    f"{rule['record']} instant-selects {reference}"
                )


class TestGeneratedFilesAreSingleSourced:
    def test_slack_text_does_not_hardcode_thresholds(self, config: dict) -> None:
        """config/alerting.yml must render annotations.summary rather than restate a
        threshold that lives in alerts_config.json."""
        alerting = (REPO_ROOT / "config" / "alerting.yml").read_text()
        body = "\n".join(line for line in alerting.splitlines() if "text:" in line or "title:" in line)

        storage_threshold = str(config["storage_alerts"]["threshold_percent"])
        projection_days = str(config["storage_projection_alerts"]["days_until_full_threshold"])
        assert f"{storage_threshold}%" not in body
        assert f"{projection_days} days" not in body

    def test_recording_rules_define_drive_set_once(self, config: dict) -> None:
        """The fstype allowlist should appear only in recording rules, never in an alert."""
        selector = generate_alerts.physical_drive_selector(config["physical_drives"])
        recording = (REPO_ROOT / "config" / "recording_rules.yml").read_text()
        assert selector in recording

        for group in generate_alerts.build_alert_groups(config):
            for rule in group["rules"]:
                assert "fstype=~" not in rule["data"][0]["model"]["expr"]
