# Building the Android client (app/)

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@17   # JDK 17
export ANDROID_HOME=$HOME/Library/Android/sdk   # NDK 27+ required
cd app
./gradlew assembleRelease
# sign with your own keystore:
zipalign -f 4 app/build/outputs/apk/release/app-release-unsigned.apk out.apk
apksigner sign --ks your.keystore --out ZerotierFix-signed.apk out.apk
```

The upstream project's CI can also build it: see `.github/workflows/` (upstream).

Our changes vs upstream `kaaass/ZerotierFix`:

- `MoonOrbitFragment` — per-moon Switch; toggling fires `ToggleMoonEvent` (runtime-only orbit/deorbit, entry preserved, state in SharedPreferences)
- `ZeroTierOneService` — `onToggleMoon` handler
- `NetworkListFragment` — moon replay filters disabled entries
- `PrefsFragment` — custom planet file accepts moon header (0x7f) in addition to planet (0x01)
