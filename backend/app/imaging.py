"""Shared dataURL -> raw bytes decoding.

Mirrors the parsing approach used by `app/routers/body.py`'s `_decode`
(strip a `data:...;base64,` prefix if present, tolerate a bare base64
string, tolerate embedded/surrounding whitespace such as a line-wrapped
blob, and use `validate=True` so junk input raises rather than silently
producing garbage bytes) -- but stops at raw bytes instead of decoding
into a cv2/numpy image, since not every caller needs an OpenCV array
(e.g. the try-on route just needs bytes to upload to YouCam).

`app/routers/body.py` keeps its own inline copy (it is not touched by
this module) since it additionally needs cv2 image decoding and its own
photo-specific error messages; this module exists so *other* callers
don't have to reinvent or subtly diverge from the same base64 parsing.
"""

import base64
import binascii


class DataUrlError(ValueError):
    """Raised when a dataURL/base64 string can't be decoded to bytes."""


def decode_dataurl(dataurl: str) -> bytes:
    """Decode a `data:...;base64,XXX` dataURL (or a bare base64 string) to bytes.

    Raises DataUrlError on malformed base64. Does not validate that the
    decoded bytes are actually an image -- callers that need that should
    check separately (see app/routers/body.py for the cv2-based version).
    """
    raw = dataurl.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    b64 = "".join(raw.split())  # strip embedded whitespace/newlines

    try:
        return base64.b64decode(b64, validate=True)
    except binascii.Error as e:
        raise DataUrlError(f"invalid base64 data: {e}") from e
