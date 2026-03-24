# Task 11 — Stream Decoder

A streaming unicode decoder iterates over byte chunks and yields decoded strings.

Users report that when `encoding` is `None`, the decoder yields raw `bytes` objects instead of `str`. The `apparent_encoding` fallback is never used.

**Write:** `fixed_processor.py`

---
*Derived from: psf/requests#3362*
