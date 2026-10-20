"""The single shot /api/upload has a body cap (pentest finding PT-04)."""

import io

from gui.app import app
from gui.routes import ingest_bp


def test_max_content_length_matches_the_chunked_cap():
    assert app.config["MAX_CONTENT_LENGTH"] == ingest_bp._MAX_SIZE


def test_oversized_single_shot_upload_is_rejected_with_413():
    over = ingest_bp._MAX_SIZE + 1
    client = app.test_client()
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"x"), "clip.mp4")},
        content_type="multipart/form-data",
        environ_overrides={"CONTENT_LENGTH": str(over)},
    )
    assert resp.status_code == 413
