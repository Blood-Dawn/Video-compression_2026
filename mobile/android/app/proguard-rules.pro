# kotlinx.serialization keeps the @Serializable models reachable.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class org.svcs.mobile.net.** {
    *** Companion;
}
-keepclasseswithmembers class org.svcs.mobile.net.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# OkHttp ships these platform hints.
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
