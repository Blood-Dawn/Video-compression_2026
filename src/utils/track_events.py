"""
src/utils/track_events.py - behavior events on tracked objects (R5 TASK 5.7).

Raises events from classified, TRACKED objects rather than raw pixel motion,
which is what makes analytics fire on a person crossing a fence line instead
of on wind, rain, and headlights. Three behaviors, per the R5 spec:

* line-crossing: a track's center crosses a user-defined line (with the
  crossing DIRECTION, from the sign of the cross product before/after);
* loitering: a track dwells inside a zone past a time threshold;
* direction: the track's dominant movement vector, reported with events.

Deliberately dependency-free (pure Python, no numpy) so it unit-tests with
synthetic tracks and adds zero import weight to the slim build. Geometry is
NORMALIZED (0..1 relative to frame size) so a config survives resolution
changes - the same convention the R5 zone-mask task uses.

Debounce: one object must not emit a burst of duplicate events. A track can
emit each (event type, geometry id) pair at most once per ``debounce_s``.

Author: Bloodawn (KheivenD), 2026-08-17 (R5 TASK 5.7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── geometry ─────────────────────────────────────────────────────────────────


def _iou(a: tuple, b: tuple) -> float:
    """Intersection-over-union of two xyxy boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center(box: tuple) -> tuple:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _side_of_line(p: tuple, line: tuple) -> float:
    """Signed side of point p relative to the line (x1,y1)->(x2,y2).

    Positive on one side, negative on the other; the sign FLIP between two
    consecutive centers is a crossing, and which sign it flips TO is the
    crossing direction.
    """
    (x1, y1, x2, y2) = line
    return (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)


def _in_rect(p: tuple, rect: tuple) -> bool:
    x1, y1, x2, y2 = rect
    return (min(x1, x2) <= p[0] <= max(x1, x2)
            and min(y1, y2) <= p[1] <= max(y1, y2))


# ── tracking ─────────────────────────────────────────────────────────────────


@dataclass
class Track:
    track_id: int
    box: tuple
    label: str = ""
    age: int = 0
    misses: int = 0
    centers: list = field(default_factory=list)
    zone_entered_at: dict = field(default_factory=dict)   # zone id -> time
    emitted: dict = field(default_factory=dict)           # (kind, gid) -> time

    def direction(self) -> Optional[str]:
        """Dominant compass-ish direction over the track's life, or None."""
        if len(self.centers) < 2:
            return None
        dx = self.centers[-1][0] - self.centers[0][0]
        dy = self.centers[-1][1] - self.centers[0][1]
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return None
        if abs(dx) >= abs(dy):
            return "right" if dx > 0 else "left"
        return "down" if dy > 0 else "up"


