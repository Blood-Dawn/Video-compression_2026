"""The single shot /api/upload has a body cap (pentest finding PT-04)."""

import io

from gui.app import app
from utils import upload_limits


def test_max_content_length_matches_the_chunked_cap():
    assert app.config["MAX_CONTENT_LENGTH"] == upload_limits.max_upload_bytes()


def test_oversized_single_shot_upload_is_rejected_with_413():
    over = upload_limits.max_upload_bytes() + 1
    client = app.test_client()
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"x"), "clip.mp4")},
        content_type="multipart/form-data",
        environ_overrides={"CONTENT_LENGTH": str(over)},
    )
    assert resp.status_code == 413
