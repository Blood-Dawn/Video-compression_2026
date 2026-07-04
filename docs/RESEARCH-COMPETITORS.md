# RESEARCH: competitor surveillance apps + gap analysis (R4 Phase 3)

Date: 2026-07-04. Method: deep-research workflow (5 angles, 104 agents, 22
sources, 25 claims verified 3-vote: 24 confirmed, 1 refuted). Mapped against
the ground-truth SVCS feature inventory (docs/SVCS-FEATURE-INVENTORY.md).
NOTE: the workflow's auto-synthesis field returned a stub; this document is the
hand-synthesis from the verified claim set + source list.

## Verified competitor behaviors (confirmed claims)
- **Retention / auto-purge** - ZoneMinder ships a pre-configured `PurgeWhenFull`
  filter that deletes oldest events by DiskPercent / DiskBlocks thresholds
  (ring-buffer). Frigate supports separate retention TIERS (alerts vs
  detections vs continuous) each with an independent retain-days setting.
  Sources: wiki.zoneminder.com/PurgeWhenFull (3-0 x2), docs.frigate.video
  /configuration/record (3-0 x2). Retention math days = disk / bitrate is the
  standard user-facing model (reolink storage calc).
- **Smart-codec dynamic ROI + dynamic GOP** - Axis Zipstream and Dahua Smart
  H.265+ cut bitrate by dynamic ROI (encode motion regions at higher quality)
  and dynamic GOP (extend I-frame interval on static scenes); Dahua claims
  89-98% reduction (2-1, vendor figure). Sources: whitepapers.axis.com,
  Dahua Smart H.265+ PDF (3-0 on ROI, 2-1 on the % figures).
- **Event/alert pipelines** - Frigate publishes detection events over MQTT and
  drives Home Assistant notifications; On-Guard (a Blue Iris companion) adds AI
  object detection and multiple overlapping zones. Sources: docs.frigate.video
  (ha_notifications, mqtt, home-assistant - 3-0 x4), github On-Guard (3-0 x2).
- **Interop** - ONVIF Profile G covers recording/replay; the client (VMS) role
  retrieves recordings; ONVIF Replay Control uses RTSP as the retrieval
  protocol. Sources: onvif.org profile-g + replay spec (3-0 x3).
- **Privacy/compliance + export** - Milestone XProtect offers privacy masking,
  audit logs, and an encrypted+signed evidence export format. Sources:
  doc.milestonesys.com (3-0 x3).
- Refuted (1-2): the exact Frigate MQTT topic-namespace claim (the docs do
  describe `frigate/<category>/<camera>/<function>`, but the vote fell short;
  treated as directional, not load-bearing).

## Gap analysis vs SVCS (ranked, impact x effort)

### ADOPT NOW - Retention / disk-budget / auto-purge (TABLE STAKES, #1)
The one feature EVERY NVR has and SVCS has NONE of. Directly serves SVCS's
purpose (bound 24/7 footage on disk). ZoneMinder PurgeWhenFull is the model.
IMPLEMENTED THIS PHASE: a retention policy (max age in days AND/OR max total GB)
over the auto-compressed output, a background purge that deletes oldest
compressed segments (+ prunes the index) when over budget, a
free-disk/bitrate retention ESTIMATE (days of headroom), and GUI controls.
Safety-first (it deletes footage): confined to the resolved `compressed/`
subdir, media files only, a freshness window so an in-flight clip is never
touched, originals/encrypted-source never touched, no-op when disabled.

### ALREADY DELIVERED (R4 Phase 2) - smart-codec dynamic ROI + dynamic GOP
The Zipstream / Smart H.265+ storage lever. SVCS added encoder-level addroi ROI
(protect motion, degrade long-static cells) and long-GOP defaults in Phase 2.
No further work; noted so it is not double-counted as a gap.

### DEFER - Event notifications (webhook / MQTT / Home Assistant)
Real gap (Frigate/On-Guard). Deferred to keep Phase 3 focused and because a
safe outbound webhook needs SSRF guarding (post-to-internal risk) and MQTT
needs a broker dependency the local-first installer avoids. Recommended next:
a single opt-in outbound webhook (JSON POST on job-complete / purge), URL
vetted through the existing path_safety host checks. Recorded in BLOCKERS.

### OUT OF SCOPE (would make SVCS a full VMS, not a compressor)
- ONVIF Profile G recording/replay server, tiered/cloud storage.
- Timeline review UI (Phase 1 already deferred this; revisit post-split).
- Multi-user / RBAC + built-in HTTPS (documented answer: run behind a reverse
  proxy; single-node local-first tool).
- Encrypted+signed evidence export, privacy-mask zones (nice-to-have, large;
  SVCS already has AES-256 at-rest encryption).

## Honest caveats
- Dahua's 89-98% and the smart-codec % figures are vendor-measured (2-1 votes).
- Only Frigate / ZoneMinder / Axis / Dahua / Milestone / On-Guard claims
  survived; Blue Iris, Synology, Scrypted, Shinobi, MotionEye, Ubiquiti did not
  produce verified claims, so the competitor set is skewed to those six.
- Retention "days = disk / bitrate" is an ESTIMATE from recent throughput; real
  headroom varies with scene activity (night noise inflates bitrate).
