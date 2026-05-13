# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import sys
import time
import json
import os
import subprocess

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
    try:
        with open(_pins_path()) as f:
            return sorted(set(json.load(f).get("pins", [])))
    except Exception:
        return []

def save_pins(pins):
    try:
        with open(_pins_path(), "w") as f:
            json.dump({"pins": sorted(set(pins))}, f)
    except Exception:
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


def get_process_type(pid, name):
    """Classify process as 'Sistema', 'Aplicação', or 'Desconhecido'."""
    if not pid:
        return "Desconhecido"
    try:
        p = psutil.Process(pid)
        if sys.platform == "win32":
            try:
                uname = (p.username() or "").upper()
                if any(s in uname for s in ("SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE")):
                    return "Sistema"
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
            if name.lower() in _SYSTEM_NAMES_WIN:
                return "Sistema"
            return "Aplicação"
        else:
            try:
                uname = p.username() or ""
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                return "Desconhecido"
            if uname == "root" or name in _SYSTEM_NAMES_UNIX:
                return "Sistema"
            return "Aplicação"
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "Desconhecido"


def get_port_info(port):
    """
    Returns:
      None             — port is free
      "ACCESS_DENIED"  — no permission
      (pid, name, status_label, child_count, proc_type) — port in use
    """
    try:
        connections = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        return "ACCESS_DENIED"

    for conn in connections:
        if conn.laddr and conn.laddr.port == port:
            pid = conn.pid
            name, status_label, child_count = "—", "EM USO", 0
            if pid:
                try:
                    p = psutil.Process(pid)
                    name = p.name()
                    status_label = STATUS_MAP.get(p.status(), p.status().upper())
                    child_count = len(p.children())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            proc_type = get_process_type(pid, name)
            return (pid, name, status_label, child_count, proc_type)
    return None


# ── Confirmation dialog ───────────────────────────────────────────────────────

class Tooltip:
    def __init__(self, widget, text):
        self._widget = widget
        self._text = text
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event):
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() - 26
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self._text,
                 font=("Segoe UI", 8),
                 bg=COLORS["surface2"], fg=COLORS["text"],
                 relief="flat", padx=8, pady=4).pack()

    def _hide(self, event):
        if self._tip:
            self._tip.destroy()
            self._tip = None


