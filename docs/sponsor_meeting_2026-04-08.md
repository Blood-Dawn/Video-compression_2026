# Sponsor meeting notes — April 8, 2026
Cody Hayashi, DIU / NIWC Pacific
Kheiven D'Haiti

---

## Do these two things before the call

**1. Restart the dashboard.** There's probably an old version still running. Kill it and run this fresh:
```
python run_gui.py
```

**2. Change the video source.** The dashboard defaults to `data/test_clip.mp4` which doesn't exist on your machine. When it opens, hit the little ⟳ scan button and pick one of these:
- `data/samples/pedestrians_input.mp4` — small file, loads fast, good for a quick demo
- `data/samples/highway_input.mp4` — better for showing vehicles (12MB though, gives it a sec)
- `data/samples/parking_input.mp4` — best for showing Mode 1 because it's mostly static

Have the browser open at `http://localhost:5000` before you join the call, not after.

---

## Is everything actually working?

Everything you need for today's demo is working. The layout has a small visual gap at the top — it's cosmetic, just a CSS thing, doesn't break anything. Move on if they notice it.

What's ready: Mode 0, Mode 1, the dashboard, encryption, the image sharpening, background detection (low light too), the metadata database, live log streaming.

What's not built yet: Mode 2 and 3. Don't click them.

---

## What the team has been up to (git check)

Nobody opened a PR. You're doing most of the talking.

Here's where everyone stands:

Riley Roberts pushed work on the motion-detection pipeline April 6. It's on its own branch, not merged yet. Victor did the benchmark numbers at Milestone 1. Jorge built the video encoding piece. Ashleyn built the database. Since then, everything new is yours.

---

## How to walk through the demo

Open the dashboard. Point out the sidebar on the left — that's where you set it up. The big cards in the middle show what's happening in real time: how many frames have been processed, how many clips have been saved, how fast it's going.

Hit START. The log on the bottom left will start filling up with live output — that's the pipeline running. After a minute or so, a row shows up in the table on the right: one saved clip, whether a person or vehicle was in it, how big the file is.

Then flip it to Mode 1 and explain the difference.

---

## What you built — what to say about each one

### The dashboard

Whoever's operating this doesn't need to touch a terminal. They open a browser, and that's it. You could put this on a TV in a security office. Nothing to install on the operator's machine — just a URL.

The live log at the bottom isn't decorative. It's streaming directly from the pipeline as it runs. If something goes wrong, you see it the second it happens.

### The two recording modes

Imagine a parking lot camera running 24 hours a day. 23 of those hours, nothing moves.

Mode 0 records all 24 hours. When a car pulls in, that clip gets saved at high quality. When the lot is empty, the footage gets compressed hard — it's still there, it just takes up almost no space. You're never missing anything.

Mode 1 only saves the 1 hour that had actual activity. Way smaller files. But you do have gaps, so if you need to prove nothing happened at 2am, you can't.

Cody can pick whichever one fits how his team operates.

The way we compress is interesting: the part of the frame where something is moving gets saved at near-perfect quality. The static background gets crushed. So a face or a license plate in a crowd stays readable even when the rest of the clip is tiny.

### Encryption

Every saved clip gets locked before it touches the disk. Nobody can watch it without the key — not even someone who steals the hard drive.

You can set it up with a passphrase or with a key file, which matters if they eventually want to plug this into a key management system at the government level.

### Image sharpening (super-resolution)

If a camera is old or low-res, we can run a sharpening pass on a clip when someone pulls it for review. It's a neural network that fills in missing detail — the output looks like you had a better camera to begin with. Not magic, but noticeably better on blurry license plates or faces.

It's optional. Good camera? Skip it. Slow hardware? Skip it. It's there when it's useful.

### The database

Every clip gets a row in a database automatically: which camera, what time, whether something was detected, how big the file is. If you're running 100 cameras and something happened at 3am, you're not scrubbing through 100 days of footage to find it. You query it.

---

## Their licensing note — what to say

They're worried about video format patents. Good news: we're not using the format they flagged.

They mentioned H.265 as the problem. We use H.264, which is the older, safer one. For a free open-source project like this, there's no licensing cost.

If they ever want to turn this into a product they sell, H.264 still needs a license check. The truly worry-free option is AV1, which Google and Apple backed specifically to avoid this problem. It encodes slower but costs nothing to use commercially.

Something like: "We looked at this when we were setting up the encoder. We went with H.264, not H.265, so we're already past the thing you flagged. If this ever needs to go commercial, AV1 is the move — it's free under any scenario, and swapping to it is literally one line in our config."

---

## Questions to ask them

On the licensing:
- "Does H.264 work for you, or do you want us to go AV1 to be completely safe even if this goes commercial someday?"
- "When you say 'free open source' takes care of it — does that hold if a contractor packages this and sells it as part of a larger system? Just want to know where the line is."

On deployment:
- "Did Gina get back to you on packaging format? We're ready to do Docker, a single executable, or just a zip with instructions — just need to know what works on your hardware."
- "What CPU and RAM are on the machines we're targeting? That changes whether real-time sharpening is even possible."
- "Windows or Linux, or both?"

On encryption:
- "With 100+ cameras, how does key management work on your end? Does each camera get its own key, or is there a central system that handles it?"

On what to build next:
- "We've got two more recording modes to finish before April 18. One stores just the moments something moved plus a background reference frame. The other strips everything except the moving object — smallest possible file, best for facial recognition pipelines. Which one matters more to you?"

On testing:
- "Is there any real footage we could get access to for testing? Even something anonymized would help us tune the detection."
- "Is there a specific bad scenario you want us to handle — pitch dark, a camera getting bumped, a crowded scene with lots of movement? Tell us what you're worried about and we'll make sure it works."

---

## Numbers if they ask

Don't lead with these. Only pull them out if Cody asks for specifics.

Mode 0 files end up about 6 to 8 times smaller than raw footage. Mode 1 gets to 12 to 20 times smaller — depends on how busy the scene is. The part of the frame where someone's walking or a car is pulling in stays near-perfect quality. The empty parking lot background behind them gets crushed.

A typical 60-second clip is somewhere between 0.5 MB and 6 MB.

---

## What's coming before April 18

If Cody asks about the roadmap:

- Two more recording modes (Riley is partway through one of them)
- Tagging clips by what was detected (person, vehicle) so you can search by type
- A multi-hour stress test to make sure nothing falls over overnight
- More automated tests so the codebase is easier to hand off

The hard deadline is May 6. That's when the full report and final demo happen.

---

*April 8, 2026 — Kheiven D'Haiti*