class EventEngine:
    """Greedy-IOU tracker + the three R5 behaviors.

    lines: [{"id": str, "line": (x1,y1,x2,y2)}]           (normalized)
    zones: [{"id": str, "rect": (x1,y1,x2,y2)}]           (normalized)
    loiter_s: dwell threshold before a loiter event fires.
    debounce_s: minimum spacing of identical events from one track.
    class_filter: only these labels raise events (empty = all). Line-crossing
    with a class filter is the reliable workhorse; motion blobs never reach
    this engine at all.
    """

    def __init__(self, lines=None, zones=None, loiter_s: float = 30.0,
                 debounce_s: float = 5.0, iou_threshold: float = 0.25,
                 max_misses: int = 10, class_filter=None):
        self.lines = list(lines or [])
        self.zones = list(zones or [])
        self.loiter_s = float(loiter_s)
        self.debounce_s = float(debounce_s)
        self.iou_threshold = float(iou_threshold)
        self.max_misses = int(max_misses)
        self.class_filter = set(class_filter or [])
        self.tracks: list[Track] = []
        self._next_id = 1

    # ── the per-frame step ───────────────────────────────────────────────
    def step(self, boxes: list, t: float, labels: Optional[list] = None) -> list:
        """Advance one frame. boxes are normalized xyxy; t is seconds.

        Returns the events raised THIS frame, each:
        {"kind": "line_crossing"|"loitering", "track_id", "label", "t",
         "geometry_id", "direction"}
        """
        labels = list(labels or [""] * len(boxes))
        # Pass 1: greedy IOU matching. Pass 2: a center-distance fallback for
        # fast movers - an object that moves more than its own width between
        # frames has ZERO overlap with itself, and without the fallback every
        # such step minted a fresh track (and a fresh crossing event) instead
        # of continuing the old one.
        unmatched = list(range(len(boxes)))
        pairs = []
        pending = []
        for tr in self.tracks:
            best_j, best_v = -1, self.iou_threshold
            for j in unmatched:
                v = _iou(tr.box, tuple(boxes[j]))
                if v > best_v:
                    best_j, best_v = j, v
            if best_j >= 0:
                pairs.append((tr, best_j))
                unmatched.remove(best_j)
            else:
                pending.append(tr)
        for tr in pending:
            tw = max(tr.box[2] - tr.box[0], tr.box[3] - tr.box[1])
            reach = max(tw * 2.5, 0.05)  # a couple of body-widths per frame
            tc = _center(tr.box)
            best_j, best_d = -1, reach
            for j in unmatched:
                c = _center(tuple(boxes[j]))
                d = ((c[0] - tc[0]) ** 2 + (c[1] - tc[1]) ** 2) ** 0.5
                if d < best_d:
                    best_j, best_d = j, d
            if best_j >= 0:
                pairs.append((tr, best_j))
                unmatched.remove(best_j)
            else:
                tr.misses += 1
                # Loitering demands CONTINUOUS observed presence: a coasting
                # (miss-frame) track cannot vouch that the object stayed in
                # the zone, so its dwell clock resets rather than silently
                # surviving the gap and firing on re-acquisition.
                tr.zone_entered_at.clear()
        for tr, j in pairs:
            tr.box = tuple(boxes[j])
            tr.label = labels[j] or tr.label
            tr.age += 1
            tr.misses = 0
            tr.centers.append(_center(tr.box))
        for j in unmatched:
            tr = Track(self._next_id, tuple(boxes[j]), labels[j])
            tr.centers.append(_center(tr.box))
            self._next_id += 1
            self.tracks.append(tr)
        self.tracks = [tr for tr in self.tracks if tr.misses <= self.max_misses]

        events = []
        for tr in self.tracks:
            if tr.misses > 0:
                continue
            if self.class_filter and tr.label not in self.class_filter:
                continue
            events.extend(self._line_events(tr, t))
            events.extend(self._loiter_events(tr, t))
        return events

    # ── behaviors ────────────────────────────────────────────────────────
    def _debounced(self, tr: Track, kind: str, gid: str, t: float) -> bool:
        """True if this event may fire now; records the emission time."""
        key = (kind, gid)
        last = tr.emitted.get(key)
        if last is not None and (t - last) < self.debounce_s:
            return False
        tr.emitted[key] = t
        return True

    def _line_events(self, tr: Track, t: float) -> list:
        if len(tr.centers) < 2:
            return []
        prev_c, cur_c = tr.centers[-2], tr.centers[-1]
        out = []
        for ln in self.lines:
            s1 = _side_of_line(prev_c, tuple(ln["line"]))
            s2 = _side_of_line(cur_c, tuple(ln["line"]))
            if s1 == 0 or s2 == 0 or (s1 > 0) == (s2 > 0):
                continue
            if not self._debounced(tr, "line_crossing", str(ln["id"]), t):
                continue
            out.append({
                "kind": "line_crossing", "track_id": tr.track_id,
                "label": tr.label, "t": t, "geometry_id": str(ln["id"]),
                "direction": tr.direction(),
                "side": "positive" if s2 > 0 else "negative",
            })
        return out

    def _loiter_events(self, tr: Track, t: float) -> list:
        out = []
        cur_c = tr.centers[-1]
        for zn in self.zones:
            zid = str(zn["id"])
            if _in_rect(cur_c, tuple(zn["rect"])):
                entered = tr.zone_entered_at.setdefault(zid, t)
                if (t - entered) >= self.loiter_s:
                    if self._debounced(tr, "loitering", zid, t):
                        out.append({
                            "kind": "loitering", "track_id": tr.track_id,
                            "label": tr.label, "t": t, "geometry_id": zid,
                            "direction": tr.direction(),
                            "dwell_s": round(t - entered, 2),
                        })
            else:
                tr.zone_entered_at.pop(zid, None)
        return out
