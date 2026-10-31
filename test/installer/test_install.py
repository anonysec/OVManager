#!/usr/bin/env python3
"""Installer regression tests. Run with python3 -m unittest discover -s test/installer."""
import os
import pathlib
import pty
import select
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "install.sh"


class InstallerTests(unittest.TestCase):
    def run_bash(self, code, env=None, tty_input=None):
        command = 'source "$INSTALLER"\n' + code
        environ = dict(os.environ, INSTALLER=str(INSTALLER), **(env or {}))
        if tty_input is None:
            return subprocess.run(["bash", "-c", command], env=environ,
                                  text=True, capture_output=True, timeout=15)
        master, slave = pty.openpty()
        proc = subprocess.Popen(["bash", "-c", command], env=environ,
                                stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        os.write(master, tty_input.encode())
        output = b""
        while proc.poll() is None:
            ready, _, _ = select.select([master], [], [], 5)
            if not ready:
                proc.kill()
                self.fail("installer prompt timed out")
            try:
                output += os.read(master, 65536)
            except OSError:
                break
        proc.wait(timeout=5)
        try:
            while True:
                output += os.read(master, 65536)
        except OSError:
            pass
        os.close(master)
        return subprocess.CompletedProcess(proc.args, proc.returncode, output.decode(), "")

    def test_node_bootstrap_does_not_look_like_existing_install(self):
        # Reproduce OVNode's load_helpers creating APP_DIR before the check.
        upstream = '''#!/usr/bin/env bash
set -e
APP_DIR="$OVN_APP_DIR"
load_helpers() { mkdir -p "$APP_DIR"; touch "$APP_DIR/helper"; }
main() {
    load_helpers
    # install
    if [[ -d "$APP_DIR" ]]; then
        echo existing
    else
        echo fresh
    fi
}
main
'''
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d, "upstream.sh")
            path.write_text(upstream)
            env = {"UPSTREAM": str(path), "OVN_APP_DIR": str(pathlib.Path(d, "node"))}
            code = 'curl() { cat "$UPSTREAM"; }; sudo() { "$@"; }; run_node_installer'
            first = self.run_bash(code, env)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("fresh", first.stdout)
            second = self.run_bash(code, env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("existing", second.stdout)

    def test_node_download_failure_is_not_success(self):
        result = self.run_bash('curl() { return 22; }; run_node_installer')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not download", result.stderr)

    def test_summary_follows_node_and_precedes_logs_on_failure(self):
        result = self.run_bash('''
INTERACTIVE=1; YES=0
run_node_installer() { echo NODE_FINISHED; return 1; }
curl() { return 1; }
journalctl() { echo FOLLOW_LOGS; }
offer_node_and_logs native 2095 dashboard secret-key
''', tty_input="y\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertLess(result.stdout.index("NODE_FINISHED"), result.stdout.index("Installation complete"))
        self.assertLess(result.stdout.index("Installation complete"), result.stdout.index("FOLLOW_LOGS"))
        self.assertIn("secret-key", result.stdout)
        self.assertIn("http://127.0.0.1:2095/dashboard/", result.stdout)
        self.assertIn("OVNode installation failed", result.stdout)

    def test_summary_after_success_and_when_node_skipped(self):
        for answer, should_run in (("y", True), ("n", False)):
            result = self.run_bash('''
INTERACTIVE=1; YES=0
run_node_installer() { echo NODE_FINISHED; }
curl() { return 1; }
offer_node_and_logs docker 2095 panel secret-key
''', tty_input=answer + "\nn\n")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual("NODE_FINISHED" in result.stdout, should_run)
            self.assertIn("secret-key", result.stdout)
            if should_run:
                self.assertLess(result.stdout.index("NODE_FINISHED"), result.stdout.index("Installation complete"))

    def test_noninteractive_summary_and_interactive_command(self):
        result = self.run_bash('''
parse_args interactive
[[ "$INTERACTIVE" == 1 ]]
YES=1
curl() { return 0; }
offer_node_and_logs docker 443 /custom/ new-key
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("https://127.0.0.1:443/custom/", result.stderr)
        self.assertIn("new-key", result.stderr)

    def test_docker_mints_key_only_for_fresh_data(self):
        with tempfile.TemporaryDirectory() as d:
            code = '''
DATA_DIR="$TEST_DATA"
ensure_docker() { :; }
write_compose_file() { :; }
chown() { :; }
docker() {
    case "$1" in inspect) echo nonroot ;; esac
    return 0
}
setup_docker
printf 'KEY=%s\\n' "$DOCKER_CLAIM_KEY"
'''
            env = {"TEST_DATA": d}
            first = self.run_bash(code, env)
            self.assertEqual(first.returncode, 0, first.stderr)
            key = pathlib.Path(d, "owner-claim.key").read_text().strip()
            self.assertEqual(len(key), 32)
            self.assertIn("KEY=" + key, first.stdout)
            self.assertEqual(pathlib.Path(d, "owner-claim.key").stat().st_mode & 0o777, 0o600)
            second = self.run_bash(code, env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("KEY=\n", second.stdout)
            self.assertEqual(pathlib.Path(d, "owner-claim.key").read_text().strip(), key)
            pathlib.Path(d, "owner-claim.key").unlink()
            pathlib.Path(d, "ovmanager.db").touch()
            third = self.run_bash(code, env)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertFalse(pathlib.Path(d, "owner-claim.key").exists())


if __name__ == "__main__":
    unittest.main()
