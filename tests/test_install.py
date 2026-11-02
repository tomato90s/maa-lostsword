import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "tools"))
        spec = importlib.util.spec_from_file_location("installer_under_test", ROOT / "tools/install.py")
        cls.installer = importlib.util.module_from_spec(spec)
        with patch.object(sys, "argv", ["install.py", "v0.0.0-test", "win", "x86_64"]):
            spec.loader.exec_module(cls.installer)

    def test_desktop_package_places_helpers_next_to_framework(self):
        for platform in ("win", "macos", "linux"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "deps/bin").mkdir(parents=True)
                (root / "deps/bin/framework-library").write_bytes(b"framework")
                (root / "deps/bin/MaaDbg-tool").write_bytes(b"debug-only")
                helper = root / "deps/share/MaaAgentBinary/maatouch/universal/maatouch"
                helper.parent.mkdir(parents=True)
                helper.write_bytes(b"touch-helper")
                with patch.multiple(self.installer, working_dir=root,
                                    install_path=root / "install", os_name=platform):
                    self.installer.install_deps()
                self.assertEqual((root / "install/maafw/framework-library").read_bytes(), b"framework")
                self.assertEqual((root / "install/maafw/MaaAgentBinary/maatouch/universal/maatouch")
                                 .read_bytes(), b"touch-helper")
                self.assertTrue((root / "install/MaaAgentBinary/maatouch/universal/maatouch").is_file())
                self.assertFalse((root / "install/maafw/MaaDbg-tool").exists())

    def test_android_package_keeps_flat_framework_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "deps/bin").mkdir(parents=True)
            (root / "deps/bin/framework-library").write_bytes(b"framework")
            helper = root / "deps/share/MaaAgentBinary/helper"
            helper.parent.mkdir(parents=True)
            helper.write_bytes(b"helper")
            with patch.multiple(self.installer, working_dir=root,
                                install_path=root / "install", os_name="android"):
                self.installer.install_deps()
            self.assertTrue((root / "install/framework-library").is_file())
            self.assertTrue((root / "install/MaaAgentBinary/helper").is_file())
            self.assertFalse((root / "install/maafw").exists())

    def test_packaged_agent_path_and_all_task_imports_are_complete(self):
        for platform, executable in (("win", "./python/python.exe"),
                                     ("macos", "./python/bin/python")):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary)
                with patch.multiple(self.installer, working_dir=ROOT, install_path=target,
                                    os_name=platform, version="v0.0.0-test"), \
                        patch.object(self.installer, "configure_ocr_model"):
                    self.installer.install_resource()
                    self.installer.install_agent()
                interface = json.loads((target / "interface.json").read_text(encoding="utf-8"))
                self.assertEqual(interface["agent"]["child_exec"], executable)
                self.assertEqual(interface["agent"]["child_args"], ["-u", "./agent/main.py"])
                for relative in interface["import"]:
                    self.assertTrue((target / relative).is_file(), relative)
                for module in ("local_actions", "daily_actions", "crash_recovery"):
                    self.assertTrue((target / "agent" / f"{module}.py").is_file())
                for image in ("local_squad_room_exit.png", "local_squad_ticket_mode.png"):
                    self.assertTrue((target / "resource/image" / image).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
