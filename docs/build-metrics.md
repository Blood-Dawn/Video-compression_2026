# Build metrics — installer size

Tracks the unpacked PyInstaller bundle size (`dist/SVCS/`) as the M2 slimming
work progresses. Goal (PLAN-V2 §6/§8): get the installer download from
2.5–4.7 GB to ~400–600 MB by replacing PyTorch with ONNX Runtime — no rewrite.

Measure with:
```
uv run --no-sync pwsh installer/build.ps1 -Quick -SkipSmoke
# size = total bytes under dist/SVCS/
```

| Date | Build | Detection backend | torch in bundle | Unpacked dist/SVCS |
|---|---|---|---|---|
| 2026-06-02 | M1 (TASK 1.4), torch+ultralytics bundled | PyTorch | yes | **~4632 MB** |
| 2026-06-03 | M2 TASK 2.2, torch/ultralytics/CUDA excluded | ONNX Runtime | no | **339 MB** |

**Result: 4632 MB → 339 MB unpacked — a ~13.7× reduction**, comfortably under the
400–600 MB target, with ONNX detection working (onnxruntime + yolov8n.onnx
bundled, torch/CUDA gone) and the dashboard smoke test passing. The Inno Setup
*download* (TASK 2.4) will be smaller still once compressed and once the ONNX
weights become an optional first-run component.

> Gotcha when re-measuring locally: a clean `uv sync` provisions onnxruntime
> (it's a core dep). If you kill python/uv processes mid-sync, uv can leave the
> `onnxruntime-*.dist-info` without the package dir, after which `uv sync`
> believes it's installed and the build silently omits it (PyInstaller then
> reports "missing module named onnxruntime"). Fix: `uv pip install --reinstall
> onnxruntime`. Always confirm `import onnxruntime` works before building.

## Notes

- **TASK 2.2** moved `torch`/`torchvision`/`ultralytics` to an optional
  `[torch]` extra and excluded them (plus the CUDA `nvidia-*` wheels, `triton`,
  and the Real-ESRGAN stack `basicsr`/`realesrgan`/`gfpgan`/`facexlib`) from the
  casual `installer/svcs.spec`. Detection runs on ONNX Runtime
  (`onnxruntime`, core) against the bundled `yolov8n.onnx` (~12 MB). The runtime
  imports torch only lazily and degrades gracefully (ONNX detection; bicubic
  enhancement) when it is absent, so the frozen app still starts and serves.
- The bulk of the multi-GB weight was the CUDA PyTorch build + its `nvidia-*`
  CUDA runtime wheels. A CPU-only torch (what CI installs) is far smaller, but
  the installer's win comes from dropping torch entirely on the default path.
- TASK 2.4 (Inno Setup) turns the ONNX weights into an optional, first-run-
  fetchable component so the base download stays minimal.
