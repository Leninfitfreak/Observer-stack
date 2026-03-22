# DASHBOARD_QUERY_VALIDATION_REPORT

## Scope

This report records per-widget live query validation against `/api/v5/query_range` before dashboards are written to SigNoz.

## Dashboards Analyzed

- `LeninKart Platform Overview`
- `LeninKart Product Service Overview`
- `LeninKart Order Service Overview`
- `LeninKart Kafka Overview`
- `LeninKart Frontend Overview`

## Per-Dashboard Results

### LeninKart Platform Overview

- widgets kept: `4`
- widgets removed: `0`
- `Product Request Rate`: status=`safe`, metric=`signoz_calls_total`, meta_duration_ms=`461`, wall_time_ms=`4875.43`, rows_scanned=`25275`, bytes_scanned=`43848`, series_count=`0`, reasons=`none`
- `Order Request Rate`: status=`safe`, metric=`signoz_calls_total`, meta_duration_ms=`1204`, wall_time_ms=`3422.32`, rows_scanned=`25275`, bytes_scanned=`43848`, series_count=`0`, reasons=`none`
- `Kafka Messages In Rate`: status=`safe`, metric=`kafka.broker.topic.messages_in.rate`, meta_duration_ms=`214`, wall_time_ms=`765.25`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`none`
- `Frontend CPU Utilization`: status=`safe`, metric=`container.cpu.utilization`, meta_duration_ms=`934`, wall_time_ms=`6777.39`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`none`

### LeninKart Product Service Overview

- widgets kept: `2`
- widgets removed: `1`
- `Request Rate`: status=`safe`, metric=`signoz_calls_total`, meta_duration_ms=`150`, wall_time_ms=`2746.39`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`none`
- `Database Call Rate`: status=`safe`, metric=`signoz_db_latency_count`, meta_duration_ms=`228`, wall_time_ms=`6023.35`, rows_scanned=`25275`, bytes_scanned=`43848`, series_count=`0`, reasons=`none`
- `External Call Rate`: status=`unsafe`, metric=`signoz_external_call_latency_count`, meta_duration_ms=`219`, wall_time_ms=`9231.71`, rows_scanned=`25275`, bytes_scanned=`43848`, series_count=`0`, reasons=`wall_time_ms>8000`

### LeninKart Order Service Overview

- widgets kept: `2`
- widgets removed: `1`
- `Request Rate`: status=`safe`, metric=`signoz_calls_total`, meta_duration_ms=`260`, wall_time_ms=`1750.99`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`none`
- `Database Call Rate`: status=`unsafe`, metric=`signoz_db_latency_count`, meta_duration_ms=`329`, wall_time_ms=`9298.75`, rows_scanned=`25275`, bytes_scanned=`43848`, series_count=`0`, reasons=`wall_time_ms>8000`
- `External Call Rate`: status=`safe`, metric=`signoz_external_call_latency_count`, meta_duration_ms=`388`, wall_time_ms=`4085.8`, rows_scanned=`25275`, bytes_scanned=`43848`, series_count=`0`, reasons=`none`

### LeninKart Kafka Overview

- widgets kept: `1`
- widgets removed: `2`
- `Total Consumer Lag`: status=`unsafe`, metric=`kafka.consumer_group.lag`, meta_duration_ms=`885`, wall_time_ms=`8686.98`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`wall_time_ms>8000`
- `Messages Consumed by Group`: status=`unsafe`, metric=`kafka.consumer.records_consumed_rate`, meta_duration_ms=`5145`, wall_time_ms=`5083.13`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`meta_duration_ms>2500`
- `Messages In Rate`: status=`safe`, metric=`kafka.broker.topic.messages_in.rate`, meta_duration_ms=`293`, wall_time_ms=`2287.08`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`none`

### LeninKart Frontend Overview

- widgets kept: `2`
- widgets removed: `1`
- `CPU Utilization`: status=`unsafe`, metric=`container.cpu.utilization`, meta_duration_ms=`860`, wall_time_ms=`8190.38`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`wall_time_ms>8000`
- `Memory Working Set`: status=`safe`, metric=`container.memory.working_set`, meta_duration_ms=`327`, wall_time_ms=`7764.35`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`none`
- `Memory RSS`: status=`safe`, metric=`container.memory.rss`, meta_duration_ms=`849`, wall_time_ms=`4112.96`, rows_scanned=`0`, bytes_scanned=`0`, series_count=`0`, reasons=`none`

