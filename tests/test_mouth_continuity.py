import unittest

import numpy as np


class MouthContinuityControllerTests(unittest.TestCase):
    def make_controller(self, *, gap_grace_frames=1, opening_frames=2, closing_frames=4):
        from src.avatars.musetalk.mouth_continuity import MouthContinuityController

        source = np.zeros((8, 8, 3), dtype=np.uint8)
        mask = np.zeros((8, 8), dtype=np.uint8)
        mask[2:6, 2:6] = 255
        return MouthContinuityController(
            [source],
            [mask],
            gap_grace_frames=gap_grace_frames,
            opening_frames=opening_frames,
            closing_frames=closing_frames,
        )

    def test_gap_holds_generated_mouth_then_closes_at_fixed_frame_rate(self):
        controller = self.make_controller()
        generated = np.full((8, 8, 3), 200, dtype=np.uint8)
        source = np.zeros((8, 8, 3), dtype=np.uint8)
        eventpoint = {"turn_id": "turn-1", "generation": 1}

        spoken = controller.compose(
            generated,
            index=0,
            is_speech=True,
            eventpoint=eventpoint,
        )
        gap = controller.compose(
            source,
            index=0,
            is_speech=False,
            eventpoint=eventpoint,
        )
        closing = [
            controller.compose(
                source,
                index=0,
                is_speech=False,
                eventpoint=eventpoint,
            )
            for _ in range(4)
        ]

        roi = (slice(2, 6), slice(2, 6))
        self.assertEqual(int(spoken[roi].mean()), 200)
        self.assertEqual(int(gap[roi].mean()), 200)
        self.assertEqual(
            [int(frame[roi].mean()) for frame in closing],
            [150, 100, 50, 0],
        )
        self.assertEqual(int(closing[0][0, 0].mean()), 0)

    def test_speech_resumes_without_waiting_for_idle_closing(self):
        controller = self.make_controller(gap_grace_frames=2)
        generated = np.full((8, 8, 3), 200, dtype=np.uint8)
        source = np.zeros((8, 8, 3), dtype=np.uint8)
        eventpoint = {"turn_id": "turn-1", "generation": 1}

        controller.compose(generated, index=0, is_speech=True, eventpoint=eventpoint)
        controller.compose(source, index=0, is_speech=False, eventpoint=eventpoint)
        resumed = controller.compose(
            generated,
            index=0,
            is_speech=True,
            eventpoint=eventpoint,
        )

        self.assertGreaterEqual(int(resumed[2:6, 2:6].mean()), 100)
        self.assertEqual(int(resumed[0, 0].mean()), 200)

    def test_reset_clears_previous_generation_mouth(self):
        controller = self.make_controller()
        generated = np.full((8, 8, 3), 200, dtype=np.uint8)
        source = np.zeros((8, 8, 3), dtype=np.uint8)

        controller.compose(
            generated,
            index=0,
            is_speech=True,
            eventpoint={"turn_id": "turn-1", "generation": 1},
        )
        controller.reset()
        idle = controller.compose(
            source,
            index=0,
            is_speech=False,
            eventpoint={"turn_id": "turn-2", "generation": 2},
        )

        self.assertEqual(int(idle[2:6, 2:6].mean()), 0)

    def test_crop_mask_from_opencv_bgr_image_is_projected_to_full_frame(self):
        from src.avatars.musetalk.mouth_continuity import MouthContinuityController

        source = np.zeros((10, 12, 3), dtype=np.uint8)
        crop_mask = np.zeros((4, 6, 3), dtype=np.uint8)
        crop_mask[1:3, 2:4] = 255
        controller = MouthContinuityController(
            [source], [crop_mask], [(3, 2, 9, 6)], gap_grace_frames=0
        )

        generated = np.full_like(source, 180)
        composed = controller.compose(
            generated,
            index=0,
            is_speech=True,
            eventpoint={"generation": 1},
        )

        self.assertEqual(int(composed[3, 6].mean()), 180)
        self.assertEqual(int(composed[0, 0].mean()), 180)

    def test_optional_neutral_frame_is_used_only_inside_mouth_roi(self):
        from src.avatars.musetalk.mouth_continuity import MouthContinuityController

        source = np.zeros((8, 8, 3), dtype=np.uint8)
        mask = np.zeros((8, 8), dtype=np.uint8)
        mask[2:6, 2:6] = 255
        neutral = np.full((8, 8, 3), 60, dtype=np.uint8)
        generated = np.full((8, 8, 3), 200, dtype=np.uint8)
        controller = MouthContinuityController(
            [source], [mask], neutral_frames=[neutral], gap_grace_frames=0, closing_frames=2
        )

        controller.compose(generated, index=0, is_speech=True, eventpoint=None)
        closing = controller.compose(source, index=0, is_speech=False, eventpoint=None)

        self.assertEqual(int(closing[3, 3].mean()), 130)
        self.assertEqual(int(closing[0, 0].mean()), 0)


if __name__ == "__main__":
    unittest.main()
