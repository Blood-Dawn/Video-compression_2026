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
        versionCode = 8
        versionName = "0.5.0-beta"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
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

    testImplementation(libs.junit)
    testImplementation(libs.robolectric)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
