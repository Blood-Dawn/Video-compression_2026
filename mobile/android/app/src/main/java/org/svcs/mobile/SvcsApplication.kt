package org.svcs.mobile

import android.app.Application

/**
 * Application entry point.
 *
 * Deliberately empty. There is no analytics SDK, no crash reporter, and no
 * push-notification client to initialize here, matching the server's
 * send_default_pii=False posture and the project's no-cloud-calls rule. If
 * crash reporting is ever wanted it should be ACRA (Apache-2.0) to a
 * self-hosted endpoint, opt-in behind the same two-flag pattern the server
 * uses for usage stats.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */
class SvcsApplication : Application()
