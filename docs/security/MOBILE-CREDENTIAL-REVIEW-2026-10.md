# Mobile Credential Storage Review - October 2026

**Planner task:** 5.9, "Review the mobile credential storage path end to end"
**Reviewer:** Victor De Souza Teixeira
**Code reviewed:** `origin/mobile` at `ce38779` (2026-10-01). The Android app is
not on `main`; see the Week 3 progress report.
**Question asked by the planner:** when decrypting the stored device token
fails, does the app **fail closed**, or can it hand back a **stale credential**?

---

## Answer

**It fails closed.** No path in the app returns an old or cached credential
after a failed decrypt. Every reader treats the failure as "not paired" and
stops using the server.

This was established by reading every caller of the token store, not by running
the app: this review was done without an Android SDK, so nothing here was
executed on a device. Section 5 proposes a device test that would turn this
reading into a check.

Three smaller findings, none of them a credential leak:

| ID | Finding | Severity |
|----|---------|----------|
| MC-1 | `clearToken()` is documented as running "after a failed decrypt", but nothing in the app calls it except the tests | Low (doc/code mismatch) |
| MC-2 | Any exception during decrypt, including a transient Keystore error, is treated as "not paired", so re-pairing can leave a still-valid old token on the server | Low |
| MC-3 | No test covers the failed-decrypt path; the device test only covers the happy path and a deliberate clear | Low (test gap) |

## 1. How the credential is stored

`mobile/android/app/src/main/java/org/svcs/mobile/data/TokenStore.kt`

* The device token is encrypted with **AES-256-GCM** under a key generated
  inside the **Android Keystore** (`svcs_token_key_v1`). The key is
  non-exportable; only `base64(iv || ciphertext)` is written to DataStore.
* GCM's authentication tag means a modified blob fails to decrypt rather than
  decrypting to garbage.
* The server URL is stored in the clear on purpose (not a secret).
* **Backups are excluded.** `AndroidManifest.xml` sets `allowBackup="false"`,
  and both `backup_rules.xml` and `data_extraction_rules.xml` exclude the
  DataStore directory from cloud backup and device-to-device transfer. So the
  ciphertext never reaches a second device in the first place.
* The key is deliberately not bound to user authentication, so background HLS
  playback keeps working with the screen off. The trade-off is documented in
  the code and accepted: a lost phone is answered by per-device revocation on
  the server.

These are sound choices. GCM with a Keystore key is the pattern the deprecated
`EncryptedSharedPreferences` used internally.

## 2. The decrypt path

```kotlin
suspend fun token(): String? {
    val blob = context.settingsStore.data.first()[TOKEN_BLOB] ?: return null
    return try {
        cipher.decrypt(blob)
    } catch (e: Exception) {
        null
    }
}
```

There is no in-memory cache inside `TokenStore`. Every call re-reads DataStore
and re-decrypts. On any failure it returns `null`. It cannot return a previous
value because it never holds one.

What makes decrypt fail in practice:

| Cause | What happens |
|-------|--------------|
| Blob corrupted or tampered with | GCM tag check fails (`AEADBadTagException`), returns `null` |
| Keystore key deleted (app data partially cleared, OS keystore reset) | `secretKey()` **generates a fresh key** under the same alias, the old blob fails its tag check, returns `null` |
| Blob too short | `require(...)` throws `IllegalArgumentException`, returns `null` |
| Transient Keystore error | Caught by the same `catch (e: Exception)`, returns `null` (see MC-2) |

## 3. Every caller, and what it does with `null`

| Caller | What it does with the token | On `null` |
|--------|------------------------------|-----------|
| `ui/SvcsApp.kt` (pairing probe at launch and on re-pair) | Builds `SvcsApi(url, token)` and probes the server | Builds no client. `api = null`, the SERVER tab is hidden, and the user is sent to COMPRESS. **Fails closed.** |
| `upload/UploadWorker.kt` (background upload) | Builds `SvcsApi(url, token)` for the chunked upload | Fails the job with "Not paired with a server any more. Pair under MORE, then upload again." **Fails closed.** |
| `ui/server/settings/ServerSettingsViewModel.kt` (MORE screen) | Pre-fills the token field | Shows an empty field. Saving afterward writes the empty value, which every reader again treats as unpaired (`isNullOrBlank`). **Fails closed.** |

