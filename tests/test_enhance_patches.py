"""Enhancement must never replace the live frame with an older one."""
import numpy as np
from types import SimpleNamespace as R

from src.pipeline.pipeline import _enhance_patches, _iou, _paste_patches


class _FakeEnhancer:
    def upscale_roi(self, frame, bbox):
        x, y, w, h = bbox
        out = frame.copy()
        out[y:y + h, x:x + w] = 200
        return out


def test_iou_basics():
    assert _iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert _iou((0, 0, 10, 10), (20, 20, 5, 5)) == 0.0


def test_patches_only_cover_regions():
    frame = np.zeros((100, 100, 3), np.uint8)
    patches = _enhance_patches(frame, [R(x=10, y=10, w=20, h=20)], _FakeEnhancer())
    assert len(patches) == 1 and patches[0][:4] == (10, 10, 20, 20)
    assert (patches[0][4] == 200).all()


def test_paste_keeps_current_frame_outside_the_patch():
    old = np.zeros((100, 100, 3), np.uint8)
    patches = _enhance_patches(old, [R(x=10, y=10, w=20, h=20)], _FakeEnhancer())
    current = np.full((100, 100, 3), 77, np.uint8)       # a NEWER frame
    out = _paste_patches(current, patches, [R(x=12, y=12, w=20, h=20)])
    assert (out[10:30, 10:30] == 200).all()              # patch applied
    assert (out[50:, 50:] == 77).all()                   # live pixels untouched, not stale


def test_paste_skips_patch_when_object_moved_on():
    old = np.zeros((100, 100, 3), np.uint8)
    patches = _enhance_patches(old, [R(x=10, y=10, w=20, h=20)], _FakeEnhancer())
    current = np.full((100, 100, 3), 77, np.uint8)
    out = _paste_patches(current, patches, [R(x=70, y=70, w=20, h=20)])
    assert out is current
