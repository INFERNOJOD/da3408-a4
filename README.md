# DA3408 Assignment 4 – Monitoring a CPU Image Captioning App

Streamlit app that captions images using **BLIP-base on CPU**, instrumented with `prometheus_client`.
Prometheus scrapes the app and **node_exporter**, alert rules go through Alertmanager, and Grafana shows a dashboard.

- Demo video: _(link)_
- Dashboard recording (5 s refresh): _(link)_

## For TAs: what to check

| Rubric item | Where to look |
|---|---|
| Application logic (single + bulk, no crash on CPU) | `app/app.py`, `app/captioner.py` · screenshots 01, 04–07b |
| Python instrumentation (counters, gauges, histograms, summary, custom labels) | `app/metrics.py` · section "Metrics" below · screenshots 03, 03b, 13 |
| Node exporting (node_exporter + Prometheus scrape config) | `monitoring/prometheus/prometheus.yml` · screenshots 08, 09 |
| Alerting | `monitoring/prometheus/alert_rules.yml`, `monitoring/alertmanager/alertmanager.yml` · screenshots 10–12 |
| Grafana dashboard (JSON export, 7 commandments) | `monitoring/grafana/dashboards/caption_dashboard.json` · screenshots 15–17 |
| PromQL / AI prompts | `monitoring/grafana/PROMQL.md`, comments in `alert_rules.yml` |
| Videos | links at the top of this file |

## Repo structure

```
app/app.py                 Streamlit UI (single image + bulk ZIP)
app/captioner.py           loads BLIP and runs it on CPU
app/metrics.py             all Prometheus metrics, /metrics on port 8000
monitoring/docker-compose.yml        Prometheus + Alertmanager + Grafana
monitoring/prometheus/prometheus.yml scrape config (app + node_exporter)
monitoring/prometheus/alert_rules.yml
monitoring/alertmanager/alertmanager.yml
monitoring/grafana/dashboards/caption_dashboard.json   dashboard export
monitoring/grafana/PROMQL.md         queries used in the dashboard
scripts/make_sample_zip.py  makes test ZIPs
scripts/alert_receiver.py   prints alerts sent by Alertmanager
docs/screenshots/
```

Ports: app UI `8501`, app metrics `8000`, node_exporter `9100`, Prometheus `9090`, Alertmanager `9093`, Grafana `3000`.

I ran everything on an Ubuntu VM (aarch64, 4 vCPU, 7 GB RAM) on my Mac.

## Setup

**1. Python env (CPU-only torch)**
```bash
git clone https://github.com/INFERNOJOD/da3408-a4.git
cd da3408-a4
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -r requirements.txt
python -c "import torch; print('CUDA available:', torch.cuda.is_available())"   # False
```

**2. node_exporter**
```bash
sudo apt install -y prometheus-node-exporter
curl -s localhost:9100/metrics | grep ^node_load1
```

**3. Run the app**
```bash
streamlit run app/app.py
```
Open http://localhost:8501 once in a browser (Streamlit only starts the script, and the metrics
server, when a page is opened). Metrics are at http://localhost:8000/metrics.
The first run downloads the BLIP model (~1 GB).

**4. Prometheus + Alertmanager + Grafana**
```bash
cd monitoring && docker compose up -d && cd ..
```
- Prometheus: http://localhost:9090 (`/targets`, `/alerts`)
- Grafana: http://localhost:3000 (admin / admin). The dashboard is loaded automatically.

**5. (optional) alert receiver and test data**
```bash
python scripts/alert_receiver.py                      # prints FIRING / RESOLVED
python scripts/make_sample_zip.py                     # sample_data/photos_20.zip
python scripts/make_sample_zip.py -n 10 --edge-cases  # ZIP with junk + corrupt files
```

## The app

- **Single mode:** upload one image, get a caption plus inference time.
- **Bulk mode:** upload a ZIP, every image gets captioned one by one, with a results table and CSV download.
- Non-image files and `__MACOSX` / hidden files in a ZIP are skipped; corrupt images and bad ZIPs are shown as errors and counted. The app doesn't crash.
- Only one image runs through the model at a time (a lock), so two users queue instead of fighting over the CPU.

## Metrics

All app metrics start with `caption_` and are served on port 8000 (separate from the UI).

