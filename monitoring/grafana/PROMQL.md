# PromQL used in the dashboard

The dashboard JSON can't have comments, so the queries are listed here. As required by the
assignment, queries written with AI help have the prompt I used. Plain metric names were written by hand.
Alert rule queries are commented inside `../prometheus/alert_rules.yml`.

| Panel | Query | AI prompt used |
|---|---|---|
| App and node_exporter up | `up{job="caption_app"}`, `up{job="node"}` | hand-written |
| Images per minute | `sum by (mode) (rate(caption_images_processed_total{status="success"}[1m])) * 60` | "PromQL for images per minute from a counter, split by mode" |
| Inference p50/p95/p99 | `histogram_quantile(0.95, sum by (le) (rate(caption_inference_duration_seconds_bucket[1m])))` (same with 0.50 / 0.99) | "PromQL for p95 latency from a histogram over 1 minute" |
| Average request time | `sum by (mode) (rate(caption_request_duration_seconds_sum[1m])) / sum by (mode) (rate(caption_request_duration_seconds_count[1m]))` | "PromQL for average duration from a summary's _sum and _count" |
| Active requests / queue | `sum by (mode) (caption_active_requests)`, `caption_inference_queue_depth` | hand-written |
| Errors by type | `sum by (error_type, mode) (increase(caption_errors_total[1m]))` | "PromQL for errors per minute by error_type" |
| Requests per client | `sum by (client_ip, session_id, browser) (caption_requests_total)` | hand-written |
| Machine CPU % | `100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[30s])))` | "PromQL for total CPU percent from node_exporter" |
| App CPU % | `100 * rate(process_cpu_seconds_total{job="caption_app"}[30s])` | "PromQL for CPU percent of one process" |
| Bulk job shading | `max(caption_active_requests{mode="bulk"})` | hand-written |
| Machine RAM used | `node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes` | "PromQL for used memory from node_exporter" |
| App memory / model weights | `process_resident_memory_bytes{job="caption_app"}`, `caption_model_memory_bytes` | hand-written |

Quick notes:
- `rate(x[1m])` = how fast a counter grew per second over the last minute.
- `histogram_quantile(0.95, ...)` = estimated time under which 95% of images finished, from the bucket counts.
- `_sum / _count` of a summary = average.
