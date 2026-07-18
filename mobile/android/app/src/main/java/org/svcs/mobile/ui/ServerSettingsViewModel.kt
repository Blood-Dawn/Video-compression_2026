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
            _state.update { it.copy(serverUrl = url, token = tok) }
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

    fun save() {
        viewModelScope.launch {
            store.setServerUrl(_state.value.serverUrl.trim())
            store.setToken(_state.value.token.trim())
            _state.update { it.copy(message = "Saved.", ok = true) }
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
