import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "deploy" / "prepare.py"
spec = importlib.util.spec_from_file_location("deploy_prepare", path)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class PrivateDeploymentTests(unittest.TestCase):
    def test_public_loopback_and_ipv6_rejected_before_files(self):
        for address in ("8.8.8.8", "127.0.0.1", "0.0.0.0", "169.254.1.2", "::1"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                prepare.prepare(address)

    def test_network_surfaces_are_narrow(self):
        root = path.parents[1]
        compose = (root / "deploy/compose.yaml").read_text()
        runner = (root / "deploy/run.py").read_text()
        self.assertIn('127.0.0.1:15439:5432', compose)
        self.assertIn('--server.address=127.0.0.1', runner)


if __name__ == "__main__":
    unittest.main()
