# Upload Worker Design: moving the chunked upload off viewModelScope

Fall 3.3. Design doc for Jorge (or whoever implements this next) to build
against; nothing in this doc has been implemented yet.

## The problem this solves

`LibraryViewModel.uploadFromPhone()` runs the whole resumable chunked-upload
loop (`doUpload()`, in `mobile/android/app/src/main/java/org/svcs/mobile/ui/LibraryViewModel.kt`,
currently lines ~203-303) inside `viewModelScope.launch { ... }`. That
survives a tab switch or a config change (rotation), because `viewModelScope`
is tied to the ViewModel, not the Activity. It does **not** survive the
process being killed — backgrounded long enough for Android to reclaim it,
or the user swiping the app away mid-upload of a multi-gigabyte clip on a
slow connection. When that happens today, the upload just stops; there is no
mechanism to pick it back up.

WorkManager (`androidx.work`) is Android's own answer to exactly this: a
`OneTimeWorkRequest` is persisted by the OS (in WorkManager's own on-device
database) and WorkManager re-invokes it after process death, even after a
reboot, until it reports success or a terminal failure.

## What already exists and does not need to change

The server-side protocol is already resumable and was independently
audited this same week (`docs/security/UPLOAD-PROTOCOL-AUDIT.md`, Fall
3.4): `POST /api/upload/begin` mints an `upload_id`; `POST
/api/upload/chunk?upload_id=X&offset=K` either accepts (200, new offset) or
tells you the true offset (409); `GET /api/upload/status?upload_id=X`
reports the server's authoritative offset; `POST /api/upload/finish`
verifies size + SHA-256 + decodability. `SvcsApiClient` (interface) /
`SvcsApi` (implementation) already expose all four calls
(`uploadBegin`/`uploadChunk`/`uploadStatus`/`uploadFinish`). None of that
needs to change — this migration is purely about *what drives the loop*,
not the wire protocol.

## Design

### 1. Worker type: `CoroutineWorker`

The four `SvcsApiClient` calls are already synchronous/blocking Kotlin calls
made from a coroutine via `withContext(ioDispatcher)` in the current code —
`CoroutineWorker.doWork()` is a `suspend fun`, so the existing chunk-loop
body ports over close to as-is, just moved out of `viewModelScope.launch`
and into `doWork()`.

### 2. What crosses the process-death boundary, and how

WorkManager persists the `OneTimeWorkRequest` itself (worker class,
constraints, input `Data`) automatically. It does **not** persist anything
the Worker computes mid-run — no upload offset, no `upload_id`. `Data` (both
input and output) is capped at 10 KB serialized and is immutable once
enqueued, so it cannot be used as a place to keep updating the offset either.

So the Worker's own persisted state — `upload_id` and last-known offset —
must be written by the app itself, not left to WorkManager. Given this app
already uses `androidx.datastore.preferences` (see `TokenStore`, `pairing`
package) for small durable key-value state, the natural fit is a small
DataStore-backed `UploadState` (or a tiny Room table if more than one
concurrent upload ever needs tracking — out of scope for v1, this app
uploads one clip at a time today) keyed by a locally-generated upload
tracking id, holding: `contentPath` (see #3, NOT the original `content://`
Uri), `filename`, `size`, `serverUploadId` (nullable until `/begin`
succeeds), `lastKnownOffset`.

**Critical point for `doWork()`'s first lines, every single invocation**
(fresh start AND resume-after-death AND `Result.retry()` restart all look
identical from inside `doWork()` — there is no way to tell them apart, and
the code should not try to): treat the locally-stored offset as a *hint*,
not the truth. Always call `GET /api/upload/status?upload_id=X` first (or
`POST /begin` if no `serverUploadId` is stored yet) and resume from
whatever the server reports, exactly like the current `doUpload()` already
does reactively on a 409. This sidesteps any question of whether the local
DataStore write and the server ack were ever perfectly in sync — the server
is always asked, not assumed.

### 3. The `content://` Uri problem (read this before writing any code)

This is the sharpest pitfall in this migration and needs to shape the
implementation from the start, not be patched in later. `uploadFromPhone(resolver:
ContentResolver, uri: Uri)` currently takes a `content://` Uri straight from
whatever picker `LibraryScreen` uses to launch the upload. That Uri's read
permission is scoped to the Activity/task that received it and is not
guaranteed to survive the Activity going away — including across the
process death this whole migration exists to survive. Depending on which
picker contract is used (`GET_CONTENT`, the system Photo Picker, or
`OPEN_DOCUMENT`), a persistable grant (`takePersistableUriPermission`) may
not even be available.

**Do not defer reading the source Uri into the Worker.** Instead, as soon as
the user picks the file (in the UI layer, while the grant from the picker
is still fresh — this part is unchanged from what already happens today),
stream-copy it into app-private storage (`context.filesDir` or
`context.cacheDir`) under a stable name, and give the `OneTimeWorkRequest`'s
input `Data` that stable path instead of the original Uri string. This is
the standard pattern for exactly this situation: it removes the Worker's
dependency on the picker's lifecycle entirely, and it also gives the
chunking loop reliable random-access byte-range reads (some content
providers are stream-only and do not support the `skip()`-then-read pattern
`doUpload()` currently relies on for reseeking to an offset). Delete the
private copy once the upload reaches a terminal state
(`Result.success()`/`Result.failure()`, or `onStopped()`).

