"""
src/gui/routes/encryption_bp.py

AES-256 key generation and per-segment encrypt / decrypt.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

from pathlib import Path
from flask import Blueprint, jsonify, request, Response

try:
    from gui.state import (_state_lock, _status)
    from gui.logging_setup import log
    from gui.services.path_safety import _safe_filename
    from gui.services.cloud_detection import _detect_onedrive_root
    from gui.services.db_helpers import _get_db_path
    from utils.db import (get_connection)
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status)
    from src.gui.logging_setup import log
    from src.gui.services.path_safety import _safe_filename
    from src.gui.services.cloud_detection import _detect_onedrive_root
    from src.gui.services.db_helpers import _get_db_path
    from src.utils.db import (get_connection)

# Optional backend: keygen/encrypt/decrypt return 503 when cryptography is missing.
try:
    from utils.encryption import (
        decrypt_file as _decrypt_file,
        encrypt_file as _encrypt_file,
        generate_key as _generate_key,
    )
    _CRYPTO_AVAILABLE = True
except ModuleNotFoundError:
    try:
        from src.utils.encryption import (
            decrypt_file as _decrypt_file,
            encrypt_file as _encrypt_file,
            generate_key as _generate_key,
        )
        _CRYPTO_AVAILABLE = True
    except ImportError:
        _CRYPTO_AVAILABLE = False
        _decrypt_file = _encrypt_file = _generate_key = None
except ImportError:
    _CRYPTO_AVAILABLE = False
    _decrypt_file = _encrypt_file = _generate_key = None

# Repo root (.../src/gui/routes/<bp>_bp.py -> parents[3]).
_ROOT = Path(__file__).resolve().parents[3]

# Read size for streaming a decrypted clip back to the browser.
_STREAM_CHUNK = 64 * 1024
_INLINE_MAX_BYTES = 64 * 1024 * 1024

encryption_bp = Blueprint("encryption", __name__)

@encryption_bp.route("/api/keygen", methods=["POST"])
def api_keygen():
    """Generate a fresh 32-byte AES-256 key and save it as <output_dir>/camera.key.

    POST body (JSON, optional):
      { "filename": "camera.key" }   - override the output filename

    Returns:
      { "path": "C:/...outputs/camera.key", "size": 32 }
    """
    if not _CRYPTO_AVAILABLE:
        return jsonify({"error": "cryptography package not installed"}), 503

    body     = request.get_json(silent=True) or {}
    raw_name = body.get("filename") or "camera.key"

    # Sanitize filename - strip directories, allow only safe characters
    try:
        safe_name = _safe_filename(raw_name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not safe_name.endswith(".key"):
        safe_name = safe_name + ".key"

    with _state_lock:
        cfg = _status.get("config", {})
    out_dir = Path(cfg.get("output_dir", str(_ROOT / "outputs"))).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    key_path = out_dir / safe_name

    key = _generate_key()
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)   # owner-only; a no-op on Windows
    except OSError:
        pass
    log.info("Generated new AES-256 key file: %s", key_path)
    return jsonify({"path": str(key_path), "size": len(key)})


def _safe_segment_roots() -> list[Path]:
    """Directories the user may encrypt/decrypt files from (and descendants).

    Includes the configured output_dir (default <project>/outputs/), the
    project root (so data/samples/ and data/raw/ work), and the auto-detected
    OneDrive root when present.

    Author: Bloodawn (KheivenD), 2026-05-03 (decrypt path fix).
    """
    roots: list[Path] = []
    with _state_lock:
        cfg = _status.get("config", {})
    try:
        roots.append(Path(cfg.get("output_dir", str(_ROOT / "outputs"))).resolve())
    except (OSError, ValueError, RuntimeError, TypeError):
        pass
    roots.append(_ROOT)  # already resolved
    # Detection probes the registry and filesystem; a failure there must not
    # block decrypting a local file.
    try:
        od_root, _ = _detect_onedrive_root(prefer_business=True)
        if od_root is not None:
            roots.append(od_root.resolve())
    except Exception as exc:  # noqa: BLE001
        log.debug("OneDrive root detection failed: %s", exc)
    # De-dup by string, preserving order.
    return list({str(r): r for r in roots if str(r)}.values())


def _path_under_any(p: Path, roots: list[Path]) -> bool:
    """True if `p` equals or is under any of `roots` (after resolve)."""
    try:
        p_res = p.resolve()
    except OSError:
        return False
    return any(p_res == r or r in p_res.parents for r in roots)


@encryption_bp.route("/api/decrypt", methods=["POST"])
def api_decrypt():
    """Decrypt an .enc segment and stream the plaintext back to the browser.

    POST body (JSON):
      {
        "file_path": "/absolute/path/to/segment.mp4.enc",
        "password":  "s3cr3t",        // mutually exclusive with key_file
        "key_file":  "/path/to/camera.key"  // mutually exclusive with password
      }

    The plaintext is kept at <enc_dir>/Decrypted/<name> and also streamed to
    the client; its path is returned in the X-Decrypted-Path header. The .enc
    file is NOT deleted.

    Returns the video file as application/octet-stream (or video/mp4) with
    Content-Disposition: attachment so the browser saves/plays it.
    """
    if not _CRYPTO_AVAILABLE:
        return jsonify({"error": "cryptography package not installed"}), 503

    body      = request.get_json(silent=True) or {}
    enc_path_raw = body.get("file_path", "").strip()
    password  = body.get("password") or None
    key_file  = body.get("key_file") or None

    if not enc_path_raw:
        return jsonify({"error": "file_path is required"}), 400
    if not password and not key_file:
        return jsonify({"error": "Either password or key_file is required"}), 400

    # Security: file_path must sit under output_dir, the project root, or the
    # OneDrive root (see _safe_segment_roots).
    safe_roots = _safe_segment_roots()
    enc_path = Path(enc_path_raw).resolve()
    if not _path_under_any(enc_path, safe_roots):
        log.warning("api_decrypt: rejected path outside trusted roots: %s "
                    "(roots=%s)", enc_path, [str(r) for r in safe_roots])
        return jsonify({
            "error": "file_path is outside the trusted folders. Allowed: "
                     + " | ".join(str(r) for r in safe_roots)
        }), 403

    if not enc_path.exists():
        return jsonify({"error": f"File not found: {enc_path.name}"}), 404   # name only, no full path

    if enc_path.suffix.lower() != ".enc":
        return jsonify({"error": "Only .enc files can be decrypted via this endpoint"}), 400

    # Security: same trust check for the key file.
    raw_key = None
    if key_file:
        kf_path = Path(key_file).resolve()
        if not _path_under_any(kf_path, safe_roots):
            log.warning("api_decrypt: rejected key_file outside trusted roots: %s", kf_path)
            return jsonify({"error": "key_file is outside the trusted folders"}), 403
        try:
            with open(kf_path, "rb") as kf:
                raw_key = kf.read()
        except OSError as e:
            return jsonify({"error": f"Cannot read key file: {e}"}), 400

    # The plaintext is kept in <enc_dir>/Decrypted/ as well as streamed: a
    # browser download never says where the file went, and the metrics player
    # replays the kept copy through /api/media.
    # Author: Bloodawn (KheivenD), 2026-05-03 (decrypt destination fix).
    dec_dir = enc_path.parent / "Decrypted"
    try:
        dec_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return jsonify({"error": f"Could not create Decrypted/ folder: {e}"}), 500

    plain_name = enc_path.name[:-4] if enc_path.name.lower().endswith(".enc") else enc_path.stem
    out_path = dec_dir / plain_name

    # Re-decrypting replaces any stale copy; the .enc is the source of truth.
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass

    try:
        out = _decrypt_file(
            enc_path,
            password=password,
            key=raw_key,
            output_path=out_path,
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Decryption failed: {e}"}), 500

    # Small clips are read at once so no file handle outlives the request
    # (an open handle blocks a re-decrypt replace on Windows). Larger clips
    # stream in chunks, opening the file lazily and stopping at the size sent.
    try:
        size = out.stat().st_size
        body = out.read_bytes() if size <= _INLINE_MAX_BYTES else None
    except OSError as e:
        return jsonify({"error": f"Could not read decrypted file: {e}"}), 500

    def _stream():
        remaining = size
        with open(out, "rb") as fh:
            while remaining > 0:
                chunk = fh.read(min(_STREAM_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    stem = enc_path.stem
    log.info("Decrypted %s -> %s (%d KB)", enc_path.name, out, size // 1024)
    return Response(
        body if body is not None else _stream(),
        mimetype="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}"',
            "Content-Length": str(size),
            "X-Decrypted-Path": str(out),
        },
    )


@encryption_bp.route("/api/encrypt", methods=["POST"])
def api_encrypt():
    """Encrypt a plaintext segment to a SIBLING ``Encrypted/`` folder.

    POST body (JSON):
      {
        "file_path": "/absolute/path/to/segment.mp4",
        "password":  "s3cr3t",              // mutually exclusive with key_file
        "key_file":  "/path/to/camera.key"  // mutually exclusive with password
      }

    The original .mp4 is preserved, because encrypting in place meant a
    mistyped password permanently lost the recording. Steps:

      1. Create ``<src_dir>/Encrypted/``  (mkdir -p)
      2. Encrypt to ``<src_dir>/Encrypted/<segment>.mp4.enc``
      3. Leave the original .mp4 untouched
      4. Add a NEW DB row pointing at the .enc (so the metrics table
         shows both the unencrypted clip and its locked copy) instead
         of replacing the original row

    Returns:
      { "enc_path": "...", "size_kb": <int>, "original_kept": True }
    """
    if not _CRYPTO_AVAILABLE:
        return jsonify({"error": "cryptography package not installed. "
                                  "Run: uv sync   (or: pip install cryptography)"}), 503

    body         = request.get_json(silent=True) or {}
    raw_path     = body.get("file_path", "").strip()
    password     = body.get("password") or None
    key_file     = body.get("key_file") or None

    if not raw_path:
        return jsonify({"error": "file_path is required"}), 400
    if not password and not key_file:
        return jsonify({"error": "Either password or key_file is required"}), 400

    src_path = Path(raw_path).resolve()

    # Same trust check as decrypt: only files inside the trusted roots.
    safe_roots = _safe_segment_roots()
    if not _path_under_any(src_path, safe_roots):
        log.warning("api_encrypt: rejected path outside trusted roots: %s", src_path)
        return jsonify({
            "error": "file_path is outside the trusted folders. Allowed: "
                     + " | ".join(str(r) for r in safe_roots)
        }), 403

    if not src_path.exists():
        return jsonify({"error": f"File not found: {src_path.name}"}), 404

    if src_path.suffix.lower() == ".enc":
        return jsonify({"error": "File is already encrypted (.enc)"}), 400

    raw_key = None
    if key_file:
        kf_path = Path(key_file).resolve()
        # SEC-005: confine the key file to the trusted roots, exactly as the
        # decrypt route does. Without this, encrypt would read an arbitrary file
        # off disk as key material (inconsistent with decrypt).
        if not _path_under_any(kf_path, safe_roots):
            log.warning("api_encrypt: rejected key_file outside trusted roots: %s", kf_path)
            return jsonify({"error": "key_file is outside the trusted folders"}), 403
        try:
            raw_key = kf_path.read_bytes()
        except OSError as e:
            return jsonify({"error": f"Cannot read key file: {e}"}), 400

    # Destination: the encrypted-output folder chosen in Setup, else a sibling
    # "Encrypted/" next to the source. A cloud destination is only ever used
    # when the user chose it.
    with _state_lock:
        chosen_enc = (_status.get("config", {}).get("encrypted_dir") or "").strip()
    if chosen_enc:
        enc_subdir = Path(chosen_enc)
    else:
        enc_subdir = src_path.parent / "Encrypted"

    # SEC-006: never write the .enc to an arbitrary path. If the configured
    # encrypted_dir escapes the trusted roots, fall back to a sibling Encrypted/
    # next to the (already-confined) source.
    if not _path_under_any(enc_subdir.resolve(), safe_roots):
        log.warning("api_encrypt: encrypted_dir %s is outside the trusted roots; "
                    "writing to a sibling Encrypted/ instead", enc_subdir)
        enc_subdir = src_path.parent / "Encrypted"

    try:
        enc_subdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return jsonify({"error": f"Could not create Encrypted/ folder: {e}"}), 500

    target_enc = enc_subdir / (src_path.name + ".enc")

    try:
        enc_path = _encrypt_file(
            src_path,
            password=password,
            key=raw_key,
            delete_original=False,    # keep the source mp4
            output_path=target_enc,
        )
    except TypeError:
        # Older _encrypt_file signature without output_path. Fall back to
        # in-place encrypt + move-and-restore-original.
        log.warning("api_encrypt: _encrypt_file lacks output_path; using fallback")
        try:
            tmp_enc = _encrypt_file(
                src_path,
                password=password,
                key=raw_key,
                delete_original=False,
            )
            # Move into Encrypted/ (it landed next to src by default)
            enc_path = Path(tmp_enc).rename(target_enc)
        except (ValueError, FileNotFoundError) as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"Encryption failed: {e}"}), 500
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Encryption failed: {e}"}), 500

    # Add a row for the .enc copy; the original row stays. Only when a
    # pipeline has already created the database: opening a missing path makes
    # sqlite create an empty metadata.db, which turns the storage and search
    # routes into 500s ("no such table: segments").
    # Author: Bloodawn (KheivenD), 2026-09-24 (cleanup sweep).
    try:
        db_path = _get_db_path()
        if not db_path.exists():
            raise FileNotFoundError(f"no metadata database at {db_path} yet")
        with get_connection(str(db_path)) as conn:
            # Clone the original row's metadata when it exists.
            row = conn.execute(
                "SELECT timestamp, camera_id, target_detected, roi_count, "
                "       file_size, duration, object_type, "
                "       COALESCE(avg_sharpness, 0), sharpness_label, "
                "       COALESCE(object_classes, '[]'), dominant_color, "
                "       COALESCE(scene_type, 'unknown'), time_of_day, "
                "       COALESCE(vehicle_count, 0), COALESCE(person_count, 0) "
                "FROM segments WHERE file_path = ?",
                (str(src_path),),
            ).fetchone()
            enc_size = enc_path.stat().st_size
            if row:
                conn.execute(
                    "INSERT INTO segments (timestamp, camera_id, target_detected, "
                    "  roi_count, file_size, duration, file_path, object_type, "
                    "  avg_sharpness, sharpness_label, object_classes, "
                    "  dominant_color, scene_type, time_of_day, "
                    "  vehicle_count, person_count) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row[0], row[1], row[2], row[3], enc_size, row[5],
                     str(enc_path), row[6], row[7], row[8], row[9],
                     row[10], row[11], row[12], row[13], row[14]),
                )
            else:
                # File came from outside the pipeline: minimal row.
                conn.execute(
                    "INSERT INTO segments (timestamp, camera_id, target_detected, "
                    "  roi_count, file_size, duration, file_path, object_type) "
                    "VALUES (datetime('now'), ?, 0, 0, ?, 0, ?, 'unknown')",
                    (src_path.stem, enc_size, str(enc_path)),
                )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("api_encrypt: DB update failed: %s", e)
        # The file was encrypted, so the request still succeeds.

    size_kb = int(enc_path.stat().st_size / 1024)
    log.info("Encrypted segment: %s -> %s (%d KB)  [original kept]",
             src_path.name, enc_path, size_kb)
    return jsonify({
        "enc_path": str(enc_path),
        "size_kb": size_kb,
        "original_kept": True,
        "original_path": str(src_path),
    })
