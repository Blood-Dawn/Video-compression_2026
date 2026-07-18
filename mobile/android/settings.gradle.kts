// SVCS Mobile (Android) - Gradle settings.
//
// Standalone Gradle build living inside the Python repo. It is NOT wired into
// scripts/run_tests.ps1: the Python suite must stay runnable on a machine with
// no JDK and no Android SDK, which is the common case for this project.
//
// Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).

pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "SVCS"
include(":app")
