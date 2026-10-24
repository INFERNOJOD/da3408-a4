# Image captioning app (BLIP on CPU) with prometheus monitoring
# run: streamlit run app/app.py
# UI on :8501, metrics on :8000/metrics

import io
import os
import time
import zipfile
from pathlib import PurePosixPath

import pandas as pd
import streamlit as st
from PIL import Image
from streamlit.runtime.scriptrunner import get_script_run_ctx

from captioner import MODEL_ID, Captioner, ImageDecodeError, decode_image
from metrics import build_metrics

METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
MAX_FILE_BYTES = 25 * 1024 * 1024  # max size of one image inside a zip

st.set_page_config(page_title="CPU Image Captioning", page_icon="🖼️", layout="wide")


# streamlit reruns the whole script on every click, so these are cached
# (otherwise the metrics server would try to start twice and crash)
@st.cache_resource
def get_metrics():
    return build_metrics(METRICS_PORT)


@st.cache_resource(show_spinner="Loading BLIP model on CPU (takes ~30s first time)...")
def get_captioner(_metrics):
    return Captioner(_metrics)


m = get_metrics()
cap = get_captioner(m)


def get_browser(ua):
    ua = ua or ""
    if "Edg/" in ua:
        return "edge"
    if "OPR/" in ua:
        return "opera"
    if "Firefox/" in ua:
        return "firefox"
    if "Chrome/" in ua:
        return "chrome"
    if "Safari/" in ua:
        return "safari"
    return "other"


def get_client():
    # client info used as custom labels on the metrics
    if "client" not in st.session_state:
        ctx = get_script_run_ctx()
        headers = st.context.headers or {}
        st.session_state.client = {
            "session_id": ctx.session_id[:8] if ctx else "unknown",
            "client_ip": st.context.ip_address or "127.0.0.1",  # streamlit gives None for localhost
            "browser": get_browser(headers.get("User-Agent", "")),
        }
        m.init_client(st.session_state.client)
    return st.session_state.client


client = get_client()

# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Settings")
    max_new_tokens = st.slider("Max caption tokens", 10, 50, 30)
    num_beams = st.slider("Beam search width", 1, 5, 1, help="1 = fastest, higher = better but slower")
    max_bulk_images = st.number_input("Max images per ZIP", 1, 1000, 200, step=10)

    st.divider()
    st.subheader("Client labels")
    st.code(f"client_ip  = {client['client_ip']}\n"
            f"session_id = {client['session_id']}\n"
            f"browser    = {client['browser']}", language="text")

    st.divider()
    st.subheader("Model")
    st.caption(f"`{MODEL_ID}`  \n{cap.n_params / 1e6:.0f}M params, CPU only, loaded in {cap.load_seconds:.1f}s")
    st.caption(f"Metrics: http://localhost:{METRICS_PORT}/metrics")


# ---------------- helpers ----------------
def count_request(mode):
    m.requests.labels(mode=mode, **client).inc()


def caption_bytes(data, mode):
    img = decode_image(data)
    res = cap.caption(img, mode, max_new_tokens=max_new_tokens, num_beams=num_beams)
    m.images_processed.labels(mode=mode, status="success").inc()
    return img, res


def mark_failed(mode, error_type):
    m.images_processed.labels(mode=mode, status="failed").inc()
    m.errors.labels(mode=mode, error_type=error_type).inc()


def thumbnail(img):
    t = img.copy()
    t.thumbnail((160, 160))
    buf = io.BytesIO()
    t.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


# ---------------- single mode ----------------
def run_single(data):
    count_request("single")
    m.active_requests.labels(mode="single").inc()
    t0 = time.perf_counter()
    try:
        _, res = caption_bytes(data, "single")
        st.session_state.single_result = {"ok": True, "res": res}
    except ImageDecodeError as e:
        mark_failed("single", "decode_error")
        st.session_state.single_result = {"ok": False, "err": f"Could not read this image ({e})"}
    except Exception as e:
        mark_failed("single", type(e).__name__)
        st.session_state.single_result = {"ok": False, "err": f"Inference failed: {e}"}
    finally:
        m.active_requests.labels(mode="single").dec()
        m.request_seconds.labels(mode="single").observe(time.perf_counter() - t0)


# ---------------- bulk mode ----------------
def scan_zip(zf, limit):
    # returns only the image files, skips folders, mac junk, hidden files, non-images and huge files
    files = []
    for info in zf.infolist():
        p = PurePosixPath(info.filename)
        if info.is_dir() or info.filename.startswith("__MACOSX/") or p.name.startswith("."):
            continue
        if p.suffix.lower() in IMG_EXTS and info.file_size <= MAX_FILE_BYTES:
            files.append(info)
    return files[:limit]


