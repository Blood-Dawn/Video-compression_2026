# Running SVCS on this machine, start to finish

Everything below is PowerShell from the repo root:
`C:\Users\kheiven\Documents\GitHub\Video-compression_2026`

## 1. Start the dashboard

**Local only, no login.** Use this when you just want the dashboard on this
machine.

```powershell
.\.venv\Scripts\python.exe run_gui.py --host 127.0.0.1
```

A browser opens on http://127.0.0.1:5000 by itself.

**On the LAN, so the phone can reach it.** The server REFUSES to start on a
non-loopback bind with no credentials, by design, because it serves recorded
video of real people over plain HTTP. So set them:

```powershell
$env:SVCS_DASHBOARD_USER = 'bloodawn'
$env:SVCS_DASHBOARD_PASSWORD = (Get-Content .e2e_test_pass.txt -Raw).Trim()
.\.venv\Scripts\python.exe run_gui.py --no-browser
```

Default host is 0.0.0.0, default port 5000. From the phone that is
`http://<this machine's LAN IP>:5000`. Find the IP with:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like 'Wi-Fi*' } | Select-Object IPAddress
```

Use `.venv`, never `venv`. Stop the server by closing its window, or:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run_gui.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## 2. Start ntfy, for alerts while the app is closed

Only needed for the R6 Track C push feature. Skip it if you do not want phone
alerts. Full background is in `docs/architecture/PUSH-NOTIFICATIONS.md`.

Docker, which survives reboots:

```powershell
docker run -d --name ntfy --restart unless-stopped -p 8080:80 `
  -v C:\ntfy:/var/lib/ntfy binwiederhier/ntfy serve `
  --base-url http://<LAN IP>:8080
```

Or the plain binary, if you would rather not run Docker. Copy `ntfy.exe`
somewhere permanent (the 2.23.0 Windows release unpacks to a single exe), then:

```powershell
C:\tools\ntfy\ntfy.exe serve --listen-http :8080 --base-url http://<LAN IP>:8080
```

Check it answers:

```powershell
(Invoke-WebRequest -Uri 'http://127.0.0.1:8080/v1/health' -UseBasicParsing).Content
```

Topic in use as of 2026-08-17: `svcs-8004e25151f2`. The topic name is the only
thing protecting it on a default ntfy install, so treat it as a password and do
not shorten it.

On the phone, the ntfy app needs Default server set to `http://<LAN IP>:8080`,
the topic subscribed, and Instant delivery turned ON for that subscription.
Without instant delivery it polls every 15 minutes, which is useless for a
fence line.

## 3. Point SVCS at the topic

TOOLS tab, `PHONE ALERTS WHILE THE APP IS CLOSED`. Type the topic URL, press
Send test, then tick the switch and press Save. Or from the command line:

```powershell
$pw = (Get-Content .e2e_test_pass.txt -Raw).Trim()
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("bloodawn:$pw"))
$h = @{ Authorization = "Basic $b64"; 'Content-Type' = 'application/json' }
$body = '{"enabled":true,"topic_url":"http://<LAN IP>:8080/svcs-8004e25151f2"}'
Invoke-WebRequest -Uri 'http://<LAN IP>:5000/api/push/config' -Method POST -Headers $h -Body $body -UseBasicParsing
```

The setting lives in `%LOCALAPPDATA%\SVCS\SVCS\push_config.json` and survives
restarts. It does NOT survive a factory reset from the Setup page.

## 4. Pair a phone

There is no token UI on the dashboard yet, so mint one over the API:

```powershell
$pw = (Get-Content .e2e_test_pass.txt -Raw).Trim()
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("bloodawn:$pw"))
$h = @{ Authorization = "Basic $b64"; 'Content-Type' = 'application/json' }
$r = Invoke-WebRequest -Uri 'http://<LAN IP>:5000/api/auth/tokens' -Method POST `
     -Headers $h -Body '{"label":"my phone"}' -UseBasicParsing
($r.Content | ConvertFrom-Json).token
```

It is shown once. In the app: MORE tab, SERVER ADDRESS and ACCESS TOKEN, then
TEST CONNECTION, then SAVE & OPEN.

Known issue as of 0.9.0-beta: the save does not always persist across an app
restart, so a re-pair can silently revert. See the project note on it.

## 5. Run the tests

```powershell
pwsh scripts/run_tests.ps1
```

Or a targeted run. Always give a UNIQUE basetemp: two runs sharing one corrupt
each other and invent failures.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_push_notify.py `
  --basetemp=.pytest_tmp_mine -p no:cacheprovider -q
```

## 6. Build the Android APK

```powershell
$env:SVCS_ANDROID_KEYSTORE = "$env:USERPROFILE\.svcs\svcs-release.jks"
$env:SVCS_ANDROID_KS_PASS  = '<see keystore-credentials.txt next to the keystore>'
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot'
cd mobile\android
.\gradlew.bat assembleRelease
```

Run it detached and read a log file rather than watching the pipeline. Piping
gradle through `Select-Object -First N` KILLS the build partway and leaves a
stale APK sitting there looking successful. Always check the timestamp before
installing:

```powershell
Get-Item mobile\android\app\build\outputs\apk\release\app-release.apk |
  Select-Object LastWriteTime, Length
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r `
  mobile\android\app\build\outputs\apk\release\app-release.apk
```

## 7. Things that will bite you

* **Auth throttle.** Ten failed attempts from one address locks that address
  for 300 seconds. A phone holding a stale token spends that budget in about
  25 seconds. Restarting the server clears it instantly.
* **Restart after server code changes.** The Flask server does not hot-reload,
  and the phone briefly gets 401s across a restart while its pollers retry.
* **DHCP.** If the machine's LAN IP changes, both the phone's pairing address
  and the ntfy topic URL need updating.
* **Factory reset really is one.** The Setup page's reset deletes
  `device_tokens.json` and unpairs every phone permanently.
* **The dashboard on port 5001.** Handy for browser testing without touching
  the LAN server: `run_gui.py --host 127.0.0.1 --port 5001 --no-browser --no-sync --no-auth`

Author: Bloodawn (KheivenD), 2026-08-17.