### 4. Enqueueing and identity

```kotlin
val request = OneTimeWorkRequestBuilder<UploadWorker>()
    .setInputData(workDataOf(
        KEY_LOCAL_PATH to privateCopyPath,
        KEY_FILENAME to displayName,
        KEY_SIZE to size,
    ))
    .setConstraints(Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build())
    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, WorkRequest.MIN_BACKOFF_MILLIS, TimeUnit.MILLISECONDS)
    .build()

WorkManager.getInstance(context)
    .enqueueUniqueWork("upload-$localTrackingId", ExistingWorkPolicy.KEEP, request)
```

`enqueueUniqueWork` (not bare `enqueue`), keyed by a stable locally-generated
id, matters for two reasons: it stops a duplicate Worker being spawned if
the upload screen is somehow re-entered while one is already running, and it
lets the ViewModel re-attach to the running/finished work purely by that
name after process death, without needing to have kept the `WorkRequest.id`
around anywhere (`WorkManager.getWorkInfosForUniqueWorkFlow("upload-$id")`).

### 5. Progress: replacing the current `"Uploading X: NN%"` state

`doWork()` calls `setProgress(workDataOf(KEY_PROGRESS to percent))` after
each chunk ack, same cadence as the current `_state.update {
it.copy(actionMessage = "Uploading $name: $pct%") }` call. `LibraryViewModel`
observes it via `WorkManager.getInstance(context).getWorkInfosForUniqueWorkFlow("upload-$id")`
(a `Flow`, fits the existing `StateFlow`-based ViewModel pattern used
elsewhere in this file) and maps `WorkInfo.progress.getInt(KEY_PROGRESS, 0)`
into the same `actionMessage` field the UI already reads. `setProgress` is
only observable while the Worker is actively running — it is not a durable
store, so it plays no role in #2's resume logic.

### 6. Retry strategy: keep the inner retry, add an outer one

The current code already retries a failed chunk up to 5 times before giving
up (`retries += 1; if (retries > 5) return "Upload failed after retries..."`).
Keep that inner loop as-is inside `doWork()` — it is the right granularity
for a single dropped chunk. Layer WorkManager's own `Result.retry()` on top
for the coarser case: the inner retry budget is exhausted, or a structural
failure (token rejected — `ChunkResult.Unauthorized` already exists in the
current code and should map to `Result.failure()`, not retry, since retrying
with the same bad token will never succeed). Reserve `Result.failure()` for
anything retrying cannot fix: unauthorized, a 4xx that will not change,
`autoCompress()`/finish-time errors that are not transient.

### 7. Foreground service requirement (targetSdk 35)

A chunked upload of a large clip on a slow connection can easily run past
WorkManager's own ~10-minute expedited-work ceiling, so this needs
`setForeground()`/`ForegroundInfo`, not `setExpedited()`. Concretely:
manifest needs `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_DATA_SYNC`
permissions (the latter is a normal, install-time-granted permission — no
runtime prompt) plus a manifest merge line for WorkManager's own
`SystemForegroundService` declaring `android:foregroundServiceType="dataSync"`;
`doWork()` calls `setForeground(ForegroundInfo(id, notification,
ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC))` at the start and again
periodically to refresh the progress notification. Wrap that call in
try/catch — a `ForegroundServiceStartNotAllowedException` is possible if the
OS refuses (app background-restricted); on Android 15+ there is also a
6-hour rolling aggregate cap on `dataSync` foreground-service time shared
across the app, which will not be hit by a single upload in practice but is
worth a comment in the code so a future "upload several huge files back to
back" feature does not get quietly throttled without explanation.

### 8. Test plan

- **JVM unit tests** (`TestListenableWorkerBuilder<UploadWorker>`, no real
  WorkManager scheduler involved): the chunk-retry loop, the
  offset-reconciliation logic in #2 (given a local hint and a mocked server
  response, confirm it resumes from the server's value), and the
  `Result.success()`/`retry()`/`failure()` mapping for each `ChunkResult`
  case — same shape as the existing `LibraryViewModelTest`-style fakes
  already used elsewhere in this test suite (see `FakeSvcsApi`).
- **Instrumented tests** (`androidTest`, `WorkManagerTestInitHelper` +
  `SynchronousExecutor`): `enqueueUniqueWork` + `NetworkType.CONNECTED`
  constraint behavior, using `TestDriver.setAllConstraintsMet(...)` to avoid
  waiting on a real network state change.
- Not practically coverable by `work-testing` at all: an actual
  kill-and-restart of the process mid-upload. That needs a manual/on-device
  check before shipping (kill the app via `adb shell am kill` mid-upload,
  relaunch, confirm the upload resumes rather than restarting from 0) —
  same category as the emulator smoke-test step already in
  `docs/releases/RELEASE-CHECKLIST.md`'s mobile section.

## Out of scope for v1

- Multiple concurrent uploads (today's UI only supports one at a time via
  the `compressing` guard in `LibraryViewModel`; the unique-work-name scheme
  above would need to become per-upload-id rather than a single fixed name
  if that ever changes).
- A user-initiated-data-transfer-job migration (Android 16+ quota exemption
  API) — flagged as a future follow-up if upload duration/frequency ever
  becomes a real quota problem, not needed for this migration.
