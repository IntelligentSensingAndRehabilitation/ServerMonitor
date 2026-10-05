# One-time migrations

## 2026-08-17 mountpoint relabel

Adding `--path.rootfs=/rootfs` to node-exporter stripped the `/rootfs` prefix from
mountpoint labels, so `/rootfs/home` became `/home`. Dropping `instance` from the
recording-rule grouping changed series identity again. Both together orphaned 30 days
of storage history: the new `fs:physical:*` series started from zero, and the
projections needed 8 and 29 days before they could say anything.

`rules_pre.yml` and `rules_post.yml` rebuild `fs:physical:*` across the whole history.
They are split by label era on purpose: around the relabel, Prometheus's 5-minute
lookback returns both `/rootfs/home` and `/home` at the same timestamp, and
`label_replace` mapping them onto one labelset is an error.

Run each against a live Prometheus, then move the blocks into its data directory:

```bash
for f in rules_pre rules_post; do
  docker run --rm --user 0 --network <monitoring-net> \
    -v "$PWD/migrations":/r:ro -v /some/out:/out \
    --entrypoint promtool prom/prometheus:v3.8.0 \
    tsdb create-blocks-from rules --quiet \
      --start 2026-07-18T18:00:00Z \
      --url http://prometheus-c:9090 --output-dir /out "/r/$f.yml"
done

docker compose stop prometheus
docker run --rm --user 0 -v /some/out:/src:ro -v prometheus_data:/dst alpine \
  sh -c 'cp -a /src/. /dst/ && chown -R 65534:65534 /dst'
docker compose start prometheus
```

Notes:

- Omit `--end` so it stops 3 hours short of now and cannot collide with the live head
  block. Live rules cover the remainder.
- The importer writes fixed 2-hour blocks, one set per rule, so 34 days produced ~1640
  blocks. Prometheus compacts them down (to 11 here) within a couple of minutes, and
  logs `Overlapping blocks found` while doing it. That is expected.
- Back up the TSDB volume first.
- Series recorded before the grouping change keep their `instance` label and remain
  alongside the converted ones until they age out of retention. They show up as a
  duplicate line on range panels for that window.

### Second pass: the projection rules

`rules_pre.yml` and `rules_post.yml` rebuild only the four base series. The growth and
`days_until_full` rules are derived, so they start from zero and leave the storage-rate
panel empty. Once the base series are in the TSDB, `rules_projection.yml` rebuilds those
too, reading the recorded `fs:physical:used_bytes` and `avail_bytes`:

```bash
docker run --rm --user 0 --network <monitoring-net> \
  -v "$PWD/migrations":/r:ro -v /some/out2:/out \
  --entrypoint promtool prom/prometheus:v3.8.0 \
  tsdb create-blocks-from rules --quiet \
    --start <data-start + 8 days> \
    --url http://prometheus-c:9090 --output-dir /out /r/rules_projection.yml
```

Start at least 8 days after the earliest data, or the 7-day offset window is empty.
`days_until_full` inlines its growth term rather than reading the recorded growth
series, so one pass covers all three rules. Expect `growth_bytes_per_day_28d` to begin
28 days after the earliest sample, and `days_until_full` to be sparse by design: it
exists only while a drive is actually filling.
