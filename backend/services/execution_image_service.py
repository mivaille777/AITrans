"""Serve only decoded static raster images as inline sandbox output."""

import warnings
from io import BytesIO
from urllib.parse import quote

from fastapi import Response
from PIL import Image

from backend.services.sandbox_debug_service import SandboxDebugError


def image_response(filename: str, data: bytes) -> Response:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                format = image.format
                if (
                    format not in {"PNG", "JPEG"}
                    or image.width * image.height > 8_000_000
                ):
                    raise ValueError("Unsupported or oversized image")
                image.load()
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise SandboxDebugError(
            "artifact_not_image",
            "Artifact is not a supported PNG/JPEG image.",
            status_code=422,
        ) from exc
    return Response(
        data,
        media_type="image/png" if format == "PNG" else "image/jpeg",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=60",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
