"""System audio capture (WASAPI loopback, Windows only)."""

from .capture import TARGET_RATE, AudioChunk, LoopbackCapture, Resampler, list_loopback_devices

__all__ = ["TARGET_RATE", "AudioChunk", "LoopbackCapture", "Resampler", "list_loopback_devices"]
