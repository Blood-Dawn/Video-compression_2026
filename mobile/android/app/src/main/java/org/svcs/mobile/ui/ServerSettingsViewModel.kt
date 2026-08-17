package org.svcs.mobile.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.svcs.mobile.data.TokenStore
import org.svcs.mobile.net.Capabilities
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.HostClassifier
import org.svcs.mobile.net.ProbeResult
import org.svcs.mobile.net.SvcsApi
import java.net.URI

data class ServerSettingsState(
    val serverUrl: String = "",
    val token: String = "",
    val busy: Boolean = false,
    val ok: Boolean = false,
    val message: String? = null,
    val urlError: String? = null,
    val capabilities: Capabilities? = null,
    val needsPublicConsent: Boolean = false,
    /**
     * Bumped on every successful save.
     *
     * The shell watches this to rebuild its SvcsApi and drop the cached
     * per-tab ViewModels. Without it, re-pairing wrote a new token to storage
     * that nothing picked up: the screens kept using the client built at
     * launch, so a user told to "re-pair under MORE" after a token revocation
     * did exactly that and stayed broken until they force-quit the app.
     */
    val saveCount: Int = 0,
    /** 0.8.0: whether an upload auto-starts a mode1 compress. */
    val autoCompressUpload: Boolean = true,

    // ── 0.9.0 / R6 Track C: the SERVER's closed-app push settings ────────
    // These are not phone preferences. The server is what posts to ntfy, so
    // this screen is a remote control for a server-side config, and every
    // field here has to be fetched before it can be shown truthfully.
    val pushLoaded: Boolean = false,
    val pushEnabled: Boolean = false,
    val pushTopicUrl: String = "",
    val pushOnJobs: Boolean = true,
    val pushOnEvents: Boolean = true,
    /** Whether the SERVER holds a token. The token itself never comes back. */
    val pushHasToken: Boolean = false,
    /** Write-only. Cleared after a save so it is never held longer than needed. */
    val pushToken: String = "",
    val pushBusy: Boolean = false,
    val pushOk: Boolean = false,
    val pushMessage: String? = null,
)

/**
 * Pairing logic.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */
class ServerSettingsViewModel(app: Application) : AndroidViewModel(app) {

    private val store = TokenStore(app)
    private val _state = MutableStateFlow(ServerSettingsState())
    val state: StateFlow<ServerSettingsState> = _state.asStateFlow()

    /** Set once the user has explicitly accepted a non-private address. */
    private var publicAddressAccepted = false

    init {
        viewModelScope.launch {
            val url = store.serverUrl().orEmpty()
            val tok = store.token().orEmpty()
            val auto = store.autoCompressUpload()
            _state.update {
                it.copy(serverUrl = url, token = tok, autoCompressUpload = auto)
            }
        }
    }

    /** 0.8.0: flip whether uploads auto-start a compress. */
    fun toggleAutoCompress() {
        viewModelScope.launch {
            val next = !_state.value.autoCompressUpload
            store.setAutoCompressUpload(next)
            _state.update { it.copy(autoCompressUpload = next) }
        }
    }

    fun onServerUrlChanged(v: String) {
        publicAddressAccepted = false
        _state.update {
            it.copy(serverUrl = v, urlError = null, message = null,
                capabilities = null, needsPublicConsent = false)
        }
    }

    fun onTokenChanged(v: String) {
        _state.update { it.copy(token = v, message = null, capabilities = null) }
    }

    fun confirmPublicAddress() {
        publicAddressAccepted = true
        _state.update { it.copy(needsPublicConsent = false) }
        testConnection()
    }