class ConfirmKillDialog(tk.Toplevel):
    """Modal confirmation dialog. Shows sudo password field on Linux/macOS non-root."""

    def __init__(self, parent, targets):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.title("Confirmar encerramento")

        self.confirmed = False
        self.password = None
        self._need_pw = sys.platform != "win32" and not is_admin()

        self._build(targets)
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
        self.wait_window()

    def _build(self, targets):
        tk.Label(self, text="⚠  Encerrar processos",
                 font=("Segoe UI", 13, "bold"),
                 bg=COLORS["bg"], fg=COLORS["red"]
                 ).pack(anchor="w", padx=24, pady=(20, 6))

        frame = tk.Frame(self, bg=COLORS["surface"],
                         highlightthickness=1, highlightbackground=COLORS["border"])
        frame.pack(fill=tk.X, padx=24, pady=(0, 8))
        for port, pid, name in targets:
            tk.Label(frame, text=f"  Porta {port}  •  {name}  •  PID {pid}",
                     font=("Segoe UI", 10),
                     bg=COLORS["surface"], fg=COLORS["yellow"],
                     anchor="w").pack(fill=tk.X, padx=12, pady=3)

        tk.Label(self,
                 text="Esta ação é irreversível. Os processos serão\n"
                      "encerrados forçadamente se necessário.",
                 font=("Segoe UI", 9),
                 bg=COLORS["bg"], fg=COLORS["subtext"],
                 justify="left").pack(anchor="w", padx=24, pady=(0, 8))

        if self._need_pw:
            tk.Label(self, text="Senha de administrador (sudo):",
                     font=("Segoe UI", 10),
                     bg=COLORS["bg"], fg=COLORS["text"]
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
        if self._need_pw:
            pw = self._pw_var.get()
            if not pw:
                return
            self.password = pw
        self.confirmed = True
        self.destroy()


# ── Main application ──────────────────────────────────────────────────────────

class PortKillerApp:
    REFRESH_MS = 4000

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
        self._pinned = load_pins()

        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        self._setup_styles()
        self._build_ui()
        self._refresh_list()
        self._schedule_refresh()

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
                 text=f"Python {sys.version.split()[0]}  •  psutil {psutil.__version__}  •  {sys.platform}",
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
            pid, name, status_label, child_count, proc_type = result
            self.current_pid = pid
            self._set_card_in_use(port, pid, name, status_label, child_count, proc_type)

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
        save_pins(self._pinned)
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
        save_pins(self._pinned)
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
        save_pins(self._pinned)
        self._refresh_list()
        self._update_pin_btn()

    # ── List refresh ──────────────────────────────────────────────────────────

    def _refresh_list(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for port in self._pinned:
            result = get_port_info(port)
            if result == "ACCESS_DENIED":
                self.tree.insert("", tk.END,
                                 values=(port, "ERRO", "—", "—", "—", "—"),
                                 tags=("error",))
            elif result is None:
                self.tree.insert("", tk.END,
                                 values=(port, "LIVRE", "—", "—", "—", "—"),
                                 tags=("free",))
            else:
                pid, name, status_label, child_count, proc_type = result
                pid_txt = str(pid) if pid else "—"
                ch_txt = str(child_count) if child_count else "—"
                tag = "active" if status_label == "EM USO" else "idle"
                self.tree.insert("", tk.END,
                                 values=(port, status_label, proc_type, name, pid_txt, ch_txt),
                                 tags=(tag,))

    def _schedule_refresh(self):
        self._refresh_job = self.root.after(self.REFRESH_MS, self._auto_refresh)

    def _auto_refresh(self):
        self._refresh_list()
        self._schedule_refresh()

    # ── Kill operations ───────────────────────────────────────────────────────

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        vals = self.tree.item(iid)["values"]
        # cols: port, status, type, process, pid, children
        port, status, pid_txt, name = int(vals[0]), str(vals[1]), str(vals[4]), str(vals[3])
        if status == "LIVRE" or pid_txt == "—":
            return
        pid = int(pid_txt)
        if messagebox.askyesno("Confirmar",
                               f"Encerrar '{name}' (PID {pid}) na porta {port}?"):
            self._do_kill(pid, password=None)
            self._refresh_list()

    def _kill_from_card(self):
        if not self.current_pid:
            return
        try:
            name = psutil.Process(self.current_pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            name = "Desconhecido"
        if messagebox.askyesno("Confirmar encerramento",
                               f"Encerrar '{name}' (PID {self.current_pid})"
                               f" na porta {self.current_port}?"):
            self._do_kill(self.current_pid, password=None)
            self._check_port()
            self._refresh_list()

    def _kill_all(self):
        targets = []
        for iid in self.tree.get_children():
            vals = self.tree.item(iid)["values"]
            # cols: port, status, type, process, pid, children
            status, pid_txt, name = str(vals[1]), str(vals[4]), str(vals[3])
            if status != "LIVRE" and pid_txt != "—":
                targets.append((int(vals[0]), int(pid_txt), name))
        if not targets:
            messagebox.showinfo("Info", "Nenhum processo ativo na lista pinada.")
            return
        self._run_bulk_kill(targets)

    def _run_bulk_kill(self, targets):
        dlg = ConfirmKillDialog(self.root, targets)
        if not dlg.confirmed:
            return
        killed = failed = 0
        for _, pid, _ in targets:
            if self._do_kill(pid, password=dlg.password):
                killed += 1
            else:
                failed += 1
        parts = [f"{killed} processo(s) encerrado(s)."]
        if failed:
            parts.append(f"{failed} falha(s) — execute como Administrador.")
        messagebox.showinfo("Resultado", "\n".join(parts))
        self._refresh_list()

    def _do_kill(self, pid, password):
        try:
            p = psutil.Process(pid)
            p.terminate()
            time.sleep(0.5)
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                p.kill()
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            if password and sys.platform != "win32":
                return self._sudo_kill(pid, password)
            return False
        except Exception:
            return False

    def _sudo_kill(self, pid, password):
        try:
            r = subprocess.run(
                ["sudo", "-S", "kill", "-9", str(pid)],
                input=f"{password}\n",
                capture_output=True, text=True, timeout=5)
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

    def _set_card_in_use(self, port, pid, name, status_label, child_count, proc_type):
        color = COLORS["red"] if status_label == "EM USO" else COLORS["yellow"]
        self.card.configure(highlightbackground=color)
        self.status_icon.configure(text="●", fg=color)
        self.status_label.configure(text=f"Porta {port} está EM USO", fg=color)
        children_txt = f"   •   Filhos: {child_count}" if child_count else ""
        self.detail_label.configure(
            text=f"PID: {pid}   •   {name}   •   {status_label}   •   {proc_type}{children_txt}",
            fg=COLORS["yellow"])
        if pid:
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
