import asyncio
import queue
import unittest
from io import BytesIO
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np

from src.llm.base import TextStreamProcessor
from src.tts.base import BaseTTS


class TTSSpeechTextTests(unittest.TestCase):
    def test_tts_queue_removes_markdown_markers_and_emoji_before_synthesis(self):
        config = SimpleNamespace(audio=SimpleNamespace(fps=50))
        tts = BaseTTS(config, SimpleNamespace())

        tts.put_msg_txt("**這很重要**，請確認。😊")

        text, metadata = tts.msgqueue.get_nowait()
        self.assertEqual(text, "這很重要，請確認。")
        self.assertEqual(metadata, {})


class WebRTCPacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_player_reports_media_debt_and_av_offset_without_frames(self):
        from src.utils.webrtc import HumanPlayer

        observations = []
        player = HumanPlayer(
            None,
            on_media_timing=lambda **values: observations.append(values),
        )
        await player.audio.enqueue(object())
        await player.video.enqueue(object())

        player.notify_media_timing("audio", 0.10)
        player.notify_media_timing("video", 0.14)

        self.assertEqual(
            observations[-1],
            {
                "media_debt_seconds": 0.02,
                "av_offset_seconds": 0.04,
            },
        )
        player.audio.stop()
        player.video.stop()

    async def test_speech_start_discards_only_paired_idle_runway(self):
        from src.utils.webrtc import HumanPlayer, VIDEO_PTIME

        player = HumanPlayer(None)
        audio = player.audio
        video = player.video
        for _ in range(audio.max_buffer_frames):
            await audio.enqueue(object())
        for _ in range(video.max_buffer_frames):
            await video.enqueue(object())

        await player.prepare_speech_start()

        self.assertLessEqual(audio.buffered_duration, 0.10)
        self.assertLessEqual(video.buffered_duration, 0.10)
        self.assertLessEqual(
            abs(audio.buffered_duration - video.buffered_duration),
            VIDEO_PTIME,
        )
        audio.stop()
        video.stop()

    async def test_audio_and_video_apply_equal_low_latency_backpressure(self):
        from src.utils.webrtc import HumanPlayer

        player = HumanPlayer(None)
        audio = player.audio
        video = player.video

        self.assertLessEqual(audio.max_buffer_duration, 0.25)
        self.assertAlmostEqual(
            audio.max_buffer_duration,
            video.max_buffer_duration,
            places=3,
        )

        for _ in range(audio.max_buffer_frames):
            await audio.enqueue(object())
        blocked_put = asyncio.create_task(audio.enqueue(object()))
        await asyncio.sleep(0)

        self.assertFalse(blocked_put.done())
        self.assertLessEqual(audio.buffered_duration, 0.25)

        blocked_put.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await blocked_put
        audio.stop()
        video.stop()

    async def test_audio_and_video_share_one_stall_rebase(self):
        from src.utils.webrtc import HumanPlayer

        now = [100.0]
        sleeper = AsyncMock()
        player = HumanPlayer(None)
        audio = player.audio
        video = player.video

        with (
            patch("src.utils.webrtc.time.time", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
            patch("src.utils.webrtc.asyncio.sleep", new=sleeper),
            patch("src.utils.webrtc.mylogger") as pacing_logger,
        ):
            await audio.next_timestamp()
            await video.next_timestamp()
            now[0] += 1.0
            await audio.next_timestamp()
            now[0] += 0.08
            await video.next_timestamp()

        self.assertAlmostEqual(audio._start, video._start, places=6)
        pacing_logger.warning.assert_called_once()
        audio.stop()
        video.stop()

    async def test_audio_rebases_and_video_skips_after_stall_without_bursting(self):
        from src.utils.webrtc import (
            AUDIO_PTIME,
            SAMPLE_RATE,
            VIDEO_CLOCK_RATE,
            VIDEO_PTIME,
            PlayerStreamTrack,
        )

        cases = (
            ("audio", AUDIO_PTIME, SAMPLE_RATE),
            ("video", VIDEO_PTIME, VIDEO_CLOCK_RATE),
        )
        for kind, packet_time, clock_rate in cases:
            with self.subTest(kind=kind):
                now = [100.0]
                sleeper = AsyncMock()
                track = PlayerStreamTrack(None, kind=kind)

                with (
                    patch("src.utils.webrtc.time.time", side_effect=lambda: now[0]),
                    patch("src.utils.webrtc.time.monotonic", side_effect=lambda: now[0]),
                    patch("src.utils.webrtc.asyncio.sleep", new=sleeper),
                    patch("src.utils.webrtc.mylogger") as pacing_logger,
                ):
                    first_pts, _ = await track.next_timestamp()
                    now[0] += 1.0
                    second_pts, _ = await track.next_timestamp()
                    third_pts, _ = await track.next_timestamp()

                sleeper.assert_awaited_once()
                pacing_logger.warning.assert_called_once()
                self.assertAlmostEqual(
                    sleeper.await_args.args[0], packet_time, places=6
                )
                packet_ticks = int(packet_time * clock_rate)
                expected = (
                    [0, packet_ticks, packet_ticks * 2]
                    if kind == "audio"
                    else [0, clock_rate, clock_rate + packet_ticks]
                )
                self.assertEqual([first_pts, second_pts, third_pts], expected)
                track.stop()


class TextStreamTimingTests(unittest.TestCase):
    def test_comma_clause_waits_for_sentence_end(self):
        emitted = []
        processor = TextStreamProcessor()

        processor.process_chunk("我是 Linly 數字人助手，", emitted.append)
        self.assertEqual(emitted, [])

        processor.process_chunk("很高興為你服務，也可以協助處理各種問題。", emitted.append)
        self.assertEqual(
            emitted,
            ["我是 Linly 數字人助手，很高興為你服務，也可以協助處理各種問題。"],
        )


class MuseTalkAudioWindowTests(unittest.TestCase):
    def test_feature_window_is_centered_on_the_video_frame(self):
        from src.avatars.musetalk.whisper.audio2feature import Audio2Feature

        processor = Audio2Feature.__new__(Audio2Feature)
        features = np.zeros((64, 5, 384), dtype=np.float32)

        _, selected = processor.get_sliced_feature(
            features,
            vid_idx=5,
            audio_feat_length=[2, 2],
            fps=25,
        )

        self.assertEqual(selected, list(range(6, 16)))


class MuseTalkBufferPolicyTests(unittest.TestCase):
    def test_waits_for_pending_tts_while_playback_has_headroom(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        self.assertTrue(
            should_wait_for_tts_audio(
                tts_pending=True,
                queued_audio_frames=8,
                required_audio_frames=32,
                queued_video_frames=5,
            )
        )

    def test_partial_tts_batch_waits_instead_of_inserting_mid_speech_silence(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        # Once real speech has entered the queue, consuming a short batch makes
        # run_step() fill the remainder with timeout-generated silence.  Keep
        # the partial batch intact even when the video runway is temporarily low.
        self.assertTrue(
            should_wait_for_tts_audio(True, 8, 32, queued_video_frames=4)
        )

    def test_does_not_starve_idle_playback_or_delay_ready_audio(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        self.assertFalse(
            should_wait_for_tts_audio(True, 0, 32, queued_video_frames=4)
        )
        self.assertFalse(
            should_wait_for_tts_audio(True, 32, 32, queued_video_frames=5)
        )
        self.assertFalse(
            should_wait_for_tts_audio(False, 0, 32, queued_video_frames=5)
        )

    def test_tts_reports_work_while_synthesis_is_active(self):
        started = Event()
        release = Event()
        quit_event = Event()

        class BlockingTTS(BaseTTS):
            def txt_to_audio(self, msg):
                started.set()
                release.wait(timeout=1)

        config = SimpleNamespace(audio=SimpleNamespace(fps=50))
        tts = BlockingTTS(config, parent=None)
        tts.put_msg_txt("測試語音")
        worker = Thread(target=tts.process_tts, args=(quit_event,), daemon=True)
        worker.start()

        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(tts.has_pending_work())

        quit_event.set()
        release.set()
        worker.join(timeout=1)
        self.assertFalse(tts.has_pending_work())


class MuseTalkShutdownTests(unittest.TestCase):
    def test_full_result_queue_releases_inference_when_stopping(self):
        from src.avatars.musetalk.avatar import put_result_frame

        result_queue = queue.Queue(maxsize=1)
        result_queue.put(object())
        quit_event = Event()
        outcome = []
        worker = Thread(
            target=lambda: outcome.append(
                put_result_frame(result_queue, object(), quit_event)
            )
        )
        worker.start()
        self.assertTrue(worker.is_alive())

        quit_event.set()
        worker.join(timeout=0.3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, [False])


class MuseTalkSpeechOnsetTests(unittest.TestCase):
    def test_mixed_batch_keeps_leading_silent_pair_idle(self):
        import torch

        from src.avatars.musetalk.avatar import inference

        quit_event = Event()
        audio_feat_queue = queue.Queue()
        audio_out_queue = queue.Queue()

        audio_feat_queue.put([np.zeros(1, dtype=np.float32) for _ in range(2)])
        # Edge keeps a short natural pause before the first active sample.  All
        # four frames belong to TTS (type 0), but only the second video pair is
        # audible and should receive a generated mouth frame.
        for amplitude in (0.0, 0.0, 0.1, 0.1):
            audio_out_queue.put(
                (np.full(320, amplitude, dtype=np.float32), 0, None)
            )

        class ResultQueue(queue.Queue):
            def put(self, item, block=True, timeout=None):
                super().put(item, block=block, timeout=timeout)
                if self.qsize() == 2:
                    quit_event.set()

        class FakeModel:
            dtype = torch.float32

            def __call__(self, latent_batch, _timesteps, **_kwargs):
                return SimpleNamespace(sample=latent_batch)

        class FakeVAE:
            @staticmethod
            def decode_latents(_pred_latents):
                return ["mouth-0", "mouth-1"]

        result_queue = ResultQueue()
        inference(
            quit_event,
            2,
            [torch.zeros((1, 1), dtype=torch.float32)],
            audio_feat_queue,
            audio_out_queue,
            result_queue,
            FakeVAE(),
            SimpleNamespace(device=torch.device("cpu"), model=FakeModel()),
            lambda value: value,
            torch.tensor([0]),
        )

        results = [result_queue.get_nowait() for _ in range(2)]
        self.assertEqual([item[0] for item in results], [None, "mouth-1"])
        self.assertEqual(
            [[frame_type for _, frame_type, _ in item[2]] for item in results],
            [[1, 1], [0, 0]],
        )


class EdgeTTSSilenceTests(unittest.TestCase):
    def test_trims_synthesizer_padding_but_keeps_short_natural_pause(self):
        from src.tts.engines.edge import trim_edge_silence

        sample_rate = 16000
        stream = np.concatenate(
            [
                np.zeros(int(sample_rate * 0.10), dtype=np.float32),
                np.full(int(sample_rate * 0.50), 0.1, dtype=np.float32),
                np.zeros(int(sample_rate * 0.72), dtype=np.float32),
            ]
        )

        trimmed = trim_edge_silence(stream, sample_rate)

        self.assertEqual(trimmed.shape[0], int(sample_rate * (0.04 + 0.50 + 0.12)))
        self.assertTrue(np.allclose(trimmed[: int(sample_rate * 0.04)], 0.0))
        self.assertTrue(np.allclose(trimmed[-int(sample_rate * 0.12) :], 0.0))

    def test_does_not_drop_an_entire_quiet_clip(self):
        from src.tts.engines.edge import trim_edge_silence

        stream = np.zeros(1600, dtype=np.float32)
        self.assertIs(trim_edge_silence(stream, 16000), stream)

    def test_streaming_trim_matches_batch_trim_across_partial_frames(self):
        from src.tts.engines.edge import (
            _StreamingSilenceTrimmer,
            trim_edge_silence,
        )

        sample_rate = 16000
        stream = np.concatenate(
            [
                np.zeros(1731, dtype=np.float32),
                np.full(8123, 0.1, dtype=np.float32),
                np.zeros(11957, dtype=np.float32),
            ]
        )
        trimmer = _StreamingSilenceTrimmer(sample_rate)
        output = []
        for offset in range(0, stream.size, 137):
            chunk = trimmer.feed(stream[offset : offset + 137])
            if chunk.size:
                output.append(chunk)
        output.append(trimmer.finish())

        self.assertTrue(
            np.array_equal(np.concatenate(output), trim_edge_silence(stream, sample_rate))
        )


class EdgeTTSStreamingTests(unittest.TestCase):
    @staticmethod
    def _mp3_fixture() -> bytes:
        import av

        sample_rate = 24000
        tone_samples = int(sample_rate * 0.30)
        tone = (
            np.sin(2 * np.pi * 440 * np.arange(tone_samples) / sample_rate)
            * 8000
        ).astype(np.int16)
        samples = np.concatenate(
            [
                np.zeros(int(sample_rate * 0.05), dtype=np.int16),
                tone,
                np.zeros(int(sample_rate * 0.15), dtype=np.int16),
            ]
        )
        output = BytesIO()
        with av.open(output, mode="w", format="mp3") as container:
            stream = container.add_stream("libmp3lame", rate=sample_rate)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(
                samples.reshape(1, -1), format="s16", layout="mono"
            )
            frame.sample_rate = sample_rate
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        payload = output.getvalue()
        first_audio_frame = payload.find(b"\xff\xf3")
        return payload[first_audio_frame:] if first_audio_frame >= 0 else payload

    @staticmethod
    def _make_tts(parent):
        from src.tts.engines.edge import EdgeTTS

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(ref_file="zh-TW-YunJheNeural"),
        )
        return EdgeTTS(config, parent)

    def test_pcm_is_emitted_before_remote_stream_finishes(self):
        remote_release = Event()
        first_pcm = Event()

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                first_pcm.set()

        payload = self._mp3_fixture()

        class SlowEndingCommunicate:
            def __init__(self, *_args):
                pass

            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not remote_release.is_set():
                    await asyncio.sleep(0.01)

        tts = self._make_tts(Parent())
        worker = Thread(target=tts.txt_to_audio, args=(("測試即時播放。", {}),))
        with patch("src.tts.engines.edge.edge_tts.Communicate", SlowEndingCommunicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=0.20))
                self.assertTrue(worker.is_alive())
            finally:
                remote_release.set()
                worker.join(timeout=1)

    def test_timeout_before_first_audio_retries_without_stale_data(self):
        calls = []

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame, eventpoint))

        payload = self._mp3_fixture()

        class TimeoutCommunicate:
            async def stream(self):
                if False:
                    yield None
                raise asyncio.TimeoutError

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        def communicate(*_args):
            calls.append(len(calls) + 1)
            return TimeoutCommunicate() if len(calls) == 1 else WorkingCommunicate()

        parent = Parent()
        tts = self._make_tts(parent)
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            tts.txt_to_audio(("測試逾時重試。", {}))

        self.assertEqual(calls, [1, 2])
        self.assertTrue(parent.frames)
        start_events = [
            event for _, event in parent.frames if event.get("status") == "start"
        ]
        self.assertEqual(len(start_events), 1)

    def test_timeout_after_partial_audio_resumes_without_duplicate_prefix(self):
        calls = []

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame.copy(), dict(eventpoint)))

        payload = self._mp3_fixture()

        class PartialTimeoutCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload[: len(payload) * 3 // 4]}
                raise asyncio.TimeoutError

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        def communicate(*_args):
            calls.append(len(calls) + 1)
            return PartialTimeoutCommunicate() if len(calls) == 1 else WorkingCommunicate()

        resumed_parent = Parent()
        resumed_tts = self._make_tts(resumed_parent)
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            resumed_tts.txt_to_audio(("測試中斷續傳。", {}))

        expected_parent = Parent()
        expected_tts = self._make_tts(expected_parent)
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: WorkingCommunicate(),
        ):
            expected_tts.txt_to_audio(("測試中斷續傳。", {}))

        self.assertEqual(calls, [1, 2])
        self.assertTrue(
            np.array_equal(
                np.concatenate([frame for frame, _ in resumed_parent.frames]),
                np.concatenate([frame for frame, _ in expected_parent.frames]),
            )
        )
        events = [event for _, event in resumed_parent.frames if event]
        self.assertEqual([event["status"] for event in events], ["start", "end"])

    def test_turn_aware_frames_are_fenced_and_keep_20ms_media_sequences(self):
        from src.server.reply_streaming.channel import PlayableFragment
        from src.server.reply_streaming.turn import TurnContext

        class Parent:
            def __init__(self):
                self.frames = []

            def put_audio_frame(self, frame, eventpoint):
                self.frames.append((frame.copy(), dict(eventpoint)))

        payload = self._mp3_fixture()

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        turn = TurnContext(turn_id="turn-1", generation=7)
        fragment = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=3),
            text="測試輪次音訊。",
            estimated_seconds=0.5,
        )
        parent = Parent()
        tts = self._make_tts(parent)

        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: WorkingCommunicate(),
        ):
            tts.synthesize_fragment(
                fragment,
                chunk_guard=lambda media_sequence: media_sequence < 2,
            )

        self.assertEqual(len(parent.frames), 2)
        self.assertTrue(all(frame.shape == (320,) for frame, _ in parent.frames))
        self.assertEqual(
            [event["media_sequence"] for _, event in parent.frames],
            [0, 1],
        )
        self.assertTrue(
            all(
                event["turn_id"] == "turn-1"
                and event["generation"] == 7
                and event["fragment_sequence"] == 3
                for _, event in parent.frames
            )
        )

    def test_fragment_retry_uses_the_shared_one_second_budget(self):
        from src.server.reply_streaming.channel import PlayableFragment
        from src.server.reply_streaming.retry import RetryBudget
        from src.server.reply_streaming.turn import TurnContext

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                raise AssertionError("timed out attempts must not emit audio")

        class HangingCommunicate:
            async def stream(self):
                await asyncio.Event().wait()
                if False:
                    yield None

        timeouts = []

        async def immediate_timeout(awaitable, *, timeout):
            timeouts.append(timeout)
            awaitable.close()
            raise asyncio.TimeoutError

        turn = TurnContext(turn_id="turn-1", generation=1)
        fragment = PlayableFragment(
            envelope=turn.envelope(stage="tts_fragment", sequence=0),
            text="測試重試預算。",
            estimated_seconds=0.5,
        )
        tts = self._make_tts(Parent())

        with (
            patch(
                "src.tts.engines.edge.edge_tts.Communicate",
                side_effect=lambda *_args: HangingCommunicate(),
            ),
            patch("src.tts.engines.edge.asyncio.wait_for", new=immediate_timeout),
        ):
            tts.synthesize_fragment(
                fragment,
                chunk_guard=lambda _sequence: True,
                retry_budget=RetryBudget(max_retries=1, extra_wait_seconds=1.0),
            )

        self.assertEqual(timeouts, [1.5, 1.0])


if __name__ == "__main__":
    unittest.main()
