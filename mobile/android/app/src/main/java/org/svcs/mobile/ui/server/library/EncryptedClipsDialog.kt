package org.svcs.mobile.ui.server.library

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Request
import org.svcs.mobile.crypto.ClipDecryptor
import org.svcs.mobile.net.EncryptedClip
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.SvcsApiClient
import org.svcs.mobile.ui.VideoIntents
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * Encrypted clips on the server, opened on the phone.
 *
 * The clip downloads as ciphertext and is decrypted here with the password
 * or key file the person types or picks. Neither ever leaves the phone. The
 * plaintext copy lives in the app cache only long enough to hand to a video
 * player, and is wiped the next time this dialog opens or closes.
 */
@Composable
fun EncryptedClipsDialog(api: SvcsApiClient, folder: String?, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var clips by remember { mutableStateOf<List<EncryptedClip>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var picked by remember { mutableStateOf<EncryptedClip?>(null) }
    var password by remember { mutableStateOf("") }
    var keyBytes by remember { mutableStateOf<ByteArray?>(null) }
    var keyName by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        wipeClipCache(context)
        when (val r = withContext(Dispatchers.IO) { api.encryptedClips(folder) }) {
            is Fetched.Ok -> clips = r.value.items
            Fetched.Unauthorized -> error = "The server rejected this device's token. Re-pair under MORE."
            is Fetched.Failed -> error = "Could not list encrypted clips. ${r.detail}"
        }
    }
    val keyPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            val bytes = runCatching {
                context.contentResolver.openInputStream(uri)?.use { ins ->
                    val buf = ByteArray(65)
                    var n = 0
                    while (n < buf.size) {
                        val r = ins.read(buf, n, buf.size - n)
                        if (r < 0) break
                        n += r
                    }
                    buf.copyOf(n)
                }
            }.getOrNull()
            if (bytes != null && bytes.size == 32) {
                keyBytes = bytes
                keyName = uri.lastPathSegment?.substringAfterLast('/') ?: "key file"
                message = null
            } else {
                keyBytes = null
                keyName = null
                message = "That is not an SVCS key file. It must be exactly 32 bytes."
            }
        }
    }
    fun close() { wipeClipCache(context); onDismiss() }

    AlertDialog(
        onDismissRequest = { if (!busy) close() },
        confirmButton = {
            val target = picked
            if (target != null) {
                TextButton(
                    enabled = !busy && (password.isNotEmpty() || keyBytes != null),
                    onClick = {
                        busy = true; message = null
                        scope.launch {
                            message = unlockAndPlay(context, api, folder, target, password, keyBytes)
                            busy = false
                            password = ""
                        }
                    },
                ) { Text("UNLOCK AND PLAY") }
            }
        },
        dismissButton = {
            TextButton(enabled = !busy, onClick = {
                if (picked != null) { picked = null; message = null } else close()
            }) { Text(if (picked != null) "BACK" else "CLOSE") }
        },
        title = { Text("Encrypted clips", style = MaterialTheme.typography.titleSmall) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                val target = picked
                when {
                    target != null -> {
                        Text(target.name, style = MaterialTheme.typography.bodyMedium, maxLines = 2)
                        OutlinedTextField(
                            value = password, onValueChange = { password = it },
                            label = { Text("Password") }, singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(enabled = !busy, onClick = { keyPicker.launch(arrayOf("*/*")) }) {
                                Text(if (keyName == null) "USE A KEY FILE" else "KEY: $keyName")
                            }
                        }
                        Text("Decryption happens on this phone. The password is never sent.",
                            style = MaterialTheme.typography.bodySmall, color = SvcsTextDim)
                        if (busy) CircularProgressIndicator()
                    }
                    error != null -> Text(error!!, color = SvcsRed)
                    clips == null -> CircularProgressIndicator()
                    clips!!.isEmpty() -> Text("No encrypted clips in this folder.", color = SvcsTextDim)
                    else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        items(clips!!, key = { it.path }) { c ->
                            Column(Modifier.fillMaxWidth().clickable { picked = c; message = null }
                                .padding(vertical = 6.dp)) {
                                Text(c.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                                Text(humanBytes(c.size), style = MaterialTheme.typography.labelSmall,
                                    color = SvcsAmber)
                            }
                        }
                    }
                }
                message?.let { Text(it, color = SvcsRed, style = MaterialTheme.typography.bodySmall) }
            }
        },
    )
}

private fun humanBytes(b: Long): String = when {
    b >= 1_048_576 -> String.format("%.1f MB", b / 1_048_576.0)
    b >= 1024 -> String.format("%.0f KB", b / 1024.0)
    else -> "$b B"
}

private fun clipDir(context: Context) = File(context.cacheDir, "clips")

private fun wipeClipCache(context: Context) {
    clipDir(context).listFiles()?.forEach { it.delete() }
}

/** Returns an error message, or null when the clip was handed to a player. */
private suspend fun unlockAndPlay(
    context: Context, api: SvcsApiClient, folder: String?,
    clip: EncryptedClip, password: String, key: ByteArray?,
): String? = withContext(Dispatchers.IO) {
    val dir = clipDir(context)
    wipeClipCache(context)
    dir.mkdirs()
    val enc = File(dir, "download.enc")
    try {
        val req = Request.Builder().url(api.encFileUrl(clip.path, folder)).build()
        api.httpClient().newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return@withContext "The server did not send the clip (HTTP ${resp.code})."
            val body = resp.body ?: return@withContext "The server sent an empty response."
            enc.outputStream().use { out -> body.byteStream().copyTo(out) }
        }
        val base = clip.name.removeSuffix(".enc").ifBlank { "clip" }
        val out = File(dir, if (base.contains('.')) base else "$base.mp4")
        val result = if (key != null) ClipDecryptor.decrypt(enc, out, rawKey = key)
        else ClipDecryptor.decrypt(enc, out, password = password.toCharArray())
        enc.delete()
        when (result) {
            is ClipDecryptor.Result.Ok -> {
                val uri: Uri = FileProvider.getUriForFile(
                    context, context.packageName + ".fileprovider", result.output)
                val ok = withContext(Dispatchers.Main) { VideoIntents.play(context, uri) }
                if (ok) null else "No video player on this phone can open the clip."
            }
            ClipDecryptor.Result.WrongKeyOrCorrupt -> "Wrong password or key, or the clip was changed."
            ClipDecryptor.Result.NotAnEncryptedClip -> "That file is not an SVCS encrypted clip."
            ClipDecryptor.Result.TooLarge -> "That clip is too large to open on the phone (limit 200 MB)."
            ClipDecryptor.Result.BadKeyFile -> "Enter the password or choose a key file."
        }
    } catch (e: Exception) {
        enc.delete()
        "Could not open the clip: ${e.message ?: e.javaClass.simpleName}"
    }
}
