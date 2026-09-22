# Resumable Upload Protocol Audit (Fall 3.4)

Audit of the resumable chunked-upload protocol the mobile app uses
(`POST /api/upload/begin`, `POST /api/upload/chunk`, `GET /api/upload/status`,
`POST /api/upload/finish`, all in `src/gui/routes/ingest_bp.py`), against the
question the planner task asked: does `/api/upload/status` return an offset a
client can actually resume from safely?

Date: 2026-09-22. Branch: `mobile`.

## Answer, short version

Yes, with two real gaps that this audit found and fixed (locking, cleanup),
and one durability gap that this audit found, fixed (fsync), and bounded
(finish-time verification already covers the residual risk).

## How the protocol works

```
POST /api/upload/begin   {"name": "clip.mp4", "size": N}
    -> {"upload_id": hex, "offset": 0, "chunk_hint": 1048576}
POST /api/upload/chunk?upload_id=X&offset=K   (raw bytes body)
    -> {"offset": K+len}    or 409 {"offset": current} when K is stale
GET  /api/upload/status?upload_id=X -> {"offset": current}
POST /api/upload/finish  {"upload_id": X, "sha256": hex}
    -> verifies size, whole-file hash, and a decodable video stream
```

State is a `<upload_id>.part` file plus a `<upload_id>.json` sidecar under
`data_dir()/upload_tmp/`, not an in-memory dict and not a database. That
means an in-progress upload already survives a clean server restart: the
`.part` file's size IS the offset, read fresh off disk on every request, so
there is nothing to resync after a restart the way there would be with a
cached in-memory value.

## Findings

| ID | Area | Severity | What | Status |
|----|------|----------|------|--------|
| UPL-001 | Durability | Low | `api_upload_chunk` wrote with `open(part, "ab")` and no `fh.flush()`/`os.fsync()`. Between a `write()`/`close()` and the OS actually flushing the page to disk, a chunk endpoint's reported offset could theoretically be ahead of what survives a crash/power-loss (not an ordinary process restart, which is unaffected). Bounded even before this fix: `finish` independently re-checks size and re-hashes the whole file with SHA-256, so a truncated write from this narrow window is caught there, not silently accepted. | fixed |
| UPL-002 | Correctness (race) | Medium | No locking around the read-check-write section in `api_upload_chunk`. Two concurrent requests for the SAME `upload_id` (a retry racing the original, or a client bug) could both read the same `current` offset, both pass the offset check, and both append -- the file ends up larger than either individual response reported, desyncing the client's tracked offset from the true file size, and could jointly exceed the declared size past the overflow guard (which read `current` before the race too). Untested before this audit. | fixed |
| UPL-003 | Resource exhaustion | Low | No TTL/cleanup for abandoned uploads. A client that calls `/begin` and never follows up (app killed, picker cancelled, network gone for good) left its `.part`/`.json` pair on disk forever -- an unbounded, slow disk leak with no scheduled task or reaper anywhere in the codebase to catch it. | fixed |
| UPL-004 | Correctness | -- | 409-with-correct-offset resume mechanics: confirmed to work exactly as the mobile client (`SvcsApi.kt`) assumes -- an offset mismatch always returns the server's true `current` as the resume point, verified against a passing test before this audit even started. | confirmed, no change needed |
| UPL-005 | Correctness | -- | Finish-time integrity: size check, full SHA-256 re-hash, and an `ffprobe` decodability check, all before the file is promoted out of the temp dir. A hash mismatch discards the part entirely rather than leaving it for a resume that would preserve corruption (by design -- there is intentionally no partial-resume-after-corruption path). Confirmed correct, no change needed. | confirmed, no change needed |

## Fixes (this audit)

All three in `src/gui/routes/ingest_bp.py`:

1. **UPL-001 (fsync)**: `api_upload_chunk` now does `fh.flush(); os.fsync(fh.fileno())`
   after every chunk write, inside the new lock (below), so a chunk's 200
   response is not returned until the bytes are actually durable.
2. **UPL-002 (locking)**: a per-`upload_id` `threading.Lock`, created lazily
   in a `_lock_for()` helper guarded by one small module-level lock, now
   wraps the entire read-current-offset -> check -> write section of
   `api_upload_chunk`. Locks are dropped (`_forget_lock`) once an upload
   finishes, is discarded (hash/decode failure), or is swept as stale, so
   the lock dict does not grow without bound over the app's lifetime.
3. **UPL-003 (cleanup)**: `_sweep_stale_uploads()` runs, best-effort, at the
   top of every `/api/upload/begin` call. It deletes any `.part`/`.json`
   pair whose sidecar is older than `_UPLOAD_TTL_SECONDS` (48 hours). This
   was chosen over a background scheduler thread because the app has no
   existing cron/scheduler infra for this kind of housekeeping, and
   `/begin` is called often enough (once per new upload) that abandoned
   uploads get swept promptly without adding a new moving part. The sweep
   never raises -- a cleanup bug must not break a real upload in progress.

## Tests

`tests/test_chunked_upload.py` gained two regression tests (all 10 in that
file pass, plus the pre-existing 28 in `test_mobile_client_contract.py` and
`tests/security/test_ingest_filename_normalization.py`):

- `test_concurrent_chunk_requests_do_not_desync_the_offset` -- fires two
  real threads at the same `upload_id&offset=0` simultaneously (via a
  `threading.Barrier`) and asserts exactly one gets 200 and the other gets
  409 with the true offset, and that the part file has exactly one copy of
  the chunk, not two.
- `test_stale_upload_is_swept_after_ttl` / `test_sweep_leaves_fresh_uploads_alone`
  -- back-dates a sidecar past the TTL (instead of waiting 48 hours) and
  confirms the next `/begin` sweeps it, while a fresh upload from the same
  test is left alone.

## What this audit deliberately did not change

- The TTL sweep runs opportunistically on `/begin`, not on a timer. If the
  app goes a long time with no new uploads, an abandoned upload from that
  quiet period sits until the next `/begin` happens to run past it. Given
  this app's usage pattern (uploads are user-initiated, not constant), this
  was judged an acceptable trade against adding a background thread. Worth
  revisiting if abandoned-upload volume ever becomes large enough to matter
  between uploads.
- No change to the `_MAX_SIZE` (8 GB) cap or `chunk_hint` (1 MB) -- those
  were out of scope for a resume-correctness audit.