**In-memory copies.** The plaintext token does live in memory in two places:
the `SvcsApi` client built in `SvcsApp`, and the settings screen's
`ServerSettingsState.token`. Neither is "stale" in the sense this task asks
about. Both hold the token that was valid when they were built, the client is
rebuilt on every re-pair (`sessionEpoch`), and a revoked token is refused by
the server with a 401 regardless of what the phone still holds. That is the
correct place for revocation to be enforced.

## 4. Findings

### MC-1 - `clearToken()` is never called by the app (Low)

`TokenStore.clearToken()` is documented as "Used on unpair and after a failed
decrypt." A search of every Kotlin file on `origin/mobile` finds no caller in
`app/src/main`. The only callers are tests (`TokenStorePersistenceTest.kt` and
`ServerSettingsViewModelTest.kt`).

**Effect.** After a failed decrypt the unreadable blob stays in DataStore, and
every later `token()` call repeats the Keystore attempt and fails the same way.
That is still fail-closed and harmless, and the next successful pairing
overwrites the blob. The risk is the **comment**: the next person to touch this
code will believe a cleanup happens that does not.

**Recommendation.** Either correct the comment, or clear the blob only on a
failure that is known to be permanent (see MC-2), never on every exception.

### MC-2 - Transient errors look like "unpaired" (Low)

`catch (e: Exception)` cannot tell a permanently bad blob (`AEADBadTagException`,
a short blob) from a passing Keystore hiccup (a `ProviderException` or
`KeyStoreException` while the keystore daemon is busy).

**Effect.** A transient error makes the app look unpaired. The user re-pairs,
which mints a **new** token on the server, while the old token is still valid
there. The phone cannot revoke it (token management needs the password, by
design), so it stays live until the operator removes it from the device list.
That is token sprawl, not a leak: the old token is still encrypted on that
phone and nowhere else. The server caps stored tokens at 50.

This may also be worth checking against the pairing persistence defect in
planner 4.1/4.2, since a phone that "forgets" its pairing after a restart is
one visible symptom this would produce.

**Recommendation.** Catch `AEADBadTagException` and `IllegalArgumentException`
as "permanently unreadable" (return `null`, and clearing is safe). Retry once
on other exceptions before giving up. Log the exception **class name** only,
never the blob.

### MC-3 - The failure path has no test (Low)

`TokenStorePersistenceTest` checks that a token survives a restart and that a
deliberate clear forgets it. Nothing checks the question this task asks:
corrupt the stored blob, or lose the key, and confirm `token()` returns `null`
rather than a previous value.

## 5. Proposed tests (not run; needs the Android toolchain)

These match the style of the existing device test. They were written for this
review and **have not been compiled or run**.

```kotlin
// androidTest: TokenStorePersistenceTest.kt, alongside the existing cases

@Test
fun aTamperedBlobFailsClosedNotStale() = runBlocking {
    val store = TokenStore(context)
    store.setToken("dev_real_token")
    // Overwrite the ciphertext with valid base64 that is not a valid blob.
    context.settingsStore.edit {
        it[stringPreferencesKey("token_blob")] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    }
    assertNull(TokenStore(context).token())
}

@Test
fun losingTheKeystoreKeyFailsClosedNotStale() = runBlocking {
    TokenStore(context).setToken("dev_real_token")
    KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        .deleteEntry("svcs_token_key_v1")
    // A fresh key is generated on the next read; the old blob must not decrypt.
    assertNull(TokenStore(context).token())
}
```

`settingsStore` is `private` in `TokenStore.kt`, so the first test needs either
a small `internal` test hook or a second `preferencesDataStore` delegate with
the same name in the test file. The JVM tests can also cover the same rule
without a device, through the existing `TokenCipher` seam: a cipher whose
`decrypt` always throws must make `token()` return `null`.

## 6. Summary for the progress report

The mobile credential path fails closed: a token that cannot be decrypted is
treated as "not paired" by all three readers, and no code path returns a
previous or cached credential. Backups exclude the encrypted store entirely.
Three low-severity follow-ups: a doc comment that promises a cleanup the code
does not do (MC-1), transient Keystore errors being indistinguishable from a
lost pairing (MC-2), and no test for the failure path (MC-3, tests proposed
above).
