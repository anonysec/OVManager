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

    def test_node_installer_runs_the_release_bootstrap_with_yes(self):
        upstream = '#!/usr/bin/env bash\necho "NODE_ARGS:$*"\nexit 0\n'
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d, "upstream.sh")
            path.write_text(upstream)
            result = self.run_bash(
                'curl() { cat "$UPSTREAM"; }; sudo() { "$@"; }; run_node_installer',
                {"UPSTREAM": str(path)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NODE_ARGS:-y", result.stdout)

    def test_node_installer_accepts_an_existing_node(self):
        upstream = '#!/usr/bin/env bash\nexit 3\n'
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d, "upstream.sh")
            path.write_text(upstream)
            result = self.run_bash(
                'curl() { cat "$UPSTREAM"; }; sudo() { "$@"; }; run_node_installer',
                {"UPSTREAM": str(path)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already installed", result.stderr)

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
        self.assertLess(result.stdout.index("NODE_FINISHED"), result.stdout.index("Panel installation complete"))
        self.assertLess(result.stdout.index("Panel installation complete"), result.stdout.index("FOLLOW_LOGS"))
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
OVM_HOST_IP=127.0.0.1
curl() { return 0; }
offer_node_and_logs docker 443 /custom/ new-key
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("https://127.0.0.1:443/custom/", result.stderr)
        self.assertIn("new-key", result.stderr)



    def test_install_defaults_to_the_wizard_on_a_terminal(self):
        result = self.run_bash('parse_args install; echo "INTERACTIVE=$INTERACTIVE"', tty_input="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INTERACTIVE=1", result.stdout)
        result = self.run_bash('parse_args -y install; echo "INTERACTIVE=$INTERACTIVE"', tty_input="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INTERACTIVE=0", result.stdout)

    def test_node_settings_prompt_rejects_nothing_and_defaults_to_1194(self):
        result = self.run_bash('''
is_port_in_use() { return 1; }
YES=0
ask_node_settings
echo "PORT=$OVNODE_VPN_PORTS PROTO=$OVNODE_PROTO"
''', tty_input="45432\nboth\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PORT=45432 PROTO=both", result.stdout)
        result = self.run_bash('YES=1; ask_node_settings; echo "PORT=$OVNODE_VPN_PORTS PROTO=$OVNODE_PROTO"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PORT=1194 PROTO=udp", result.stdout)

    def test_update_runs_the_downloaded_release_updater(self):
        with tempfile.TemporaryDirectory() as d:
            app = pathlib.Path(d, "app")
            app.mkdir()
            (app / "ovmanager-server").write_text("#!/bin/sh\nexit 0\n")
            (app / "ovmanager-server").chmod(0o755)
            (app / ".env").write_text(f"DataDir={d}/data\n")
            result = self.run_bash('''
INSTALL_DIR="$APP"; DATA_DIR="$DATA"; SERVER_BIN=ovmanager-server; FROM_SOURCE=0
fetch_release() {
    mkdir -p "$1"
    printf '#!/bin/sh\necho NEW_UPDATER "$@"\n' > "$1/ovmanager-server"
    chmod +x "$1/ovmanager-server"
}
do_update
''', {"APP": str(app), "DATA": f"{d}/data"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NEW_UPDATER", result.stdout)
        self.assertIn("--install-dir " + str(app), result.stdout)
        self.assertIn("update --yes", result.stdout)

    def test_update_does_not_fall_through_to_install(self):
        result = self.run_bash('''
do_update() { echo UPDATED; }
do_install() { echo INSTALLED; }
main update
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UPDATED", result.stdout)
        self.assertNotIn("INSTALLED", result.stdout)
