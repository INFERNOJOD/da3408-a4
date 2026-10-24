# Prometheus metrics for the captioning app
# served on a separate port (8000 by default) at /metrics

from prometheus_client import (
    CollectorRegistry, Counter, Gauge, GCCollector, Histogram,
    PlatformCollector, ProcessCollector, Summary, start_http_server,
)

NS = "caption"

# CPU inference is slow so latency buckets go up to 30s
LATENCY_BUCKETS = (0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 13, 20, 30)


class AppMetrics:
    def __init__(self, registry):
        r = registry

        # counters
        self.images_processed = Counter("images_processed", "Images processed, single vs bulk",
                                        ["mode", "status"], namespace=NS, registry=r)
        self.requests = Counter("requests", "Caption requests (button clicks) per client",
                                ["mode", "client_ip", "session_id", "browser"], namespace=NS, registry=r)
        self.errors = Counter("errors", "Errors by type",
                              ["mode", "error_type"], namespace=NS, registry=r)

        # gauges
        self.active_requests = Gauge("active_requests", "Requests in progress",
                                     ["mode"], namespace=NS, registry=r)
        self.inference_queue_depth = Gauge("inference_queue_depth", "Images waiting for the model",
                                           namespace=NS, registry=r)
        self.model_memory_bytes = Gauge("model_memory_bytes", "Memory used by model weights",
                                        namespace=NS, registry=r)

        # histogram
        self.inference_seconds = Histogram("inference_duration_seconds", "Model inference time per image",
                                           ["mode"], buckets=LATENCY_BUCKETS, namespace=NS, registry=r)

        # summary
        self.request_seconds = Summary("request_duration_seconds", "End to end request time",
                                       ["mode"], namespace=NS, registry=r)

        # start known label combos at 0 so the first event shows up in rate() and panels show 0 not "No data"
        for mode in ("single", "bulk"):
            for status in ("success", "failed"):
                self.images_processed.labels(mode=mode, status=status)
            self.active_requests.labels(mode=mode)
            self.inference_seconds.labels(mode=mode)
            self.request_seconds.labels(mode=mode)
        for mode, err in (("single", "decode_error"), ("bulk", "decode_error"),
                          ("bulk", "bad_zip"), ("bulk", "empty_zip")):
            self.errors.labels(mode=mode, error_type=err)

    def init_client(self, client):
        # same for a new browser session
        for mode in ("single", "bulk"):
            self.requests.labels(mode=mode, **client)


def build_metrics(port, addr="0.0.0.0"):
    registry = CollectorRegistry()
    # default process_* (cpu, memory) and python_* metrics
    ProcessCollector(registry=registry)
    PlatformCollector(registry=registry)
    GCCollector(registry=registry)
    m = AppMetrics(registry)
    start_http_server(port, addr=addr, registry=registry)
    return m
