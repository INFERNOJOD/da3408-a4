# BLIP captioning model, CPU only

import io
import os
import threading
import time
from dataclasses import dataclass

import torch
from PIL import Image, ImageOps, UnidentifiedImageError
from transformers import BlipForConditionalGeneration, BlipProcessor

MODEL_ID = os.getenv("CAPTION_MODEL_ID", "Salesforce/blip-image-captioning-base")
Image.MAX_IMAGE_PIXELS = 60_000_000  # avoid decompression bombs


class ImageDecodeError(Exception):
    pass


@dataclass
class CaptionResult:
    caption: str
    preprocess_s: float
    inference_s: float
    queue_wait_s: float
    tokens: int
    width: int
    height: int


def decode_image(data):
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img)  # fix phone photo rotation
        return img.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as e:
        raise ImageDecodeError(f"{type(e).__name__}: {e}") from e


class Captioner:
    def __init__(self, metrics, threads=None):
        self.m = metrics
        # only one image goes through the model at a time, otherwise 4 cores get overloaded
        self.lock = threading.Lock()

        threads = threads or int(os.getenv("TORCH_THREADS", os.cpu_count() or 4))
        torch.set_num_threads(threads)

        t0 = time.perf_counter()
        self.processor = BlipProcessor.from_pretrained(MODEL_ID)
        self.model = BlipForConditionalGeneration.from_pretrained(MODEL_ID)
        self.model.eval()
        self.load_seconds = time.perf_counter() - t0

        self.n_params = sum(p.numel() for p in self.model.parameters())
        n_bytes = sum(p.numel() * p.element_size() for p in self.model.parameters())
        self.m.model_memory_bytes.set(n_bytes)

    def caption(self, image, mode, max_new_tokens=30, num_beams=1):
        m = self.m

        t0 = time.perf_counter()
        inputs = self.processor(images=image, return_tensors="pt")
        preprocess_s = time.perf_counter() - t0

        # wait for the model
        m.inference_queue_depth.inc()
        t_wait = time.perf_counter()
        with self.lock:
            wait_s = time.perf_counter() - t_wait
            m.inference_queue_depth.dec()

            t1 = time.perf_counter()
            with torch.inference_mode():
                out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, num_beams=num_beams,
                                          no_repeat_ngram_size=3, repetition_penalty=1.3)
            inference_s = time.perf_counter() - t1

        m.inference_seconds.labels(mode=mode).observe(inference_s)

        caption = self.processor.decode(out[0], skip_special_tokens=True).strip()
        tokens = int(out.shape[-1])

        return CaptionResult(caption, preprocess_s, inference_s, wait_s, tokens, image.width, image.height)
