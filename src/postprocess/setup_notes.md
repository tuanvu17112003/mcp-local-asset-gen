# Postprocess setup notes

This package implements the canned-path side of contract
C3-processed-asset v0.1.0. The image work itself is Pillow-only; live
background removal additionally needs `rembg` and a pre-downloaded
model cache.

## Python version

Live background removal requires Python 3.11 or newer. The pinned
floor is Python >= 3.11 because `rembg` and its model runtimes are
only exercised and supported there.

This checkout currently runs Python 3.10.11, so the live `rembg` path
is unreachable here by design: `remove_background` without a canned
`mask_provider` raises `SegmentationFailedError` on this interpreter
instead of attempting any download. The canned path (tests, fixtures)
works on any supported interpreter.

To run the live path, use a Python 3.11+ interpreter, for example:

```console
uv run --python 3.11 -- python -m pytest tests/test_postprocess/ -v
```

or create a dedicated virtual environment with Python 3.11+ and run
the suite inside it.

## Install route (covering authority required)

Installing packages was NOT performed as part of this change. When
installation is authorized, the live path needs:

```console
pip install rembg pillow
```

No other runtime dependency is required. In particular, `vtracer` is
explicitly NOT installed: SVG vectorization is deferred post-MVP (see
below) and the `vectorize_rgba` stub must keep working with stdlib +
Pillow only.

## Model pre-download and cache

Never download models inside tests or inside `process()`. Models are
pre-downloaded offline under covering authority before any live run:

```console
python -c "from rembg import new_session; new_session('u2net')"
python -c "from rembg import new_session; new_session('isnet-general-use')"
```

(The `rembg` CLI extra is deliberately not installed: it pins
`python-multipart<0.0.22`, which conflicts with `fastmcp 4.1.0`'s
`python-multipart>=0.0.26`. Use the Python one-liners above instead of
`rembg d`.)

The default model cache is `~/.u2net`; set `U2NET_HOME` to relocate
it. `remove_background` never triggers a download: the live path uses
a lazily created `rembg` session against the already-cached weights,
and any failure surfaces as `SegmentationFailedError`.

The default model is `u2net`; `isnet-general-use` is the quality
option. Session reuse (one `rembg.new_session(model)` per model,
shared across calls by the caller) is the expected live pattern; the
adapter creates the session per live call and does not cache globally.

## No downloads in tests

Tests use the canned-mask path only (`mask_provider` painting the
known 256x256 center square over `fixtures/c3/input-512.png`, trimmed
and padded to 272x272). The suite asserts the canned path never
imports `rembg`, and the live path is covered only by its
version-guard error on interpreters below 3.11.

## Vectorization status

SVG output is deferred post-MVP per the Q4 PNG-first decision. The
`vectorize_rgba` function is a stub: `vectorize=False` (the default)
returns `None` and produces no SVG entries; `vectorize=True` raises
`VectorizeFailedError` (`VECTORIZE_FAILED`). Re-activation must
re-pin `vtracer` first (the 1.0.0a4 API differs from 0.6.x) and then
implement the stub — do not add the dependency before that decision.

## USER-FACING LICENSE NOTE

The `rembg` code itself is MIT-licensed, but model weights carry
their own terms. In particular, the `bria-rmbg` model (RMBG-1.4
weights) is NON-commercial: commercial use requires a paid agreement
with BRIA. This package therefore defaults to `u2net` (with
`isnet-general-use` as the quality option), both usable without a
license flag.

Requesting `model="bria-rmbg"` without explicit acceptance is
rejected with `LicenseRequiredError` (`LICENSE_REQUIRED`), both via
`remove_background` and via `process()`. Pass
`bria_license_accepted=True` only after accepting the BRIA commercial
terms; the flag is recorded per call and never persisted by this
package.
