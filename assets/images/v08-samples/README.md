# v0.8.0 live samples (RTX 3080 10 GB, ComfyUI 0.41.0)

Produced by driving the REAL `AssetOrchestrator` against a live ComfyUI
(port 8000) on 2026-11-08, with FLUX.1-schnell GGUF-Q4 + `RealESRGAN_x4.pth`.
These files are evidence for the release notes, not test fixtures.

| File | How it was produced |
|---|---|
| `upscale-4x-base.png` | `generate_app_asset(prompt="simple blue square icon, flat design", category="icon", save_path="live/sq.png", upscale=4)` → reported `output_width`/`output_height` 1597×1584, matching the written file exactly |
| `variant-1.png` … `variant-3.png` | `generate_app_asset(..., variants=3)` → three independent seeds (`<stem>.png`, `<stem>-v2.png`, `<stem>-v3.png`) |
| `variants-contact-sheet.png` | the `contact_sheet=true` grid for those three variants (1048×1048, 2×2 cells) |
| `variants-contact-sheet.json` | the deterministic manifest written beside the sheet |

Observed timings on that machine: `upscale=4` ≈ 19–21 s end to end (render +
292 MP-ish upscale + trim + exports); `variants=3 + contact_sheet` ≈ 25 s.
