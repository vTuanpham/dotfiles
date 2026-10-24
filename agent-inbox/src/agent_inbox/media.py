"""Bounded raster attachments; no remote fetching or phone-supplied host paths."""

import base64
import binascii
import hashlib
import io
import os
import stat
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from PIL import Image

MAX_BYTES = 8 * 1024 * 1024
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}


@dataclass
class ImageBudget:
    bytes: int = MAX_BYTES
    pixels: int = 25_000_000


def raster(raw, budget=None):
    budget = budget if budget is not None else ImageBudget()
    if not 0 < len(raw) <= budget.bytes:
        raise ValueError("Images must total at most 8 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                pixels = image.width * image.height
                if (image.format not in FORMATS or pixels > budget.pixels
                        or getattr(image, "is_animated", False)):
                    raise ValueError("Unsupported image or dimensions")
                mime = FORMATS[image.format]
                image.verify()
    except (OSError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ValueError("Invalid image") from error
    budget.bytes -= len(raw)
    budget.pixels -= pixels
    return "data:" + mime + ";base64," + base64.b64encode(raw).decode()


def decode_images(value, budget=None):
    if type(value) is not list or len(value) > 4:
        raise ValueError("Choose at most four images")
    budget = budget if budget is not None else ImageBudget()
    images = []
    for url in value:
        if type(url) is not str or len(url) > MAX_BYTES * 4 // 3 + 100:
            raise ValueError("Invalid image data")
        header, separator, encoded = url.partition(",")
        if not separator or header not in {"data:" + mime + ";base64" for mime in FORMATS.values()}:
            raise ValueError("Only embedded raster images are accepted")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Invalid image encoding") from error
        normalized = raster(raw, budget)
        if normalized != url:
            raise ValueError("Image type or encoding does not match")
        images.append(normalized)
    return images


def native_image(part, budget=None):
    """Only the native transcript can nominate a local image; never HTTP input."""
    try:
        budget = budget if budget is not None else ImageBudget()
        if budget.bytes <= 0 or budget.pixels <= 0:
            return None
        if part.get("type") == "image":
            return decode_images([part.get("url")], budget)[0]
        if part.get("type") == "inlineImage":
            encoded = part.get("data")
            if type(encoded) is not str or len(encoded) > budget.bytes * 4 // 3 + 4:
                return None
            raw = base64.b64decode(encoded, validate=True)
            return raster(raw, budget)
        if part.get("type") == "localImage":
            path = Path(part["path"])
            if not path.is_absolute():
                return None
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    return None
                raw = stream.read(budget.bytes + 1)
            return raster(raw, budget)
    except (ValueError, OSError, KeyError, TypeError, binascii.Error):
        return None
    return None


class MediaCache:
    """Private, bounded memory cache; image bytes never become upload files."""

    def __init__(self):
        self.entries = OrderedDict()
        self.size = 0
        self.lock = Lock()

    def publish(self, root, url):
        identifier = hashlib.sha256((root + "\0" + url).encode()).hexdigest()
        with self.lock:
            if identifier not in self.entries:
                header, _, encoded = url.partition(",")
                raw = base64.b64decode(encoded, validate=True)
                self.entries[identifier] = (header[5:].split(";")[0], raw)
                self.size += len(raw)
            self.entries.move_to_end(identifier)
            while self.size > 32 * 1024 * 1024:
                _, (_, raw) = self.entries.popitem(last=False)
                self.size -= len(raw)
        return "/api/image?id=" + identifier

    def get(self, identifier):
        with self.lock:
            value = self.entries.get(identifier)
            if value:
                self.entries.move_to_end(identifier)
            return value
