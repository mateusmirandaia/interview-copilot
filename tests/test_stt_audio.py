"""Audio resampling, the latency clock, Deepgram message parsing and URL, energy VAD."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest

from interview_copilot.audio.capture import TARGET_RATE, AudioChunk, Resampler, float_to_pcm16
from interview_copilot.stt import AudioClock, make_transcriber
from interview_copilot.stt.deepgram import MAX_KEYTERMS, DeepgramParser, DeepgramTranscriber
from interview_copilot.stt.whisper import EnergyVAD


# ---- audio -----------------------------------------------------------------------------------
def test_resampler_48k_stereo_in_chunks():
    rs = Resampler(48000, 2)
    t = np.arange(48000) / 48000
    tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    stereo = np.stack([tone, tone], axis=1).reshape(-1)
    out = np.concatenate([rs.process(stereo[i:i + 4802]) for i in range(0, len(stereo), 4802)])
    assert abs(len(out) - 16000) <= 2
    assert 0.6 < np.sqrt(np.mean(out ** 2)) < 0.75   # ~0.707 for a sine


def test_resampler_44100_and_16k():
    out = Resampler(44100, 1).process(np.zeros(44100, dtype=np.float32))
    assert abs(len(out) - 16000) <= 2
    same = Resampler(16000, 1).process(np.ones(320, dtype=np.float32))
    assert len(same) == 320
    assert len(Resampler(44100, 1).process(np.zeros(1, dtype=np.float32))) == 0


def test_float_to_pcm16_clips():
    pcm = np.frombuffer(float_to_pcm16(np.array([0.0, 2.0, -2.0], dtype=np.float32)), dtype="<i2")
    assert list(pcm) == [0, 32767, -32767]


# ---- clock -----------------------------------------------------------------------------------
def _clock(seconds: float, base: float) -> AudioClock:
    clock = AudioClock()
    for i in range(1, int(seconds / 0.05) + 1):
        clock.add(AudioChunk(b"\x00\x00" * 800, base + i * 0.05, 0))   # 50 ms chunks
    return clock


def test_audio_clock_maps_seconds():
    clock = _clock(2.0, 100.0)
    assert abs(clock.wall_time(1.0) - 101.0) < 1e-6
    assert abs(clock.seconds - 2.0) < 1e-9
    assert clock.wall_time(5.0) is None


# ---- deepgram --------------------------------------------------------------------------------
def _res(text: str, final: bool, speech_final: bool = False, end: float | None = None) -> dict:
    words = [{"word": "x", "start": 0, "end": end}] if end is not None else []
    return {"type": "Results", "is_final": final, "speech_final": speech_final,
            "channel": {"alternatives": [{"transcript": text, "words": words}]}}


def test_deepgram_parser_speech_final_utterance_end_and_offset():
    clock = _clock(5.0, 10.0)
    interims: list[str] = []
    utts: list = []
    p = DeepgramParser(clock, interims.append, utts.append)
    p.handle(_res("Tell me", False))
    p.handle(_res("Tell me about", True, end=1.2))
    p.handle(_res("yourself", False))
    assert interims[-1] == "Tell me about yourself"
    p.handle(_res("yourself and your", True, speech_final=True, end=2.5))
    assert len(utts) == 1
    assert utts[0].text == "Tell me about yourself and your"
    assert abs(utts[0].t_speech_end - 12.5) < 1e-6          # 10 s base + 2.5 s of audio
    p.handle({"type": "UtteranceEnd", "last_word_end": 2.5})  # nothing pending -> nothing
    assert len(utts) == 1
    p.handle(_res("Why Python?", True, end=3.9))
    p.handle({"type": "UtteranceEnd", "last_word_end": 3.9})
    assert utts[-1].text == "Why Python?"
    p.offset = 1.0                                           # reconnect: timestamps restart at 0
    p.handle(_res("Next one", True, speech_final=True, end=2.0))
    assert abs(utts[-1].t_speech_end - 13.0) < 1e-6
    p.handle(_res("pending", True))
    assert p.take_pending() == "pending" and p.take_pending() == ""
    p.handle({"type": "SpeechStarted"})                     # other messages are ignored
    assert len(utts) == 3


@pytest.fixture
def dg_settings(make_settings, monkeypatch: pytest.MonkeyPatch, profile: Path):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    return make_settings(profile)


def test_deepgram_url_keyterms(dg_settings):
    vocab = ["Sam Lee", "C#", "F&O"] + [f"term{i}" for i in range(150)]
    url = DeepgramTranscriber(dg_settings, vocab, print, print).url()
    q = parse_qs(urlparse(url).query)
    assert url.startswith("wss://api.deepgram.com/v1/listen?")
    assert q["model"] == ["nova-3"] and q["encoding"] == ["linear16"]
    assert q["sample_rate"] == [str(TARGET_RATE)]
    assert q["endpointing"] == ["700"] and q["utterance_end_ms"] == ["1000"]
    assert len(q["keyterm"]) == MAX_KEYTERMS == 100
    assert {"Sam Lee", "C#", "F&O"} <= set(q["keyterm"])
    assert "keywords" not in q


def test_deepgram_url_keywords_for_older_models(make_settings, monkeypatch, profile: Path):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    s = make_settings(profile, stt={"deepgram": {"model": "nova-2"}, "pause_ms": 1200})
    q = parse_qs(urlparse(DeepgramTranscriber(s, ["Sam"], print, print).url()).query)
    assert q["keywords"] == ["Sam:2"] and "keyterm" not in q
    assert q["utterance_end_ms"] == ["1500"]


def test_deepgram_requires_key(make_settings, monkeypatch, profile: Path):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
        DeepgramTranscriber(make_settings(profile), [], print, print)


def test_make_transcriber_auto_picks_deepgram(dg_settings):
    t = make_transcriber(dg_settings, ["Sam"], print, print, print)
    assert t.name == "deepgram" and t.vocabulary == ["Sam"]


def test_make_transcriber_unknown(make_settings, profile: Path):
    with pytest.raises(ValueError, match="provider"):
        make_transcriber(make_settings(profile, stt={"provider": "nope"}), [], print, print, print)


# ---- energy VAD ------------------------------------------------------------------------------
def _chunk(seconds: float, amp: float, t_end: float, rng: np.random.Generator):
    x = (rng.standard_normal(int(TARGET_RATE * seconds)) * amp).astype(np.float32)
    return x, float(np.sqrt(np.mean(x * x))), t_end


def test_energy_vad_detects_pause():
    rng = np.random.default_rng(0)
    vad = EnergyVAD(threshold=0.01, pause_ms=700)
    t = 0.0
    for _ in range(20):                    # 1 s of silence
        t += 0.05
        assert vad.push(*_chunk(0.05, 0.0005, t, rng)) is None
    for _ in range(40):                    # 2 s of "speech"
        t += 0.05
        assert vad.push(*_chunk(0.05, 0.1, t, rng)) is None
    assert vad.in_speech and vad.current_audio() is not None
    t_voice = t
    ev = None
    for _ in range(20):                    # silence until the end is detected
        t += 0.05
        ev = vad.push(*_chunk(0.05, 0.0005, t, rng))
        if ev:
            break
    assert ev and ev[0] == "end"
    assert abs(ev[2] - t_voice) < 1e-9
    assert 0.65 <= t - t_voice <= 0.8      # detected after ~700 ms
    assert len(ev[1]) >= TARGET_RATE * 2
    assert not vad.in_speech and vad.current_audio() is None


def test_energy_vad_max_segment():
    rng = np.random.default_rng(1)
    vad = EnergyVAD(threshold=0.01, pause_ms=700, max_segment_s=1.0)
    events = [vad.push(*_chunk(0.05, 0.1, i * 0.05, rng)) for i in range(40)]
    assert any(e and e[0] == "end" for e in events)
