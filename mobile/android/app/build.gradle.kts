// SVCS Mobile - app module.
// Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "org.svcs.mobile"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.svcs.mobile"
        // minSdk 29 (Android 10): the floor where the modern Keystore behavior
        // this app relies on is dependable, and where platform AV1 decode first
        // appears for later milestones.
        minSdk = 29
        targetSdk = 35
        // versionCode tracks the milestone the build actually contains.
        // 3 = M3 (pairing + LIBRARY + METRICS + HOME + LIVE), first public beta.
        // 4 = 0.3.1: the save-event replay glitch fix + SAVE & OPEN pairing UX.
        // 5 = 0.4.0 (M4 first slice): in-app clip playback, library filter
        //     views, compress-from-phone (server-side path).
        // 6 = 0.4.1: OUTPUTS shortcut; server-side, pipeline outputs now
        //     register in the compressed index so COMPRESSED shows them.
        // 7 = 0.4.2: compression-mode picker on COMPRESS (the desktop's four
        //     modes with honest codec notes; mode1 stays the default).
        // 8 = 0.5.0: M5 job-completion notifications (app-alive polling),
        //     and minification is BACK ON with complete R8 keep rules,
        //     re-verified on the physical device.
        // 9 = 0.6.0 (R6 Track A): EVENTS tab with behavior-event list and
        //     notifications, plus the drag-to-draw zone/line editor.
        // 10 = 0.7.0 (R6 Track B): resumable chunked upload from the phone's
        //      gallery, then auto-compress; completes the M4 ingest tail.
        // 11 = 0.8.0: auto-compress-on-upload becomes a MORE toggle, and INFO
        //      on every clip shows per-video metrics (codec, resolution, fps,
        //      duration, provenance) instead of only server-wide numbers.
        // 12 = 0.9.0 (R6 Track C): closed-app push. MORE gains a remote control
        //      for the server's ntfy settings, so an alert reaches the phone
        //      through the ntfy app even when Android has stopped SVCS.
        // 13 = 1.0.0-beta (Fall roadmap Phase 1-2): the standalone on-device
        //      compressor. COMPRESS works with no server at all, SAVED is a
        //      searchable history of on-device jobs, and opt-in Smart
        //      Compress runs YOLOv8n on-device via LiteRT. Server Mode tabs
        //      are unchanged. Published as the v1-beta GitHub release.
        // 14 = 1.1.0-beta: UI pass. The SVCS design system applied to the
        //      compressor (bundled fonts, full color scheme, components,
        //      icons), one layout per job state, honest size estimates.
        // 15 = 1.2.0-beta (prepared 2026-09-24, not yet released): Smart
        //      Compress region-of-interest encoding on FEATURE_Roi phones,
        //      per-phone size-limit calibration, encoder-fallback notices,
        //      one SERVER tab for Server Mode, the cleanup sweep.
        versionCode = 15
        versionName = "1.2.0-beta"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // FLAG_SECURE stays on in every normal build (see MainActivity). This
        // switch exists only for store screenshots and UI review, and has to
        // be asked for explicitly on the command line:
        //   ./gradlew assembleDebug -PsvcsAllowScreenshots=true
        // Nothing checked in or published ever sets it.
        buildConfigField(
            "boolean",
            "ALLOW_SCREENSHOTS",
            (project.findProperty("svcsAllowScreenshots") as String? ?: "false"),
        )
    }

    // Release signing (first public APK, 2026-08-16). The keystore is NOT in
    // the repo; it lives on the release machine and is passed in via env vars:
    //   SVCS_ANDROID_KEYSTORE      absolute path to the .jks
    //   SVCS_ANDROID_KS_PASS       keystore password
    //   SVCS_ANDROID_KEY_ALIAS     key alias (default "svcs")
    //   SVCS_ANDROID_KEY_PASS      key password (defaults to the store pass)
    // When the env vars are absent (CI, contributor machines) the release
    // buildType falls back to the debug signing config, so `assembleRelease`
    // still produces an installable APK anywhere. A self-signed key is the
    // normal, correct thing for a sideloaded GitHub-release APK; Play Store
    // publishing (if ever) would use its own upload key.
    // Author: Bloodawn (KheivenD), 2026-08-16 (first APK release).
    signingConfigs {
        create("release") {
            val ksPath = System.getenv("SVCS_ANDROID_KEYSTORE")
            if (ksPath != null) {
                storeFile = file(ksPath)
                storePassword = System.getenv("SVCS_ANDROID_KS_PASS")
                keyAlias = System.getenv("SVCS_ANDROID_KEY_ALIAS") ?: "svcs"
                keyPassword = System.getenv("SVCS_ANDROID_KEY_PASS")
                    ?: System.getenv("SVCS_ANDROID_KS_PASS")
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            buildConfigField("boolean", "ENABLE_HTTP_LOG", "true")
        }
        release {
            // Minification back ON (0.5.0): the 0.3.0 black screen was the
            // generated kotlinx-serialization $$serializer classes and the
            // Signature attribute being stripped; proguard-rules.pro now keeps
            // them wholesale, and the minified build is re-verified on the
            // physical device before every release per the R8 note there.
            // Author: Bloodawn (KheivenD), 2026-08-17 (R8 keep rules).
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = if (System.getenv("SVCS_ANDROID_KEYSTORE") != null) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
            buildConfigField("boolean", "ENABLE_HTTP_LOG", "false")
        }
        // FALL 3.2: a build that behaves like release for R8/minification
        // purposes (so it actually catches the same stripping bugs a real
        // release build would), but keeps HTTP logging on. Point of this:
        // a failing request on a minified build used to just be a mystery
        // (Level.NONE, nothing to look at); "qa" gives a tester or teammate
        // a build they can sideload next to release and read logcat on.
        // Never ships as a GitHub release asset; it is a local/testing
        // build type only.
        // Author: Bloodawn (KheivenD), 2026-09-22 (Fall 3.2).
        create("qa") {
            initWith(getByName("release"))
            applicationIdSuffix = ".qa"
            versionNameSuffix = "-qa"
            isDebuggable = true
            matchingFallbacks += listOf("release")
            buildConfigField("boolean", "ENABLE_HTTP_LOG", "true")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        // BuildConfig is needed so release code can assert on isDebuggable
        // when deciding whether any HTTP logging is permitted at all.
        buildConfig = true
    }
    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    // 1.0.0-beta: LiteRT (Smart Compress) ships a native .so per CPU
    // architecture, and one APK carrying all four roughly doubled the
    // download. Splitting gives phones a much smaller arm64-v8a APK (every
    // 64-bit Android phone from the last several years) while the universal
    // APK stays available for 32-bit phones and x86_64 emulators. Same
    // versionCode on every split is fine for sideloading and for F-Droid,
    // which builds from source itself; Play would need distinct codes.
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = true
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.androidx.datastore.preferences)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.kotlinx.serialization.json)
    // M2.1: thumbnails. Coil is given the app's OkHttp client so thumbnail
    // requests carry the same Bearer token, and disk caching is disabled at
    // the call site: these are frames of real people and must not be written
    // to the phone's storage.
    implementation(libs.coil.compose)

    // M3: LIVE tab. media3-datasource-okhttp is what carries the Bearer token
    // onto the .ts segment requests, which are separate HTTP calls from the
    // playlist and are 401 without it.
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.exoplayer.hls)
    implementation(libs.media3.ui)
    implementation(libs.media3.datasource.okhttp)

    // Standalone compressor (Fall roadmap Phase 1): hardware-accelerated
    // transcode via Media3 Transformer/MediaCodec, no bundled FFmpeg.
    implementation(libs.media3.transformer)
    implementation(libs.media3.effect)
    implementation(libs.androidx.work.runtime.ktx)

    // Fall roadmap Phase 2: on-device detection for "Smart Compress".
    implementation(libs.litert)

    testImplementation(libs.junit)
    testImplementation(libs.robolectric)
    testImplementation(libs.kotlinx.coroutines.test)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
