# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import sys
import json
import os
import subprocess
from collections import namedtuple

# Single source of truth for the version: build.py, port_killer.spec and
# setup.iss all read it from here instead of each carrying a copy.
APP_VERSION = "1.0.0"


def resource_path(name):
    """Locate a bundled data file, both frozen (PyInstaller) and from source."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

COLORS = {
    "bg":                 "#1e1e2e",
    "surface":            "#313244",
    "surface2":           "#45475a",
    "border":             "#45475a",
    "border2":            "#585b70",
    "text":               "#cdd6f4",
    "subtext":            "#a6adc8",
    "green":              "#a6e3a1",
    "red":                "#f38ba8",
    "yellow":             "#f9e2af",
    "blue":               "#89b4fa",
    "button_kill":        "#f38ba8",
    "button_kill_hover":  "#eb6f92",
    "button_check":       "#89b4fa",
    "button_check_hover": "#74c7ec",
    "button_pin":         "#a6e3a1",
    "button_pin_hover":   "#94d39b",
    "tree_bg":            "#181825",
    "sash":               "#313244",
}

STATUS_MAP = {
    "running":      "EM USO",
    "sleeping":     "DORMINDO",
    "stopped":      "PARADO",
    "tracing-stop": "PARADO",
    "parked":       "PARADO",
    "zombie":       "ZUMBI",
    "dead":         "MORTO",
    "disk-sleep":   "AGUARD. E/S",
    "idle":         "OCIOSO",
    "waking":       "ACORDANDO",
    "locked":       "BLOQUEADO",
    "waiting":      "AGUARDANDO",
}

_SYSTEM_NAMES_WIN = frozenset({
    "system", "registry", "idle", "svchost.exe", "lsass.exe", "winlogon.exe",
    "csrss.exe", "smss.exe", "wininit.exe", "services.exe", "spoolsv.exe",
    "dwm.exe", "fontdrvhost.exe", "lsm.exe", "ntoskrnl.exe",
})

# A kill target, resolved at the moment the user asks for it. `create_time`
# pins the identity of the process: a PID alone is not a stable handle, and
# the OS may hand it to something else while the confirmation dialog is open.
Target = namedtuple("Target", "port pid name create_time children")

# What a port check found. `pids` holds every process bound to the port —
# SO_REUSEPORT (nginx/node cluster) and dual-stack listeners put more than one
# there, and killing only the first leaves the port occupied.
PortInfo = namedtuple("PortInfo", "pid name status children proc_type pids")

_SYSTEM_NAMES_UNIX = frozenset({
    "systemd", "init", "launchd", "kthreadd", "udevd", "NetworkManager",
    "sshd", "cron", "rsyslogd", "dbus-daemon", "cupsd", "avahi-daemon",
})


# ── Persistent storage ────────────────────────────────────────────────────────

def _pins_path():
    base = (os.environ.get("APPDATA", os.path.expanduser("~"))
            if sys.platform == "win32" else os.path.expanduser("~"))
    return os.path.join(base, ".port_killer_pins.json")

def load_pins():
    """
    Reads the pinned ports.

    Returns (pins, writable). `writable` is False when the file exists but
    could not be read — saving over it would destroy pins we never saw, so
    the caller must refuse to write until the user acts.

    A single malformed entry is skipped rather than discarding the whole
    list, and unparseable JSON is moved aside to <file>.corrupt instead of
    being silently overwritten on the next save.
    """
    path = _pins_path()
    if not os.path.exists(path):
        return [], True

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except ValueError:
        try:
            os.replace(path, path + ".corrupt")
        except OSError:
            return [], False
        return [], True
    except OSError:
        return [], False

    entries = raw.get("pins") if isinstance(raw, dict) else None
    pins = set()
    for item in entries or []:
        try:
            port = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535:
            pins.add(port)
    return sorted(pins), True

def save_pins(pins):
    """Atomic write — a crash mid-save can no longer truncate the pin list."""
    path = _pins_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"pins": sorted(set(pins))}, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── System helpers ────────────────────────────────────────────────────────────

def is_admin():
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.getuid() == 0


def system_snapshot():
    """
    One pass over the whole system, shared by every port in a refresh.

    Enumerating connections and the process tree once per port made refresh
    cost grow linearly with the number of pins (measured: 470 ms for 10 pins,
    blocking the Tk main thread every 4 s).

    Returns (ports, child_counts) where `ports` maps a local port to the list
    of connections on it, or is the "ACCESS_DENIED" sentinel.
    """
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError, RuntimeError):
        return "ACCESS_DENIED", {}

    ports = {}
    for conn in connections:
        if conn.laddr:
            ports.setdefault(conn.laddr.port, []).append(conn)

    # A listening socket is what actually holds a port. Most connections are
    # not listeners (322 of 434 on a normal desktop), so taking whichever came
    # first could describe the port by an unrelated ESTABLISHED socket — or by
    # some other process whose ephemeral local port happened to collide.
    for port, conns in ports.items():
        listening = [c for c in conns if c.status == psutil.CONN_LISTEN]
        if listening:
            ports[port] = listening

    # psutil._ppid_map() is the same bulk syscall Process.children() uses, but
    # paid once instead of once per port. Private API, so degrade gracefully.
    child_counts = {}
    ppid_map = getattr(psutil, "_ppid_map", None)
    if ppid_map is not None:
        try:
            for ppid in ppid_map().values():
                child_counts[ppid] = child_counts.get(ppid, 0) + 1
        except Exception:
            child_counts = {}
    return ports, child_counts


def get_process_type(pid, name, proc=None):
    """
    Classify process as 'Sistema', 'Aplicação', or 'Desconhecido'.

    Unreadable ownership means 'Desconhecido', never 'Aplicação'. On Windows
    an AccessDenied from username() is precisely what a privileged process
    looks like to an unelevated caller, so the old fallback pinned the
    safest-looking label onto the least safe processes: services such as
    oracle.exe, tnslsnr.exe and postgres.exe all read as ordinary
    applications. This is the label the user leans on before killing, so it
    has to fail closed — as the POSIX branch already did.
    """
    if not pid:
        return "Desconhecido"

    # Checked first: it needs no syscall, and it still answers for processes
    # whose owner we are not allowed to read.
    if sys.platform == "win32":
        if name.lower() in _SYSTEM_NAMES_WIN:
            return "Sistema"
    elif name in _SYSTEM_NAMES_UNIX:
        return "Sistema"

    try:
        uname = (proc or psutil.Process(pid)).username() or ""
    except (psutil.Error, OSError):
        return "Desconhecido"

    if sys.platform == "win32":
        if any(s in uname.upper() for s in ("SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE")):
            return "Sistema"
    elif uname == "root":
        return "Sistema"
    return "Aplicação"


def get_port_info(port, snapshot=None):
    """
    Returns:
      None             — port is free
      "ACCESS_DENIED"  — no permission
      PortInfo         — port in use

    Pass `snapshot` (from system_snapshot()) to check many ports without
    re-scanning the system for each one.
    """
    ports, child_counts = snapshot if snapshot is not None else system_snapshot()
    if ports == "ACCESS_DENIED":
        return "ACCESS_DENIED"

    conns = ports.get(port)
    if not conns:
        return None

    pids = []
    for conn in conns:
        if conn.pid and conn.pid not in pids:
            pids.append(conn.pid)

    pid = pids[0] if pids else conns[0].pid
    name, status_label, child_count = "—", "EM USO", 0
    p = None
    if pid:
        try:
            p = psutil.Process(pid)
            name = p.name()
            status = p.status()
            status_label = STATUS_MAP.get(status, status.upper())
            child_count = child_counts.get(pid, 0) if child_counts else len(p.children())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    proc_type = get_process_type(pid, name, proc=p)
    return PortInfo(pid, name, status_label, child_count, proc_type, pids)


# ── Confirmation dialog ───────────────────────────────────────────────────────

class Tooltip:
    def __init__(self, widget, text):
        self._widget = widget
        self._text = text
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<Destroy>", self._hide)      # else the tip outlives its widget

    def _show(self, event):
        self._hide(event)                         # never stack two tips
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() - 26
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self._text,
                 font=("Segoe UI", 8),
                 bg=COLORS["surface2"], fg=COLORS["text"],
                 relief="flat", padx=8, pady=4).pack()

    def _hide(self, event=None):
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class ConfirmKillDialog(tk.Toplevel):
    """Modal confirmation dialog. Shows sudo password field on Linux/macOS non-root."""

    def __init__(self, parent, targets):
        super().__init__(parent)
        self.withdraw()                       # place it before it is ever drawn
        self.transient(parent)
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.title("Confirmar encerramento")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.confirmed = False
        self.password = None
        self._offer_pw = sys.platform != "win32" and not is_admin()

        self._build(targets)
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # X11 refuses a grab on a window that is not yet viewable, which used
        # to raise TclError on Linux. Wait for the map before grabbing.
        self.deiconify()
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass                              # worst case the dialog is not modal
        self.wait_window()

    def _build(self, targets):
        tk.Label(self, text="⚠  Encerrar processos",
                 font=("Segoe UI", 13, "bold"),
                 bg=COLORS["bg"], fg=COLORS["red"]
                 ).pack(anchor="w", padx=24, pady=(20, 6))

        frame = tk.Frame(self, bg=COLORS["surface"],
                         highlightthickness=1, highlightbackground=COLORS["border"])
        frame.pack(fill=tk.X, padx=24, pady=(0, 8))
        for t in targets:
            extra = f"  (+{t.children} filho(s))" if t.children else ""
            tk.Label(frame,
                     text=f"  Porta {t.port}  •  {t.name}  •  PID {t.pid}{extra}",
                     font=("Segoe UI", 10),
                     bg=COLORS["surface"], fg=COLORS["yellow"],
                     anchor="w").pack(fill=tk.X, padx=12, pady=3)

        tk.Label(self,
                 text="Esta ação é irreversível. Os processos filhos também\n"
                      "serão encerrados, à força se necessário.",
                 font=("Segoe UI", 9),
                 bg=COLORS["bg"], fg=COLORS["subtext"],
                 justify="left").pack(anchor="w", padx=24, pady=(0, 8))

        if self._offer_pw:
            # Optional: your own processes die without sudo. Demanding a
            # password up front blocked killing your own dev server, and an
            # empty field made the Encerrar button silently do nothing.
            tk.Label(self, text="Senha de administrador (sudo) — opcional:",
                     font=("Segoe UI", 10),
                     bg=COLORS["bg"], fg=COLORS["text"]
                     ).pack(anchor="w", padx=24)
            tk.Label(self, text="Necessária apenas para processos de outro usuário.",
                     font=("Segoe UI", 8),
                     bg=COLORS["bg"], fg=COLORS["subtext"]
                     ).pack(anchor="w", padx=24)
            self._pw_var = tk.StringVar()
            pw = tk.Entry(self, textvariable=self._pw_var, show="●",
                          font=("Segoe UI", 12),
                          bg=COLORS["surface"], fg=COLORS["text"],
                          insertbackground=COLORS["text"], relief="flat",
                          highlightthickness=1,
                          highlightcolor=COLORS["blue"],
                          highlightbackground=COLORS["border"])
            pw.pack(fill=tk.X, padx=24, pady=(4, 12), ipady=6)
            pw.focus()
            pw.bind("<Return>", lambda _: self._confirm())

        row = tk.Frame(self, bg=COLORS["bg"])
        row.pack(fill=tk.X, padx=24, pady=(4, 20))

        tk.Button(row, text="Cancelar", command=self.destroy,
                  font=("Segoe UI", 10),
                  bg=COLORS["surface2"], fg=COLORS["subtext"],
                  relief="flat", padx=16, pady=8, cursor="hand2",
                  activebackground=COLORS["border"],
                  activeforeground=COLORS["text"]
                  ).pack(side=tk.RIGHT, padx=(8, 0))

        tk.Button(row, text="⬛  Encerrar", command=self._confirm,
                  font=("Segoe UI", 10, "bold"),
                  bg=COLORS["button_kill"], fg=COLORS["bg"],
                  relief="flat", padx=16, pady=8, cursor="hand2",
                  activebackground=COLORS["button_kill_hover"],
                  activeforeground=COLORS["bg"]
                  ).pack(side=tk.RIGHT)

    def _confirm(self):
        if self._offer_pw:
            self.password = self._pw_var.get() or None
        self.confirmed = True
        self.destroy()


# ── Main application ──────────────────────────────────────────────────────────

class PortKillerApp:
    REFRESH_MS = 4000
    TERM_GRACE_S = 1.5      # time a process gets to shut down cleanly
    KILL_GRACE_S = 1.0      # time to disappear after SIGKILL

    def __init__(self, root):
        self.root = root
        self.root.title("Port Killer")
        self.root.geometry("720x540")
        self.root.minsize(580, 420)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.current_pid = None
        self.current_port = None
        self._refresh_job = None
        self._pinned, self._pins_writable = load_pins()

        self._set_window_icon()

        self._setup_styles()
        self._build_ui()
        self._refresh_list()
        self._schedule_refresh()

        if not self._pins_writable:
            self.root.after(100, self._warn_pins_unreadable)

    def _set_window_icon(self):
        # The previous iconbitmap(default="") was a no-op, so the app ran with
        # Tk's default icon everywhere. Keep a reference: Tk does not own the
        # PhotoImage and it would be garbage collected out from under us.
        for name in ("port_killer.png", "port_killer.ico"):
            path = resource_path(name)
            if not os.path.exists(path):
                continue
            try:
                if name.endswith(".ico") and sys.platform == "win32":
                    self.root.iconbitmap(path)
                else:
                    self._icon = tk.PhotoImage(file=path)
                    self.root.iconphoto(True, self._icon)
                return
            except Exception:
                continue

    def _warn_pins_unreadable(self):
        messagebox.showwarning(
            "Lista de portas indisponível",
            f"Não foi possível ler:\n{_pins_path()}\n\n"
            "A lista começou vazia e não será salva nesta sessão, para não "
            "sobrescrever as portas que já estão no arquivo.")

    def _save_pins(self):
        """Never write over a pin file we failed to read — it may hold pins we never saw."""
        if self._pins_writable:
            save_pins(self._pinned)

    # ── Styles ────────────────────────────────────────────────────────────────

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Custom.TEntry",
                    fieldbackground=COLORS["surface"],
                    background=COLORS["surface"],
                    foreground=COLORS["text"],
                    insertcolor=COLORS["text"],
                    bordercolor=COLORS["border"],
                    relief="flat")
        for name in ("Active.Treeview",):
            s.configure(name,
                        background=COLORS["tree_bg"],
                        foreground=COLORS["text"],
                        fieldbackground=COLORS["tree_bg"],
                        borderwidth=0, rowheight=22,
                        font=("Segoe UI", 9))
            s.configure(f"{name}.Heading",
                        background=COLORS["surface"],
                        foreground=COLORS["subtext"],
                        borderwidth=0,
                        font=("Segoe UI", 9, "bold"),
                        relief="flat")
            s.map(name,
                  background=[("selected", COLORS["surface2"])],
                  foreground=[("selected", COLORS["text"])])
            s.map(f"{name}.Heading",
                  background=[("active", COLORS["surface2"])])

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=COLORS["bg"])
        hdr.pack(fill=tk.X, padx=24, pady=(12, 0))
        tk.Label(hdr, text="Port Killer",
                 font=("Segoe UI", 16, "bold"),
                 bg=COLORS["bg"], fg=COLORS["blue"]).pack(side=tk.LEFT, anchor="w")
        tk.Label(hdr, text="Verifique, pine e encerre processos por porta",
                 font=("Segoe UI", 8),
                 bg=COLORS["bg"], fg=COLORS["subtext"]).pack(side=tk.LEFT, anchor="w", padx=(10, 0))

        tk.Frame(self.root, height=1, bg=COLORS["border"]).pack(fill=tk.X, padx=24, pady=8)

        # Input row
        row = tk.Frame(self.root, bg=COLORS["bg"])
        row.pack(fill=tk.X, padx=24)

        tk.Label(row, text="Porta:",
                 font=("Segoe UI", 10),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(side=tk.LEFT)

        self.port_var = tk.StringVar()
        self.port_entry = tk.Entry(
            row, textvariable=self.port_var,
            font=("Segoe UI", 11, "bold"), width=7,
            bg=COLORS["surface"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat",
            highlightthickness=1,
            highlightcolor=COLORS["blue"],
            highlightbackground=COLORS["border"])
        self.port_entry.pack(side=tk.LEFT, padx=(8, 8), ipady=3)
        self.port_entry.bind("<Return>", lambda _: self._check_port())
        self.port_entry.focus()

        self.check_btn = tk.Button(
            row, text="Verificar", command=self._check_port,
            font=("Segoe UI", 9, "bold"),
            bg=COLORS["button_check"], fg=COLORS["bg"],
            relief="flat", padx=10, pady=4, cursor="hand2",
            activebackground=COLORS["button_check_hover"],
            activeforeground=COLORS["bg"])
        self.check_btn.pack(side=tk.LEFT)

        self.pin_btn = tk.Button(
            row, text="📌  Pinar", command=self._pin_current,
            font=("Segoe UI", 9, "bold"),
            bg=COLORS["surface2"], fg=COLORS["subtext"],
            relief="flat", padx=10, pady=4, cursor="arrow",
            state=tk.DISABLED,
            activebackground=COLORS["button_pin_hover"],
            activeforeground=COLORS["bg"])
        self.pin_btn.pack(side=tk.LEFT, padx=(6, 0))

        # Status card
        self.card = tk.Frame(self.root, bg=COLORS["surface"],
                             highlightthickness=1,
                             highlightbackground=COLORS["border"])
        self.card.pack(fill=tk.X, padx=24, pady=6)

        inner = tk.Frame(self.card, bg=COLORS["surface"])
        inner.pack(fill=tk.X, padx=12, pady=6)

        self.status_icon = tk.Label(inner, text="○",
                                    font=("Segoe UI", 14),
                                    bg=COLORS["surface"], fg=COLORS["subtext"])
        self.status_icon.pack(side=tk.LEFT, padx=(0, 8))

        col = tk.Frame(inner, bg=COLORS["surface"])
        col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(col, text="Aguardando consulta...",
                                     font=("Segoe UI", 10, "bold"),
                                     bg=COLORS["surface"], fg=COLORS["subtext"],
                                     anchor="w")
        self.status_label.pack(fill=tk.X)

        self.detail_label = tk.Label(col,
                                     text="Digite uma porta acima e clique em Verificar",
                                     font=("Segoe UI", 8),
                                     bg=COLORS["surface"], fg=COLORS["subtext"],
                                     anchor="w")
        self.detail_label.pack(fill=tk.X)

        self.kill_btn = tk.Button(inner, text="⬛  Encerrar",
                                  command=self._kill_from_card,
                                  font=("Segoe UI", 9, "bold"),
                                  bg=COLORS["border"], fg=COLORS["subtext"],
                                  relief="flat", padx=10, pady=4,
                                  cursor="arrow", state=tk.DISABLED,
                                  activebackground=COLORS["button_kill_hover"],
                                  activeforeground=COLORS["bg"])
        self.kill_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # Pinned section header
        ph = tk.Frame(self.root, bg=COLORS["bg"])
        ph.pack(fill=tk.X, padx=24, pady=(2, 2))

        tk.Label(ph, text="📌  Portas Pinadas",
                 font=("Segoe UI", 9, "bold"),
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(side=tk.LEFT)

        tk.Label(ph, text="atualiza a cada 4s  ",
                 font=("Segoe UI", 7),
                 bg=COLORS["bg"], fg=COLORS["border2"]).pack(side=tk.RIGHT)

        tk.Button(ph, text="↻", command=self._refresh_list,
                  font=("Segoe UI", 11),
                  bg=COLORS["surface"], fg=COLORS["blue"],
                  relief="flat", padx=6, pady=0, cursor="hand2",
                  activebackground=COLORS["surface2"],
                  activeforeground=COLORS["blue"]).pack(side=tk.RIGHT, padx=(0, 4))

        # ── Table ─────────────────────────────────────────────────────────────
        tf = tk.Frame(self.root, bg=COLORS["bg"])
        tf.pack(fill=tk.X, padx=24, pady=(2, 0))

        cols = ("port", "status", "type", "process", "pid", "children")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings",
                                 style="Active.Treeview", selectmode="extended",
                                 height=7)
        self.tree.heading("port",     text="Porta",    anchor="center")
        self.tree.heading("status",   text="Status",   anchor="w")
        self.tree.heading("type",     text="Tipo",     anchor="w")
        self.tree.heading("process",  text="Processo", anchor="w")
        self.tree.heading("pid",      text="PID",      anchor="center")
        self.tree.heading("children", text="Filhos",   anchor="center")

        self.tree.column("port",     width=60,  minwidth=50,  anchor="center", stretch=False)
        self.tree.column("status",   width=100, minwidth=80,  anchor="w",      stretch=False)
        self.tree.column("type",     width=100, minwidth=80,  anchor="w",      stretch=False)
        self.tree.column("process",  width=200, minwidth=120, anchor="w",      stretch=True)
        self.tree.column("pid",      width=75,  minwidth=55,  anchor="center", stretch=False)
        self.tree.column("children", width=60,  minwidth=45,  anchor="center", stretch=False)

        self.tree.tag_configure("active",  foreground=COLORS["red"])
        self.tree.tag_configure("idle",    foreground=COLORS["yellow"])
        self.tree.tag_configure("free",    foreground=COLORS["green"])
        self.tree.tag_configure("error",   foreground=COLORS["subtext"])

        sb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_double_click)

        # ── Action buttons ────────────────────────────────────────────────────
        ab = tk.Frame(self.root, bg=COLORS["bg"])
        ab.pack(fill=tk.X, padx=24, pady=(6, 0))

        tk.Button(ab, text="✕  Remover da lista",
                  command=self._unpin_selected,
                  font=("Segoe UI", 8),
                  bg=COLORS["surface"], fg=COLORS["subtext"],
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  activebackground=COLORS["surface2"],
                  activeforeground=COLORS["text"]).pack(side=tk.LEFT)

        tk.Button(ab, text="🗑  Limpar lista",
                  command=self._clear_all_pins,
                  font=("Segoe UI", 8),
                  bg=COLORS["surface"], fg=COLORS["subtext"],
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  activebackground=COLORS["surface2"],
                  activeforeground=COLORS["text"]).pack(side=tk.LEFT, padx=(6, 0))

        kill_all_btn = tk.Button(ab, text="⬛  Encerrar todas",
                                 command=self._kill_all,
                                 font=("Segoe UI", 8, "bold"),
                                 bg=COLORS["button_kill"], fg=COLORS["bg"],
                                 relief="flat", padx=10, pady=4, cursor="hand2",
                                 activebackground=COLORS["button_kill_hover"],
                                 activeforeground=COLORS["bg"])
        kill_all_btn.pack(side=tk.LEFT, padx=(6, 0))
        Tooltip(kill_all_btn, "Liberará todas as portas listadas com status diferente de LIVRE")

        # Footer
        tk.Label(self.root,
                 text=f"v{APP_VERSION}  •  Python {sys.version.split()[0]}"
                      f"  •  psutil {psutil.__version__}  •  {sys.platform}",
                 font=("Segoe UI", 7),
                 bg=COLORS["bg"], fg=COLORS["border"]
                 ).pack(side=tk.BOTTOM, pady=3)

    # ── Port check ────────────────────────────────────────────────────────────

    def _check_port(self):
        raw = self.port_var.get().strip()
        try:
            port = int(raw)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            # Leaving the previous port selected let "Pinar" pin a port that
            # was no longer the one on screen.
            self.current_port = None
            self.current_pid = None
            self._set_card_idle("Porta inválida")
            self._update_pin_btn()
            messagebox.showerror("Porta inválida", "Digite um número entre 1 e 65535.")
            return

        self.current_port = port
        self.current_pid = None
        self._set_card_idle("Verificando...")
        self._update_pin_btn()

        result = get_port_info(port)
        if result == "ACCESS_DENIED":
            self._set_card_idle("Sem permissão — execute como Administrador")
            return

        if result is None:
            self._set_card_free(port)
        else:
            self.current_pid = result.pid
            self._set_card_in_use(port, result)

        self._update_pin_btn()

    def _update_pin_btn(self):
        if self.current_port is None:
            self.pin_btn.configure(state=tk.DISABLED,
                                   bg=COLORS["surface2"], fg=COLORS["subtext"],
                                   cursor="arrow", text="📌  Pinar")
            return
        if self.current_port in self._pinned:
            self.pin_btn.configure(state=tk.DISABLED,
                                   bg=COLORS["surface2"], fg=COLORS["green"],
                                   cursor="arrow", text="✓  Pinada")
        else:
            self.pin_btn.configure(state=tk.NORMAL,
                                   bg=COLORS["button_pin"], fg=COLORS["bg"],
                                   cursor="hand2", text="📌  Pinar")

    # ── Pin management ────────────────────────────────────────────────────────

    def _pin_current(self):
        if self.current_port is None or self.current_port in self._pinned:
            return
        self._pinned.append(self.current_port)
        self._pinned.sort()
        self._save_pins()
        self._refresh_list()
        self._update_pin_btn()

    def _unpin_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Seleção vazia", "Selecione ao menos uma porta na lista.")
            return
        for iid in sel:
            port = int(self.tree.item(iid)["values"][0])
            if port in self._pinned:
                self._pinned.remove(port)
        self._save_pins()
        self._refresh_list()
        self._update_pin_btn()

    def _clear_all_pins(self):
        if not self._pinned:
            messagebox.showinfo("Lista vazia", "Não há portas pinadas para remover.")
            return
        if not messagebox.askyesno("Limpar lista",
                                   f"Remover todas as {len(self._pinned)} porta(s) da lista?\n\n"
                                   "Os processos não serão encerrados."):
            return
        self._pinned.clear()
        self._save_pins()
        self._refresh_list()
        self._update_pin_btn()

    # ── List refresh ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_for(port, snapshot):
        result = get_port_info(port, snapshot)
        if result == "ACCESS_DENIED":
            return (port, "ERRO", "—", "—", "—", "—"), "error"
        if result is None:
            return (port, "LIVRE", "—", "—", "—", "—"), "free"
        pid_txt = str(result.pid) if result.pid else "—"
        if len(result.pids) > 1:
            pid_txt += f" +{len(result.pids) - 1}"      # SO_REUSEPORT / dual-stack
        ch_txt = str(result.children) if result.children else "—"
        tag = "active" if result.status == "EM USO" else "idle"
        return (port, result.status, result.proc_type, result.name, pid_txt, ch_txt), tag

    def _refresh_list(self):
        # Rows are keyed by port and updated in place. Rebuilding the tree
        # cleared the selection on every tick, so "Remover da lista" only
        # worked if the user clicked within 4 s of selecting.
        snapshot = system_snapshot()
        wanted = {str(port) for port in self._pinned}

        for iid in self.tree.get_children():
            if iid not in wanted:
                self.tree.delete(iid)

        for index, port in enumerate(self._pinned):
            iid = str(port)
            values, tag = self._row_for(port, snapshot)
            if self.tree.exists(iid):
                self.tree.item(iid, values=values, tags=(tag,))
                self.tree.move(iid, "", index)
            else:
                self.tree.insert("", index, iid=iid, values=values, tags=(tag,))

    def _schedule_refresh(self):
        self._refresh_job = self.root.after(self.REFRESH_MS, self._auto_refresh)

    def _auto_refresh(self):
        # A single unexpected error used to stop the timer for good, freezing
        # the list with no visible sign of it (the build runs console=False).
        try:
            self._refresh_list()
        except Exception:
            pass
        finally:
            self._schedule_refresh()

    # ── Kill operations ───────────────────────────────────────────────────────

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        vals = self.tree.item(iid)["values"]
        # cols: port, status, type, process, pid, children
        port, status, pid_txt = int(vals[0]), str(vals[1]), str(vals[4])
        if status == "LIVRE" or pid_txt == "—":
            return
        self._run_kill(self._resolve_targets([port]))

    def _kill_from_card(self):
        if not self.current_port:
            return
        if self._run_kill(self._resolve_targets([self.current_port])):
            self._check_port()

    def _kill_all(self):
        self._run_kill(self._resolve_targets(self._pinned))

    @staticmethod
    def _resolve_targets(ports):
        """
        Ask the OS who owns these ports *now*.

        Targets used to be read off the table, which the 4 s timer had already
        rewritten — and could rewrite again while the dialog was open. The
        table is a view; it is not a safe source of PIDs to kill.
        """
        snapshot = system_snapshot()
        targets, claimed = [], set()
        for port in ports:
            result = get_port_info(port, snapshot)
            if result is None or result == "ACCESS_DENIED":
                continue
            # One target per process on the port: with SO_REUSEPORT the port
            # stays bound unless every one of them goes.
            for pid in result.pids:
                if pid in claimed:
                    continue          # one process can hold several pinned ports
                claimed.add(pid)
                try:
                    proc = psutil.Process(pid)
                    create_time = proc.create_time()
                    name = proc.name()
                except (psutil.Error, OSError):
                    continue
                try:
                    children = len(proc.children(recursive=True))
                except (psutil.Error, OSError):
                    children = 0
                targets.append(Target(port, pid, name, create_time, children))
        return targets

    def _run_kill(self, targets):
        """
        The single path for every kill: confirmation, the sudo prompt where
        one is needed, and a report of what actually happened. Double-click
        and the card button used to bypass all three — a denied kill was
        indistinguishable from a successful one.

        Returns True if the user confirmed.
        """
        if not targets:
            messagebox.showinfo("Info", "Nenhum processo ativo para encerrar.")
            return False

        # The timer must not rewrite the table while the user reads the
        # dialog — and must not race the kills that follow.
        self._pause_refresh()
        try:
            dlg = ConfirmKillDialog(self.root, targets)
            if not dlg.confirmed:
                return False

            tally = {"killed": 0, "denied": 0, "stale": 0}
            for t in targets:
                tally[self._do_kill(t.pid, dlg.password, t.create_time)] += 1
        finally:
            self._resume_refresh()

        self._refresh_list()
        if tally["denied"] and self._offer_elevation(tally["denied"]):
            return True

        parts = [f"{tally['killed']} processo(s) encerrado(s)."]
        if tally["stale"]:
            parts.append(f"{tally['stale']} ignorado(s) — o PID passou a "
                         "pertencer a outro processo.")
        if tally["denied"]:
            hint = ("execute como Administrador."
                    if sys.platform == "win32" else "permissão negada.")
            parts.append(f"{tally['denied']} falha(s) — {hint}")

        show = messagebox.showwarning if len(parts) > 1 else messagebox.showinfo
        show("Resultado", "\n".join(parts))
        return True

    def _offer_elevation(self, denied):
        """
        Windows has no sudo prompt to fall back on, so a denied kill used to
        end at "execute como Administrador" with no way to actually do it.
        Offer the UAC relaunch instead. Returns True if we are restarting.
        """
        if sys.platform != "win32" or is_admin():
            return False
        if not messagebox.askyesno(
                "Permissão negada",
                f"{denied} processo(s) exigem privilégios de Administrador.\n\n"
                "Reabrir o Port Killer como Administrador?"):
            return False
        try:
            import ctypes
            if getattr(sys, "frozen", False):
                target, params = sys.executable, ""
            else:
                target = sys.executable
                params = f'"{os.path.abspath(__file__)}"'
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", target, params, os.getcwd(), 1)
            if rc <= 32:                       # ShellExecuteW error, incl. user declining UAC
                return False
        except Exception:
            return False
        self._on_close()
        return True

    def _pause_refresh(self):
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
            self._refresh_job = None

    def _resume_refresh(self):
        if not self._refresh_job:
            self._schedule_refresh()

    def _do_kill(self, pid, password, create_time=None):
        """
        Terminate the process *and its children*, then confirm they are gone.

        The app has always shown a "Filhos" column because it matters: killing
        a lone parent leaves orphans holding the port, which is the everyday
        npm/node case the tool exists for. The old version also reported
        success without ever checking whether the process actually died.

        Returns 'killed', 'denied', or 'stale' (PID now holds another process).
        """
        try:
            parent = psutil.Process(pid)
            if create_time is not None and parent.create_time() != create_time:
                return "stale"
        except psutil.NoSuchProcess:
            return "killed"
        except (psutil.Error, OSError):
            return "denied"

        try:
            family = parent.children(recursive=True)
        except (psutil.Error, OSError):
            family = []
        family.append(parent)

        alive = self._signal_family(family, "terminate", self.TERM_GRACE_S)
        if alive:
            alive = self._signal_family(alive, "kill", self.KILL_GRACE_S)
        if alive and password and sys.platform != "win32":
            alive = self._sudo_family(alive, password)
        return "denied" if alive else "killed"

    @classmethod
    def _signal_family(cls, procs, action, timeout):
        """Signal every process, then report who is still standing."""
        for proc in procs:
            try:
                getattr(proc, action)()
            except (psutil.Error, OSError):
                pass
        _, alive = psutil.wait_procs(procs, timeout=timeout)
        return [p for p in alive if cls._still_holding(p)]

    @staticmethod
    def _still_holding(proc):
        """A zombie has already released its ports and cannot be killed again."""
        try:
            return proc.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except (psutil.Error, OSError):
            return True

    def _sudo_family(self, procs, password):
        """
        Escalate for whatever survived: TERM first, KILL only if needed, and
        one sudo call per round instead of one per PID.
        """
        for sig, grace in (("-TERM", self.TERM_GRACE_S), ("-KILL", self.KILL_GRACE_S)):
            if not procs:
                break
            self._sudo_kill([p.pid for p in procs], password, sig)
            _, procs = psutil.wait_procs(procs, timeout=grace)
            procs = [p for p in procs if self._still_holding(p)]
        return procs

    @staticmethod
    def _sudo_kill(pids, password, sig="-KILL"):
        if not pids:
            return True
        try:
            r = subprocess.run(
                ["sudo", "-S", "-p", "", "kill", sig] + [str(p) for p in pids],
                input=f"{password}\n",
                capture_output=True, text=True, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    # ── Card state helpers ────────────────────────────────────────────────────

    def _set_card_idle(self, msg="Aguardando consulta..."):
        self.card.configure(highlightbackground=COLORS["border"])
        self.status_icon.configure(text="○", fg=COLORS["subtext"])
        self.status_label.configure(text=msg, fg=COLORS["subtext"])
        self.detail_label.configure(text="", fg=COLORS["subtext"])
        self.kill_btn.configure(state=tk.DISABLED,
                                bg=COLORS["border"], fg=COLORS["subtext"], cursor="arrow")

    def _set_card_free(self, port):
        self.card.configure(highlightbackground=COLORS["green"])
        self.status_icon.configure(text="●", fg=COLORS["green"])
        self.status_label.configure(text=f"Porta {port} está LIVRE", fg=COLORS["green"])
        self.detail_label.configure(text="Nenhum processo usando esta porta.",
                                    fg=COLORS["subtext"])
        self.kill_btn.configure(state=tk.DISABLED,
                                bg=COLORS["border"], fg=COLORS["subtext"], cursor="arrow")

    def _set_card_in_use(self, port, info):
        color = COLORS["red"] if info.status == "EM USO" else COLORS["yellow"]
        self.card.configure(highlightbackground=color)
        self.status_icon.configure(text="●", fg=color)
        self.status_label.configure(text=f"Porta {port} está EM USO", fg=color)
        children_txt = f"   •   Filhos: {info.children}" if info.children else ""
        extra_txt = (f"   •   +{len(info.pids) - 1} processo(s) na mesma porta"
                     if len(info.pids) > 1 else "")
        self.detail_label.configure(
            text=f"PID: {info.pid}   •   {info.name}   •   {info.status}"
                 f"   •   {info.proc_type}{children_txt}{extra_txt}",
            fg=COLORS["yellow"])
        if info.pid:
            self.kill_btn.configure(state=tk.NORMAL,
                                    bg=COLORS["button_kill"], fg=COLORS["bg"],
                                    cursor="hand2")
        else:
            self.kill_btn.configure(state=tk.DISABLED,
                                    bg=COLORS["border"], fg=COLORS["subtext"], cursor="arrow")

    # ── Window close ──────────────────────────────────────────────────────────

    def _on_close(self):
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
        self.root.destroy()



if __name__ == "__main__":
    root = tk.Tk()
    app = PortKillerApp(root)
    root.mainloop()
