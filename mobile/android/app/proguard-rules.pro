# TSAR Mobile — ProGuard Rules
# ────────────────────────────────────────────────────────────────
# Flutter-specific rules
-keep class io.flutter.app.** { *; }
-keep class io.flutter.plugin.** { *; }
-keep class io.flutter.util.** { *; }
-keep class io.flutter.view.** { *; }
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }

# Keep annotations
-keepattributes *Annotation*

# Keep source file names for stack traces
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Prevent stripping of generic type info (needed for JSON parsing)
-keepattributes Signature

# Keep HTTP/TLS classes
-keep class javax.net.ssl.** { *; }
-dontwarn javax.net.ssl.**
