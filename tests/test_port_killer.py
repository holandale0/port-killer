# -*- coding: utf-8 -*-
"""
Testes do Port Killer.

Rodar:  python -m unittest discover -s tests -v

A lógica pura (pins, snapshot, classificação, máquina de estados do kill) roda
sem display. Os testes de UI são pulados automaticamente quando não há Tk.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil
import port_killer as pk

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
    _root.destroy()
    HAS_TK = True
except Exception:
    HAS_TK = False

requires_tk = unittest.skipUnless(HAS_TK, "sem display/Tk disponivel")


# ── helpers ───────────────────────────────────────────────────────────────────

class FakeAddr:
    def __init__(self, port):
        self.port = port


class FakeConn:
    def __init__(self, port, pid, status):
        self.laddr, self.pid, self.status = FakeAddr(port), pid, status


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


LISTENER = (
    "import socket,time\n"
    "s=socket.socket()\n"
    "s.bind(('127.0.0.1',{port})); s.listen(5)\n"
    "{extra}"
    "time.sleep(300)"
)

SPAWN_KIDS = (
    "import subprocess,sys\n"
    "k=[subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'])"
    " for _ in range(2)]\n"
    "print(' '.join(str(x.pid) for x in k), flush=True)\n"
)


def spawn_listener(extra="", stdout=None, attempts=3):
    """Sobe um listener real. Retenta: free_port() tem janela de corrida."""
    for _ in range(attempts):
        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, "-c", LISTENER.format(port=port, extra=extra)],
            stdout=stdout, text=True if stdout else None)
        deadline = time.time() + 25
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            info = pk.get_port_info(port)
            if info and info != "ACCESS_DENIED" and info.pid == proc.pid:
                return proc, port
            time.sleep(0.2)
        try:
            proc.kill()
        except Exception:
            pass
    raise unittest.SkipTest("nao foi possivel subir o listener de teste")


def wait_gone(pids, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(psutil.pid_exists(p) for p in pids):
            return True
        time.sleep(0.1)
    return False


# ── persistência de pins ──────────────────────────────────────────────────────

class TestPins(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "pins.json")
        self._orig = pk._pins_path
        pk._pins_path = lambda: self.path

    def tearDown(self):
        pk._pins_path = self._orig

    def write(self, content):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_missing_file_is_writable(self):
        self.assertEqual(pk.load_pins(), ([], True))

    def test_reads_valid_pins(self):
        self.write('{"pins": [8080, 3000]}')
        self.assertEqual(pk.load_pins(), ([3000, 8080], True))

    def test_bad_entry_does_not_discard_the_list(self):
        """Regressao: um pin string zerava a lista inteira."""
        self.write('{"pins": ["3000", 8080, null]}')
        self.assertEqual(pk.load_pins(), ([3000, 8080], True))

    def test_out_of_range_ports_dropped(self):
        self.write('{"pins": [0, -5, 70000, 443]}')
        self.assertEqual(pk.load_pins(), ([443], True))

    def test_corrupt_json_is_quarantined_not_overwritten(self):
        self.write("not json at all")
        self.assertEqual(pk.load_pins(), ([], True))
        with open(self.path + ".corrupt", encoding="utf-8") as f:
            self.assertEqual(f.read(), "not json at all")

    def test_unreadable_file_marks_session_read_only(self):
        self.write('{"pins": [1234]}')
        import builtins
        real = builtins.open

        def boom(path, *a, **k):
            if str(path) == self.path:
                raise OSError("locked")
            return real(path, *a, **k)

        builtins.open = boom
        try:
            self.assertEqual(pk.load_pins(), ([], False))
        finally:
            builtins.open = real

    def test_save_is_atomic_and_deduplicates(self):
        pk.save_pins([443, 80, 443])
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"pins": [80, 443]})
        self.assertFalse(os.path.exists(self.path + ".tmp"))


# ── snapshot e resolução de portas ────────────────────────────────────────────

class TestSnapshot(unittest.TestCase):
    def snapshot_of(self, conns):
        real = psutil.net_connections
        psutil.net_connections = lambda kind=None: conns
        try:
            return pk.system_snapshot()
        finally:
            psutil.net_connections = real

    def test_listen_wins_over_other_states(self):
        """Regressao: o primeiro match podia ser um socket ESTABLISHED."""
        ports, _ = self.snapshot_of([
            FakeConn(9000, 111, psutil.CONN_ESTABLISHED),
            FakeConn(9000, 222, psutil.CONN_LISTEN),
        ])
        self.assertEqual([c.pid for c in ports[9000]], [222])

    def test_reuseport_exposes_every_worker(self):
        ports, _ = self.snapshot_of([
            FakeConn(9001, p, psutil.CONN_LISTEN) for p in (333, 444, 555)
        ])
        info = pk.get_port_info(9001, (ports, {}))
        self.assertEqual(info.pids, [333, 444, 555])

    def test_dual_stack_collapses_to_one_pid(self):
        ports, _ = self.snapshot_of([
            FakeConn(9002, 666, psutil.CONN_LISTEN),
            FakeConn(9002, 666, psutil.CONN_LISTEN),
        ])
        self.assertEqual(pk.get_port_info(9002, (ports, {})).pids, [666])

    def test_udp_without_listen_still_reported(self):
        ports, _ = self.snapshot_of([FakeConn(9003, 777, psutil.CONN_NONE)])
        self.assertEqual(pk.get_port_info(9003, (ports, {})).pids, [777])

    def test_free_port_returns_none(self):
        ports, _ = self.snapshot_of([])
        self.assertIsNone(pk.get_port_info(9999, (ports, {})))

    def test_access_denied_propagates(self):
        real = psutil.net_connections

        def denied(kind=None):
            raise psutil.AccessDenied()

        psutil.net_connections = denied
        try:
            self.assertEqual(pk.get_port_info(80), "ACCESS_DENIED")
        finally:
            psutil.net_connections = real


# ── classificação de processos ────────────────────────────────────────────────

class TestProcessType(unittest.TestCase):
    def test_unreadable_owner_is_never_an_application(self):
        """Regressao: AccessDenied virava 'Aplicacao', o rotulo mais seguro."""
        class Denied:
            def username(self):
                raise psutil.AccessDenied()

        self.assertEqual(
            pk.get_process_type(1234, "postgres.exe", proc=Denied()), "Desconhecido")

    def test_known_system_name_without_any_syscall(self):
        class Boom:
            def username(self):
                raise AssertionError("nao deveria consultar o dono")

        name = "svchost.exe" if sys.platform == "win32" else "systemd"
        self.assertEqual(pk.get_process_type(4, name, proc=Boom()), "Sistema")

    def test_own_process_is_an_application(self):
        me = psutil.Process(os.getpid())
        self.assertEqual(pk.get_process_type(me.pid, me.name(), proc=me), "Aplicação")

    def test_no_pid_is_unknown(self):
        self.assertEqual(pk.get_process_type(0, "qualquer"), "Desconhecido")

    def test_privileged_owner_is_system(self):
        class Root:
            def username(self):
                return "NT AUTHORITY\\SYSTEM" if sys.platform == "win32" else "root"

        self.assertEqual(pk.get_process_type(1, "qualquer", proc=Root()), "Sistema")


# ── máquina de estados do encerramento ────────────────────────────────────────

class Immortal:
    """Processo que ignora todos os sinais."""
    def __init__(self, pid=424242):
        self.pid = pid

    def create_time(self):
        return 1.0

    def children(self, recursive=False):
        return []

    def terminate(self):
        pass

    def kill(self):
        pass

    def status(self):
        return psutil.STATUS_RUNNING

    def is_running(self):
        return True


class TestKill(unittest.TestCase):
    def setUp(self):
        self.app = pk.PortKillerApp.__new__(pk.PortKillerApp)

    def test_recycled_pid_is_refused(self):
        """Regressao: matava por PID sem checar se ainda era o mesmo processo."""
        proc, port = spawn_listener()
        self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
        target = self.app._resolve_targets([port])[0]
        self.assertEqual(
            self.app._do_kill(target.pid, None, target.create_time - 999), "stale")
        self.assertIsNone(proc.poll(), "processo nao podia ter sido encerrado")

    def test_kills_the_whole_tree(self):
        """Regressao: filhos orfaos seguiam segurando a porta."""
        proc, port = spawn_listener(extra=SPAWN_KIDS, stdout=subprocess.PIPE)
        kids = [int(x) for x in proc.stdout.readline().split()]
        self.addCleanup(lambda: [psutil.Process(p).kill()
                                 for p in kids + [proc.pid] if psutil.pid_exists(p)])
        self.assertTrue(all(psutil.pid_exists(k) for k in kids))

        target = self.app._resolve_targets([port])[0]
        self.assertGreaterEqual(target.children, 2)
        self.assertEqual(self.app._do_kill(target.pid, None, target.create_time), "killed")
        self.assertTrue(wait_gone(kids), "os filhos sobreviveram ao pai")

    def test_returns_quickly_when_the_process_dies(self):
        """Regressao: sleep(0.5) fixo por processo, na thread da UI."""
        proc, port = spawn_listener()
        self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
        start = time.perf_counter()
        result = self.app._do_kill(proc.pid, None, None)
        self.assertEqual(result, "killed")
        self.assertLess(time.perf_counter() - start, 0.5)

    def test_survivor_is_reported_as_denied(self):
        """Regressao: retornava sucesso sem verificar se o processo morreu."""
        real_proc, real_wait = psutil.Process, psutil.wait_procs
        psutil.Process = lambda pid: Immortal(pid)
        psutil.wait_procs = lambda procs, timeout=None: ([], list(procs))
        try:
            self.assertEqual(self.app._do_kill(424242, None, 1.0), "denied")
        finally:
            psutil.Process, psutil.wait_procs = real_proc, real_wait

    def test_gone_process_counts_as_killed(self):
        real = psutil.Process

        def missing(pid):
            raise psutil.NoSuchProcess(pid)

        psutil.Process = missing
        try:
            self.assertEqual(self.app._do_kill(1, None, None), "killed")
        finally:
            psutil.Process = real

    def test_sudo_escalates_term_then_kill_in_one_call_per_round(self):
        """Regressao: `kill -9` direto, e um sudo por PID."""
        calls = []
        real_run, real_wait = subprocess.run, psutil.wait_procs
        subprocess.run = lambda cmd, **kw: (
            calls.append((cmd, kw.get("input"))),
            type("R", (), {"returncode": 1})())[1]
        psutil.wait_procs = lambda procs, timeout=None: ([], list(procs))
        try:
            self.app._sudo_family([Immortal(10), Immortal(11)], "s3nha")
        finally:
            subprocess.run, psutil.wait_procs = real_run, real_wait

        self.assertEqual(len(calls), 2, "esperava uma rodada TERM e uma KILL")
        self.assertIn("-TERM", calls[0][0])
        self.assertIn("-KILL", calls[1][0])
        self.assertEqual(calls[0][0][-2:], ["10", "11"], "PIDs deviam ir juntos")
        self.assertEqual(calls[0][1], "s3nha\n")
        self.assertNotIn("s3nha", " ".join(calls[0][0]), "senha nunca em argv")


# ── UI ────────────────────────────────────────────────────────────────────────

@requires_tk
class TestUI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._orig = pk._pins_path
        pk._pins_path = lambda: os.path.join(self.dir, "pins.json")
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = pk.PortKillerApp.__new__(pk.PortKillerApp)
        self.app.root = self.root
        self.app.current_pid = self.app.current_port = None
        self.app._refresh_job = None
        self.app._pinned, self.app._pins_writable = [3000, 8080, 9999], True
        self.app._setup_styles()
        self.app._build_ui()
        self.app._refresh_list()

    def tearDown(self):
        pk._pins_path = self._orig
        self.root.destroy()

    def test_refresh_preserves_selection(self):
        """Regressao: a tabela era recriada e a selecao sumia a cada 4 s."""
        rows = self.app.tree.get_children()
        self.app.tree.selection_set(rows[0], rows[2])
        before = self.app.tree.selection()
        self.app._refresh_list()
        self.assertEqual(self.app.tree.selection(), before)

    def test_refresh_follows_the_pin_list(self):
        self.app._pinned = [80, 3000]
        self.app._refresh_list()
        shown = [self.app.tree.item(i)["values"][0]
                 for i in self.app.tree.get_children()]
        self.assertEqual(shown, [80, 3000])

    def test_timer_survives_a_failing_refresh(self):
        """Regressao: uma excecao parava o auto-refresh para sempre."""
        def boom():
            raise RuntimeError("falha simulada")

        self.app._refresh_list = boom
        self.app._auto_refresh()
        self.assertIsNotNone(self.app._refresh_job)
        self.root.after_cancel(self.app._refresh_job)

    def test_invalid_port_clears_the_previous_one(self):
        """Regressao: 'Pinar' pinava a porta anterior, nao a da tela."""
        errors = []
        real = pk.messagebox.showerror
        pk.messagebox.showerror = lambda t, m: errors.append(t)
        try:
            self.app.port_var.set("80")
            self.app._check_port()
            self.assertEqual(self.app.current_port, 80)
            self.app.port_var.set("abc")
            self.app._check_port()
        finally:
            pk.messagebox.showerror = real
        self.assertIsNone(self.app.current_port)
        self.assertEqual(str(self.app.pin_btn["state"]), "disabled")
        self.assertEqual(len(errors), 1)

    def test_targets_come_from_the_os_not_the_table(self):
        """Regressao: PIDs eram lidos da tabela, que o timer ja reescreveu."""
        port = free_port()
        if pk.get_port_info(port) is not None:
            self.skipTest("a porta %s foi ocupada durante o teste" % port)
        self.app._pinned = [port]
        self.app._refresh_list()
        self.app.tree.item(str(port), values=(port, "EM USO", "Aplicação",
                                              "fake.exe", "999999", "0"))
        self.assertEqual(self.app._resolve_targets([port]), [])

    def test_refresh_pauses_around_the_dialog(self):
        self.app._schedule_refresh()
        self.app._pause_refresh()
        self.assertIsNone(self.app._refresh_job)
        self.app._resume_refresh()
        self.assertIsNotNone(self.app._refresh_job)
        self.root.after_cancel(self.app._refresh_job)

    def test_empty_password_still_confirms(self):
        """Regressao: campo vazio fazia o botao Encerrar nao fazer nada."""
        dlg = pk.ConfirmKillDialog.__new__(pk.ConfirmKillDialog)
        dlg.confirmed, dlg.password, dlg._offer_pw = False, None, True
        dlg._pw_var = tk.StringVar(master=self.root, value="")
        dlg.destroy = lambda: None
        dlg._confirm()
        self.assertTrue(dlg.confirmed)
        self.assertIsNone(dlg.password)

    def test_password_is_passed_through(self):
        dlg = pk.ConfirmKillDialog.__new__(pk.ConfirmKillDialog)
        dlg.confirmed, dlg.password, dlg._offer_pw = False, None, True
        dlg._pw_var = tk.StringVar(master=self.root, value="hunter2")
        dlg.destroy = lambda: None
        dlg._confirm()
        self.assertEqual(dlg.password, "hunter2")

    def test_elevation_is_offered_only_on_windows_without_admin(self):
        """No Windows nao ha sudo: um kill negado tem de oferecer o relaunch UAC."""
        asked = []
        real_ask, real_admin = pk.messagebox.askyesno, pk.is_admin
        pk.messagebox.askyesno = lambda t, m: (asked.append((t, m)), False)[1]
        try:
            pk.is_admin = lambda: True
            self.assertFalse(self.app._offer_elevation(1))
            self.assertEqual(asked, [], "ja elevado: nao ha o que oferecer")

            pk.is_admin = lambda: False
            offered = self.app._offer_elevation(2)
            self.assertFalse(offered, "usuario recusou, entao nao relanca")
            if sys.platform == "win32":
                self.assertEqual(len(asked), 1)
                self.assertIn("2 processo(s)", asked[0][1])
            else:
                self.assertEqual(asked, [], "fora do Windows usa-se o campo sudo")
        finally:
            pk.messagebox.askyesno, pk.is_admin = real_ask, real_admin

    def test_tooltip_does_not_stack_windows(self):
        """Regressao: cada <Enter> vazava um Toplevel."""
        btn = tk.Button(self.root, text="x")
        tip = pk.Tooltip(btn, "ajuda")
        tip._show(None)
        first = tip._tip
        tip._show(None)
        self.assertFalse(first.winfo_exists(), "o tooltip anterior vazou")
        tip._hide(None)
        self.assertIsNone(tip._tip)


# ── consistência do empacotamento ─────────────────────────────────────────────

class TestPackaging(unittest.TestCase):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_icons_exist(self):
        """O AppImage nao compila sem o PNG referenciado pelo .desktop."""
        for rel in ("installer/linux/port_killer.png",
                    "installer/windows/port_killer.ico",
                    "installer/macos/port_killer.icns"):
            self.assertTrue(os.path.exists(os.path.join(self.root_dir, *rel.split("/"))), rel)

    def test_desktop_icon_key_matches_a_real_file(self):
        desktop = os.path.join(self.root_dir, "installer", "linux", "port_killer.desktop")
        with open(desktop, encoding="utf-8") as f:
            key = next(l.split("=", 1)[1].strip() for l in f if l.startswith("Icon="))
        self.assertTrue(os.path.exists(
            os.path.join(self.root_dir, "installer", "linux", key + ".png")))

    def test_version_has_a_single_source(self):
        """Nenhum arquivo de build pode carregar a versao hardcoded."""
        import build
        self.assertEqual(build.APP_VERSION, pk.APP_VERSION)
        for rel in ("port_killer.spec", "installer/macos/build_dmg.sh"):
            with open(os.path.join(self.root_dir, *rel.split("/")), encoding="utf-8") as f:
                self.assertNotIn('"%s"' % pk.APP_VERSION, f.read(),
                                 "%s ainda tem a versao hardcoded" % rel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
