import unittest
import warnings


class AvatarEnvironmentTests(unittest.TestCase):
    def test_pkg_resources_is_available_for_openmmlab(self):
        """mmengine/mmpose still import pkg_resources while building MuseTalk roles."""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                import pkg_resources  # noqa: F401
        except ModuleNotFoundError:
            self.fail(
                "MuseTalk role creation requires pkg_resources via mmengine/mmpose; "
                "install a setuptools version older than 82"
            )


if __name__ == "__main__":
    unittest.main()