    fun testConnection() {
        val raw = _state.value.serverUrl.trim()
        val normalized = normalizeUrl(raw)
        if (normalized == null) {
            _state.update { it.copy(urlError = "Enter an address like http://192.168.1.42:5000") }
            return
        }

        val host = hostOf(normalized)
        if (host == null) {
            _state.update { it.copy(urlError = "Could not read a host from that address.") }
            return
        }

        // Refuse a non-private address until the user explicitly accepts it.
        // The server sends credentials and video in the clear, so this is the
        // one moment worth interrupting the user for.
        if (HostClassifier.requiresExplicitConsent(host) && !publicAddressAccepted) {
            _state.update { it.copy(needsPublicConsent = true, message = null) }
            return
        }

        _state.update { it.copy(busy = true, message = null, capabilities = null) }
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                SvcsApi(normalized, _state.value.token.trim()).probe()
            }
            _state.update { s ->
                when (result) {
                    is ProbeResult.Ok -> s.copy(
                        busy = false, ok = true, capabilities = result.capabilities,
                        serverUrl = normalized,
                        message = "Connected to ${result.capabilities.editionLabel}.",
                    )
                    ProbeResult.BadCredential -> s.copy(
                        busy = false, ok = false,
                        message = "The server rejected that token. Create a new " +
                            "one on the dashboard and paste it here.",
                    )
                    is ProbeResult.RateLimited -> s.copy(
                        busy = false, ok = false,
                        message = "Too many failed attempts. Wait " +
                            "${result.retryAfterSeconds ?: 300}s and try again.",
                    )
                    is ProbeResult.Unreachable -> s.copy(
                        busy = false, ok = false,
                        message = "Could not reach that address. Check you are " +
                            "on the same network as the server. (${result.detail})",
                    )
                    is ProbeResult.NotSvcs -> s.copy(
                        busy = false, ok = false,
                        message = "Reached that address, but it is not an SVCS " +
                            "server. ${result.detail}",
                    )
                }
            }
        }
    }

    // ── R6 Track C: the server's push settings ───────────────────────────

    /** An API client on the SAVED pairing, or null if there is not one yet. */
    private fun pairedApi(): SvcsApi? {
        val url = normalizeUrl(_state.value.serverUrl.trim()) ?: return null
        val tok = _state.value.token.trim()
        if (tok.isBlank()) return null
        return SvcsApi(url, tok)
    }

    fun onPushTopicChanged(v: String) {
        _state.update { it.copy(pushTopicUrl = v, pushMessage = null) }
    }

    fun onPushTokenChanged(v: String) {
        _state.update { it.copy(pushToken = v, pushMessage = null) }
    }

    fun togglePushEnabled() {
        _state.update { it.copy(pushEnabled = !it.pushEnabled, pushMessage = null) }
    }

    fun togglePushOnJobs() {
        _state.update { it.copy(pushOnJobs = !it.pushOnJobs, pushMessage = null) }
    }

    fun togglePushOnEvents() {
        _state.update { it.copy(pushOnEvents = !it.pushOnEvents, pushMessage = null) }
    }

    /** Fetch the settings once, so the switches show the server's truth. */
    fun loadPushConfig() {
        val api = pairedApi() ?: return
        _state.update { it.copy(pushBusy = true) }
        viewModelScope.launch {
            val res = withContext(Dispatchers.IO) { api.getPushConfig() }
            _state.update { s ->
                when (res) {
                    is Fetched.Ok -> s.copy(
                        pushBusy = false, pushLoaded = true,
                        pushEnabled = res.value.config.enabled,
                        pushTopicUrl = res.value.config.topicUrl,
                        pushOnJobs = res.value.config.onJobs,
                        pushOnEvents = res.value.config.onEvents,
                        pushHasToken = res.value.config.hasToken,
                    )
                    // A failure SAYS SO rather than quietly leaving defaults on
                    // screen. Blank fields next to a server that actually has a
                    // topic saved read as "this feature is off", and an operator
                    // acting on that turns alerts on twice and wonders why.
                    //
                    // pushLoaded also stays FALSE here on purpose. Marking a
                    // failed fetch as loaded is what made a re-pair never pick
                    // the settings up: the first fetch 401'd on a dead token,
                    // the flag latched, and the successful pairing that
                    // followed left the fields showing defaults that did not
                    // match the server.
                    is Fetched.Failed -> s.copy(
                        pushBusy = false, pushOk = false,
                        pushMessage = "Could not read the server's alert " +
                            "settings: " + res.detail)
                    Fetched.Unauthorized -> s.copy(
                        pushBusy = false, pushOk = false,
                        pushMessage = "Could not read the server's alert " +
                            "settings: the server rejected this device token.")
                }
            }
        }
    }

    fun savePushConfig() {
        val api = pairedApi() ?: return
        val s0 = _state.value
        _state.update { it.copy(pushBusy = true, pushMessage = null) }
        viewModelScope.launch {
            val res = withContext(Dispatchers.IO) {
                api.savePushConfig(
                    enabled = s0.pushEnabled,
                    topicUrl = s0.pushTopicUrl.trim(),
                    onJobs = s0.pushOnJobs,
                    onEvents = s0.pushOnEvents,
                    token = s0.pushToken.trim().ifBlank { null },
                )
            }
            _state.update { s ->
                when (res) {
                    is Fetched.Ok -> s.copy(
                        pushBusy = false, pushOk = true, pushToken = "",
                        pushEnabled = res.value.config.enabled,
                        pushTopicUrl = res.value.config.topicUrl,
                        pushOnJobs = res.value.config.onJobs,
                        pushOnEvents = res.value.config.onEvents,
                        pushHasToken = res.value.config.hasToken,
                        pushMessage = if (res.value.config.enabled)
                            "Saved. Alerts are on." else "Saved. Alerts are off.",
                    )
                    is Fetched.Failed -> s.copy(
                        pushBusy = false, pushOk = false,
                        pushMessage = res.detail)
                    Fetched.Unauthorized -> s.copy(
                        pushBusy = false, pushOk = false,
                        pushMessage = "The server rejected this device token.")
                }
            }
        }
    }

    fun testPush() {
        val api = pairedApi() ?: return
        val s0 = _state.value
        if (s0.pushTopicUrl.isBlank()) {
            _state.update {
                it.copy(pushOk = false, pushMessage = "Enter a topic URL first.")
            }
            return
        }
        _state.update { it.copy(pushBusy = true, pushMessage = null) }
        viewModelScope.launch {
            val res = withContext(Dispatchers.IO) {
                api.testPush(s0.pushTopicUrl.trim(), s0.pushToken.trim().ifBlank { null })
            }
            _state.update { s ->
                when (res) {
                    is Fetched.Ok -> s.copy(
                        pushBusy = false, pushOk = res.value.ok,
                        pushMessage = if (res.value.ok)
                            "Test sent. Your ntfy app should buzz."
                        else "Test failed: " + res.value.detail)
                    is Fetched.Failed -> s.copy(
                        pushBusy = false, pushOk = false,
                        pushMessage = res.detail)
                    Fetched.Unauthorized -> s.copy(
                        pushBusy = false, pushOk = false,
                        pushMessage = "The server rejected this device token.")
                }
            }
        }
    }

    fun save() {
        viewModelScope.launch {
            store.setServerUrl(_state.value.serverUrl.trim())
            store.setToken(_state.value.token.trim())
            _state.update {
                it.copy(message = "Saved.", ok = true, saveCount = it.saveCount + 1)
            }
            // Re-read the server-side push settings with the credentials that
            // were just saved. The screen's LaunchedEffect cannot do this: it
            // keys on the server URL and the token, and BOTH already hold
            // their final values by the time the pairing succeeds, because the
            // user typed them before pressing TEST. So its only run happened
            // against the dead credential, and a phone that re-paired kept
            // showing an empty topic URL while the server had one saved.
            loadPushConfig()
        }
    }

    /**
     * Accept what a human types and turn it into a URL.
     *
     * "192.168.1.42" and "192.168.1.42:5000" both become valid http URLs,
     * because requiring a scheme is the kind of friction that has users
     * concluding the app is broken. The default port is 5000, matching
     * run_gui.py. Note the design mockup pre-fills 8000; 5000 is correct.
     */
    internal fun normalizeUrl(input: String): String? {
        if (input.isBlank()) return null
        var s = input.trim().removeSuffix("/")
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://$s"
        }
        return try {
            val uri = URI(s)
            if (uri.host.isNullOrBlank()) return null
            val port = if (uri.port == -1) 5000 else uri.port
            "${uri.scheme}://${uri.host}:$port"
        } catch (e: Exception) {
            null
        }
    }

    internal fun hostOf(url: String): String? = try {
        URI(url).host
    } catch (e: Exception) {
        null
    }
}
