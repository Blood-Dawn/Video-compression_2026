# SVCS Mobile R8 keep rules.
#
# History (0.3.0, 2026-08-16): the first minified release rendered a BLACK
# screen on the physical device - frames drew, nothing composed, no exception
# logged - because the kotlinx-serialization rules below were incomplete: the
# generated ...$$serializer classes and the generic Signature attribute were
# stripped, decoding silently produced defaulted/empty models, and the UI had
# nothing to draw. These are the complete rules, and 0.5.0 re-enables
# minification ONLY together with a physical-device verification pass.
# Author: Bloodawn (KheivenD), 2026-08-17 (R8 keep rules).

# Attributes serializers and reflective generics depend on.
-keepattributes *Annotation*, InnerClasses, Signature, EnclosingMethod

# kotlinx.serialization: keep the GENERATED serializer classes wholesale, the
# Companion fields they are reached through, and the serializer() factories.
-dontnote kotlinx.serialization.**
-keep,includedescriptorclasses class org.svcs.mobile.**$$serializer { *; }
-keepclassmembers class org.svcs.mobile.** {
    *** Companion;
}
-keepclasseswithmembers class org.svcs.mobile.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}

# OkHttp ships these platform hints.
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
