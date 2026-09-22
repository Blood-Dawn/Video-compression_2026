# Push notifications while the app is closed (R6 Track C)

SVCS can tell your phone about a line crossing or a finished compression even
when the SVCS app is not running. It does that without a third-party push
service: your SERVER posts a short message to an [ntfy](https://ntfy.sh/docs/)
topic that YOU host, and the ntfy client on your phone wakes up and shows it.

The feature is off until you turn it on, and there is no default server baked
in. With no topic URL configured, SVCS never opens a socket for this.

## What this fixes

The mobile app's own notifications (M5) are polled by the app process. Android
kills that process when you swipe the app away or when the battery optimiser
decides to, and polled notifications stop with it. Closed-app delivery needs
something outside the app to wake it, which in practice means a push service.
The usual answer is Firebase Cloud Messaging, which would route every alert
about your property through Google. ntfy is the self-hosted answer.

## Step 1: run an ntfy server

Anywhere your phone can reach. The same machine as SVCS is fine.

Docker:

    docker run -d --name ntfy -p 8080:80 -v /var/lib/ntfy:/var/lib/ntfy \
      binwiederhier/ntfy serve

Binary: download the release for your OS from the ntfy project, then

    ntfy serve --listen-http :8080

Confirm it answers:

    curl -d "hello" http://localhost:8080/test

## Step 2: pick a topic name nobody can guess

On a default ntfy install ANY client that knows the topic name can read it, and
topics are created on first use. That makes the topic name the password. Use
something long and random:

    svcs-a7f3c9d2e1b4

Not `svcs`, not `home`, not `alerts`.

If you would rather have real authentication, ntfy supports access control and
tokens. Create a token in ntfy, restrict the topic to it, and paste the token
into the SVCS access-token field. SVCS sends it as `Authorization: Bearer ...`.

## Step 3: point SVCS at the topic

Desktop: the TOOLS tab, `PHONE ALERTS WHILE THE APP IS CLOSED`. Type the topic
URL, press `Send test`, then tick the switch and press `Save`.

Phone: the MORE tab, `PHONE ALERTS` section. Same fields, same server setting.

API, if you prefer:

    curl -X POST http://<svcs-host>:5000/api/push/config \
      -H "Content-Type: application/json" \
      -d '{"enabled": true, "topic_url": "http://192.168.1.50:8080/svcs-a7f3c9d2e1b4"}'

    curl -X POST http://<svcs-host>:5000/api/push/test \
      -H "Content-Type: application/json" -d '{}'

`GET /api/push/config` reads the settings back. It reports `has_token` as a
boolean and never returns the token itself, so a client can edit the other
fields without ever holding the secret. Omit the `token` key to keep the stored
one; send `"token": ""` to clear it.

## Step 4: subscribe on the phone

Install the ntfy app (Play Store, or F-Droid if you would rather not use Play
Services). In the app:

1. Settings, `Default server`, set it to your `http://192.168.1.50:8080`.
2. `+`, `Subscribe to topic`, enter your topic name.
3. Turn on `Instant delivery` for that subscription. Without it the app polls
   roughly every 15 minutes, which is not what you want for a fence line.

Instant delivery holds one long-lived connection to your server, so the phone
must be able to reach it. On the LAN that is automatic. From outside, expose
ntfy through your own reverse proxy or VPN, not by port-forwarding SVCS.

Then press `Send test` in SVCS. The phone should buzz within a second or two.

## What gets sent

Behavior events, priority high:

    Title:  SVCS: line crossed
    Body:   A person crossed at front_gate heading right on cam_00.

    Title:  SVCS: loitering
    Body:   A person is loitering in driveway for 41s on cam_00.

Finished jobs, normal priority:

    Title:  SVCS: compression finished
    Body:   highway.mp4 finished in 42.3s, 209.8 MB to 29.6 MB, 86 percent saved.

    Title:  SVCS: compression failed
    Body:   cam_00 failed in 3.1s: <the error>

Each kind has its own switch, so you can have fence alerts without job chatter
or the other way round.

A single batch of events sends at most five messages and then one summary line
saying how many more were recorded. The event engine already debounces each
(event kind, geometry) pair, so a person walking a fence line does not produce
a burst.

## What is deliberately NOT sent

* No plate text. The plate reader's output never reaches a notification.
* No file paths and no camera credentials.
* No image, no clip, no crop. The message is text only.

An alert says what kind of thing happened, on which camera, in which zone. To
see the footage you open SVCS.

## Safety rules the server enforces

The topic URL is operator-supplied and gets fetched by the server, which is the
classic server-side request forgery shape. The pipeline's input-source guard
(SEC-013) is the wrong tool here because it refuses nothing on the LAN, and the
LAN is exactly where a self-hosted ntfy lives. So this feature has its own
guard, in `src/utils/push_notify.py`:

* http and https only. `file:`, `ftp:`, `gopher:` and friends are refused.
* Loopback, RFC1918, and unique-local addresses are ALLOWED. They are the point.
* Cloud instance-metadata targets are refused: link-local `169.254.0.0/16` and
  `fe80::/10`, the Alibaba `100.100.100.100` literal, the AWS `fd00:ec2::254`
  address, and the `metadata`, `metadata.google.internal` hostnames.
* Hostnames are checked AFTER DNS resolution, so a friendly name that resolves
  to a metadata address is refused too.
* IPv4-mapped IPv6 forms are unwrapped before the check, so
  `::ffff:169.254.169.254` cannot slip past.
* Redirects are never followed. A permitted host cannot bounce the request onto
  a refused one.
* Credentials embedded in the URL are refused. Use the token field.
* Title, tags, and priority are carried as HTTP headers, so control characters
  are stripped out of them before the request is built.

Delivery runs on one daemon worker behind a bounded queue with a 3 second
timeout. If your ntfy server is down or slow, the encode does not notice.

## Where the settings live

`push_config.json` in the SVCS state directory, next to the Flask secret:

* Windows: `%LOCALAPPDATA%\SVCS\SVCS\`
* macOS: `~/Library/Application Support/SVCS/`
* Linux: `~/.local/share/SVCS/`

It is written `0o600` where the OS supports it, because it can hold a token.
This is why it is a separate file rather than a key in `gui_state.json`, which
is documented as holding paths and no secrets.

## Troubleshooting

`Test failed: could not reach the topic`
The server cannot open a TCP connection. Check the ntfy port, and check the
address is one the SVCS MACHINE can reach, not one only the phone can.

`Test failed: blocked link-local address` or `blocked cloud-metadata address`
You pointed it at a metadata endpoint. That is the guard doing its job.

`Test failed: no topic in the URL path`
`http://192.168.1.50:8080` is a server, not a topic. Add the topic:
`http://192.168.1.50:8080/svcs-a7f3c9d2e1b4`.

`Test failed: HTTP 403`
The topic requires auth. Create a token in ntfy and paste it into the access
token field.

Test works but the phone stays quiet
The phone is not subscribed to that exact topic, or instant delivery is off, or
the phone cannot reach the ntfy server from its current network.

## Why not UnifiedPush natively, yet

The SVCS app could speak UnifiedPush itself and drop the separate ntfy app.
That means registering with a distributor, holding a distributor-issued
endpoint per install, and handling re-registration when the distributor changes,
which is real state to get right. The ntfy app already does all of it correctly
and costs zero lines of code here, so that is the first slice. Native
UnifiedPush stays on the list.

Author: Bloodawn (KheivenD), 2026-08-17 (R6 TRACK C).