def run_bulk(data, limit):
    count_request("bulk")
    m.active_requests.labels(mode="bulk").inc()
    t0 = time.perf_counter()
    try:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            m.errors.labels(mode="bulk", error_type="bad_zip").inc()
            st.error("That is not a valid ZIP file.")
            return

        files = scan_zip(zf, limit)
        if not files:
            m.errors.labels(mode="bulk", error_type="empty_zip").inc()
            st.warning("No images found in this ZIP.")
            return

        n = len(files)
        progress = st.progress(0.0, text=f"0 / {n} images")
        table = st.empty()
        rows, thumbs, ok = [], [], 0

        # one image at a time so memory stays low
        for i, info in enumerate(files, start=1):
            name = info.filename
            try:
                img, res = caption_bytes(zf.read(info), "bulk")
                ok += 1
                rows.append({"file": name, "caption": res.caption, "status": "ok",
                             "inference_s": round(res.inference_s, 2), "size": f"{res.width}x{res.height}"})
                if len(thumbs) < 12:
                    thumbs.append((thumbnail(img), res.caption))
            except ImageDecodeError:
                mark_failed("bulk", "decode_error")
                rows.append({"file": name, "caption": "", "status": "unreadable image",
                             "inference_s": None, "size": ""})
            except Exception as e:
                mark_failed("bulk", type(e).__name__)
                rows.append({"file": name, "caption": "", "status": f"error: {e}",
                             "inference_s": None, "size": ""})
            progress.progress(i / n, text=f"{i} / {n} images - {name}")
            table.dataframe(pd.DataFrame(rows), hide_index=True)

        elapsed = time.perf_counter() - t0
        table.empty()
        progress.empty()
        st.session_state.bulk_result = {"rows": rows, "thumbs": thumbs, "ok": ok, "n": n, "elapsed": elapsed}
    finally:
        m.active_requests.labels(mode="bulk").dec()
        m.request_seconds.labels(mode="bulk").observe(time.perf_counter() - t0)


# ---------------- UI ----------------
st.title("🖼️ CPU Image Captioning")
st.caption("BLIP base on CPU, monitored with Prometheus + Grafana")

tab_single, tab_bulk = st.tabs(["Single image", "Bulk (ZIP)"])

with tab_single:
    up = st.file_uploader("Upload an image", type=[e.strip(".") for e in IMG_EXTS], key="single_upload")
    if up is not None:
        data = up.getvalue()
        # clear old caption when a new file is uploaded
        if st.session_state.get("single_file_id") != up.file_id:
            st.session_state.single_file_id = up.file_id
            st.session_state.pop("single_result", None)

        left, right = st.columns([3, 2])
        with left:
            try:
                st.image(data, width="stretch")
            except Exception:
                st.info("Preview not available for this file.")
        with right:
            if st.button("Generate caption", type="primary", key="btn_single"):
                with st.spinner("Captioning..."):
                    run_single(data)
            result = st.session_state.get("single_result")
            if result and result["ok"]:
                r = result["res"]
                st.success(f"**{r.caption}**")
                c1, c2, c3 = st.columns(3)
                c1.metric("Inference", f"{r.inference_s:.2f} s")
                c2.metric("Preprocess", f"{r.preprocess_s * 1000:.0f} ms")
                c3.metric("Tokens", r.tokens)
                st.caption(f"{r.width}x{r.height}px, waited {r.queue_wait_s:.2f}s for the model")
            elif result:
                st.error(result["err"])

with tab_bulk:
    st.write("Upload a **ZIP** of images. Non-image / hidden files are skipped, broken images are reported.")
    zup = st.file_uploader("Upload a ZIP file", type=["zip"], key="bulk_upload")
    if zup is not None and st.button("Caption all images", type="primary", key="btn_bulk"):
        run_bulk(zup.getvalue(), int(max_bulk_images))

    br = st.session_state.get("bulk_result")
    if br:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Images", br["n"])
        c2.metric("Captioned", br["ok"])
        c3.metric("Failed", br["n"] - br["ok"])
        c4.metric("Throughput", f"{br['ok'] / br['elapsed']:.2f} img/s" if br["elapsed"] else "-")
        df = pd.DataFrame(br["rows"])
        st.dataframe(df, hide_index=True)
        st.download_button("Download captions (CSV)", df.to_csv(index=False).encode(),
                           file_name="captions.csv", mime="text/csv")
        if br["thumbs"]:
            st.subheader("Preview")
            cols = st.columns(4)
            for i, (thumb, text) in enumerate(br["thumbs"]):
                cols[i % 4].image(thumb, caption=text)
