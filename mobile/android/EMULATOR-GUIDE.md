# Running an Android emulator (for testing SVCS Mobile)

This is for anyone working on this app who has never used an Android
emulator before. Short version: an emulator is a full virtual Android
phone that runs on your PC, the same idea as a VM running Windows or
Linux inside your main machine, except this one is a phone. You look at
its screen in a window, you click and type into it like a real phone
screen, and it keeps its own storage between launches, just like a real
device would.

You do not need a physical Android phone to build, install, and test this
app. Everything below runs entirely on your own computer.

## The easy way: Android Studio's Device Manager

This is the graphical path and needs no command line at all.

1. Open Android Studio and open the `mobile/android` folder from this
   repo as a project (if it is not already open).
2. Find the Device Manager. It is a phone-with-a-clock icon in the
   toolbar on the right edge of the window, or under the `Tools` menu as
   `Device Manager` if the icon is not visible.
3. Click the `+` button (sometimes labeled `Create Device` or
   `Add a new device`) and choose `Create Virtual Device`.
4. Pick a phone. Any modern Pixel works fine (Pixel 5, Pixel 7, Pixel 8);
   the exact model does not matter for this app.
5. Pick a system image. Choose one from the `Recommended` tab that says
   `API 35`, to match this app's `compileSdk`/`targetSdk`. If it has a
   download icon next to it, click that first; the download is a few
   gigabytes and takes a few minutes.
6. Click through `Next` and then `Finish`. The new virtual device now
   shows up in the Device Manager list.
7. Click the green play (triangle) button next to it. A phone-shaped
   window opens on your screen. The very first boot takes a minute or
   two; after that it is much faster, because the emulator saves its
   state and resumes instead of booting cold every time.

That window is now a real Android device as far as this app (or any app)
can tell.

## How to actually use the thing once it is open

If you have never touched an emulator, none of this is obvious, so here
it is plainly:

- Click with the mouse where you would tap with a finger.
- Click and drag where you would swipe.
- Type on your real keyboard to fill in text fields; you do not need to
  use the on-screen keyboard, though it will pop up too.
- The row of icons on the side of the emulator window (or a thin toolbar
  along one edge) are the phone's back, home, and recent-apps buttons,
  plus volume, rotate, and a few emulator-only extras like screenshot
  and a settings gear. Hover over them if the icons are not obvious.
- Closing the emulator window is like putting a real phone to sleep, not
  turning it off: the app's data, and anything it had saved (like a
  paired server and its token), is still there next time you open it.
- If something gets weird and you want to start completely fresh, open
  the Device Manager, click the dropdown arrow next to the device, and
  choose `Wipe Data`. That resets it to a factory-new phone.

## Installing the SVCS app on it

Three ways, pick whichever is easiest in the moment:

1. **From Android Studio**: with the emulator running, click the green
   `Run` (play) button in Android Studio's main toolbar. It builds,
   installs, and launches the app on whichever emulator (or device) is
   currently selected in the dropdown next to that button.
2. **Drag and drop**: with the emulator window open, drag a built `.apk`
   file (for example `app/build/outputs/apk/debug/app-debug.apk`, or a
   release APK like the ones built for GitHub releases) and drop it
   straight onto the emulator window. It installs automatically.
3. **Command line**, if you are already in a terminal:
   ```powershell
   cd mobile/android
   .\gradlew.bat installDebug
   ```
   This builds the debug variant and installs it on whichever emulator
   or device is currently running. `adb install -r path\to\some.apk`
   works too, for a specific APK file you already have (`-r` means
   reinstall over an existing copy, keeping its data).

## The one gotcha that matters for THIS app: pairing against your own PC

SVCS Mobile pairs against a server by IP address. If the server you want
to test against is running on the same computer as the emulator (the
normal case while developing), do **not** enter `127.0.0.1` or
`localhost`. Inside the emulator, those addresses mean "the emulator
itself," not your real PC, because the emulator is its own virtual
computer on its own virtual network.

Instead, use the special address `10.0.2.2`. That is a fixed alias the
emulator provides that always means "the host machine," i.e. your actual
PC. So if your server is running with:

```
python run_gui.py --host 0.0.0.0 --username you --password <strong>
```

pair the app inside the emulator against `http://10.0.2.2:5000`, not
`http://127.0.0.1:5000` and not your PC's real LAN IP (though the real
LAN IP also works, since the emulator can reach your actual network too;
`10.0.2.2` is just the simplest option when everything is on one machine).

If you are instead testing against a real server on your LAN from a real
phone (not the emulator), use that server's real LAN IP as usual, the
same as the main README describes.

## Command line reference (optional)

Everything above can also be done from a terminal, which is how this was
first set up and verified while diagnosing Week 4 tasks 4.1/4.2. This is
not necessary if the Android Studio path above works for you; it is here
for reference or for scripting.

```powershell
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"

# One-time: install a system image (skip if you already made an AVD
# through Android Studio above; this is the same thing, no GUI).
& "$env:ANDROID_HOME\cmdline-tools\latest\bin\sdkmanager.bat" `
  "system-images;android-35;google_apis;x86_64"

# One-time: create the virtual device.
& "$env:ANDROID_HOME\cmdline-tools\latest\bin\avdmanager.bat" create avd `
  -n svcs_test -k "system-images;android-35;google_apis;x86_64" -d pixel_5

# Every time: start it. Drop -no-window to see the phone screen; keep it
# for a lighter-weight, invisible instance (useful for running
# instrumented tests without a window popping up).
& "$env:ANDROID_HOME\emulator\emulator.exe" -avd svcs_test -no-window -no-audio -no-boot-anim

# Confirm it is up and ready.
& "$env:ANDROID_HOME\platform-tools\adb.exe" devices
& "$env:ANDROID_HOME\platform-tools\adb.exe" shell getprop sys.boot_completed   # prints 1 once booted

# Run the instrumented tests against it (real device APIs, not the JVM
# fakes the regular unit tests use).
.\gradlew.bat connectedDebugAndroidTest
```

A `svcs_test` AVD matching the exact commands above may already exist on
this machine from earlier Week 4 work; the Device Manager in Android
Studio will show it in its list too, since both tools point at the same
SDK.

## Why bother with an emulator instead of just using a real phone

A real phone is still the better final check, and this project's own
verification notes lean on one. But an emulator is faster to iterate
with (no cable, no "enable USB debugging" dance, resets instantly), it
is what the instrumented tests (`connectedDebugAndroidTest`, including
`TokenStorePersistenceTest`) can run against without anyone's physical
device attached, and it is the same real Android runtime under the hood,
not a simulation, so a pass here is a real pass, not a JVM-faked one.