| Type | Metric | Labels | What it measures |
|---|---|---|---|
| Counter | `caption_images_processed_total` | mode, status | images processed, single vs bulk, success / failed |
| Counter | `caption_requests_total` | mode, client_ip, session_id, browser | requests per client (custom labels) |
| Counter | `caption_errors_total` | mode, error_type | errors (decode_error, bad_zip, empty_zip) |
| Gauge | `caption_active_requests` | mode | requests in progress |
| Gauge | `caption_inference_queue_depth` | – | images waiting for the model |
| Gauge | `caption_model_memory_bytes` | – | memory used by the model weights |
| Histogram | `caption_inference_duration_seconds` | mode | inference time per image |
| Summary | `caption_request_duration_seconds` | mode | end-to-end request time |

The default `process_*` metrics (app CPU and memory) are exported too.

A summary gives `_sum` and `_count` (average = sum / count); `_total` is the counter suffix.

## Prometheus and alerts

`prometheus.yml` scrapes the app (`localhost:8000`) and node_exporter (`localhost:9100`) every 5 s.

Alert rules: app down, node_exporter down, p95 inference > 3 s, more than 20% of images failing,
model queue > 2 for 1 min, CPU > 90%, RAM < 10% free, disk < 10% free. Alertmanager sends them to
`scripts/alert_receiver.py`.

I tested it by stopping the app: the target went DOWN, `CaptionAppDown` fired, and it resolved after
restarting (screenshots 11a–11d). `LowDiskSpace` also fired for real once when my VM disk got to 93% (screenshot 12).

## Grafana dashboard

`monitoring/grafana/dashboards/caption_dashboard.json`, 9 panels, top to bottom from high level to low level:

1. **Health:** app and node_exporter up / down
2. **Throughput & latency:** images/min, inference p50/p95/p99, average request time, active requests and queue
3. **Errors and clients:** errors by type, requests per client IP / session / browser
4. **System resources:** CPU and memory (grey shading while a bulk job runs, to match app load with hardware usage)

Colour-blind safe colours, dashed lines and point markers so lines can be told apart in grayscale,
named axes with units and scale (linear / log2), legends, titles, and a short description on every panel (ⓘ).

All 8 app metrics are shown on the dashboard. They are also available at http://localhost:8000/metrics.

## Screenshots

| | |
|---|---|
| [01](docs/screenshots/01_env_cpu_only_torch_blip.png) | CPU-only torch, BLIP downloaded |
| [02](docs/screenshots/02_app_home_client_labels.png) | app home with client labels |
| [03](docs/screenshots/03_metrics_endpoint.png), [03b](docs/screenshots/03b_metrics_histogram_summary.png) | /metrics on port 8000 |
| [04](docs/screenshots/04_single_mode_caption.png), [05](docs/screenshots/05_single_corrupt_image_handled.png) | single mode, corrupt image handled |
| [06](docs/screenshots/06_bulk_20_results_table.png), [06b](docs/screenshots/06b_bulk_20_preview_thumbs.png) | bulk mode, 20 images |
| [07](docs/screenshots/07_bulk_edge_cases_summary.png), [07b](docs/screenshots/07b_bulk_edge_cases_unreadable_row.png) | ZIP with junk / corrupt files |
| [08](docs/screenshots/08_node_exporter_service.png) | node_exporter running |
| [09](docs/screenshots/09_prometheus_targets_up.png), [10](docs/screenshots/10_prometheus_alert_rules.png) | Prometheus targets and alert rules |
| [11a](docs/screenshots/11a_target_down_app_stopped.png)–[11d](docs/screenshots/11d_alert_receiver_resolved.png) | alert firing and resolving |
| [12](docs/screenshots/12_real_alert_low_disk_space.png) | real low disk alert (taken with an earlier version of the dashboard) |
| [13](docs/screenshots/13_second_client_mac_chrome.png) | second client from my Mac |
| [14](docs/screenshots/14_contention_mac_waited_for_model.png), [14b](docs/screenshots/14b_contention_bulk_throughput_drop.png) | two clients at once |
| [15](docs/screenshots/15_dashboard_overview.png)–[17](docs/screenshots/17_dash_errors_clients_system.png) | Grafana dashboard |

## AI disclosure

I used Claude (Anthropic's AI assistant) while doing this assignment, as allowed in section 4. I used it
for help writing the app and metrics code, the Prometheus / Alertmanager / Grafana configs, the
PromQL queries and this README. I set everything up, ran and tested it on my own VM, and took all the
screenshots myself.

The PromQL written with AI help has the prompt I used next to it: as `# AI prompt:` comments in
`monitoring/prometheus/alert_rules.yml`, and in `monitoring/grafana/PROMQL.md` for the dashboard queries.
