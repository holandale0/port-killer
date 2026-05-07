import tkinter as tk
from tkinter import ttk, messagebox
import psutil
import sys
import time


COLORS = {
    "bg": "#1e1e2e",
    "surface": "#313244",
    "border": "#45475a",
    "text": "#cdd6f4",
    "subtext": "#a6adc8",
    "green": "#a6e3a1",
    "red": "#f38ba8",
    "yellow": "#f9e2af",
    "blue": "#89b4fa",
    "button_kill": "#f38ba8",
    "button_kill_hover": "#eb6f92",
    "button_check": "#89b4fa",
    "button_check_hover": "#74c7ec",
}


class PortKillerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Port Killer")
        self.root.geometry("520x380")
        self.root.resizable(False, False)
        self.root.configure(bg=COLORS["bg"])
        self.current_pid = None
        self.current_port = None

        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        self._setup_styles()
        self._build_ui()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Custom.TEntry",
            fieldbackground=COLORS["surface"],
            background=COLORS["surface"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
            bordercolor=COLORS["border"],
            relief="flat",
        )

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=COLORS["bg"])
        header.pack(fill=tk.X, padx=30, pady=(30, 0))

        tk.Label(
            header,
            text="Port Killer",
            font=("Segoe UI", 22, "bold"),
            bg=COLORS["bg"],
            fg=COLORS["blue"],
        ).pack(anchor="w")

        tk.Label(
            header,
            text="Verifique e encerre processos que estão usando uma porta",
            font=("Segoe UI", 10),
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
        ).pack(anchor="w", pady=(2, 0))

        # ── Separator ───────────────────────────────────────────────
        sep = tk.Frame(self.root, height=1, bg=COLORS["border"])
        sep.pack(fill=tk.X, padx=30, pady=20)

        # ── Port input row ──────────────────────────────────────────
        input_row = tk.Frame(self.root, bg=COLORS["bg"])
        input_row.pack(fill=tk.X, padx=30)

        tk.Label(
            input_row,
            text="Porta:",
            font=("Segoe UI", 12),
            bg=COLORS["bg"],
            fg=COLORS["text"],
        ).pack(side=tk.LEFT)

        self.port_var = tk.StringVar()
        self.port_entry = tk.Entry(
            input_row,
            textvariable=self.port_var,
            font=("Segoe UI", 14, "bold"),
            width=8,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightcolor=COLORS["blue"],
            highlightbackground=COLORS["border"],
        )
        self.port_entry.pack(side=tk.LEFT, padx=(12, 12), ipady=6)
        self.port_entry.bind("<Return>", lambda _: self._check_port())
        self.port_entry.focus()

        self.check_btn = tk.Button(
            input_row,
            text="Verificar",
            command=self._check_port,
            font=("Segoe UI", 11, "bold"),
            bg=COLORS["button_check"],
            fg=COLORS["bg"],
            relief="flat",
            padx=18,
            pady=7,
            cursor="hand2",
            activebackground=COLORS["button_check_hover"],
            activeforeground=COLORS["bg"],
        )
        self.check_btn.pack(side=tk.LEFT)

        # ── Status card ─────────────────────────────────────────────
        self.card = tk.Frame(
            self.root,
            bg=COLORS["surface"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )
        self.card.pack(fill=tk.X, padx=30, pady=24)

        card_inner = tk.Frame(self.card, bg=COLORS["surface"])
        card_inner.pack(fill=tk.X, padx=20, pady=16)

        self.status_icon = tk.Label(
            card_inner,
            text="○",
            font=("Segoe UI", 28),
            bg=COLORS["surface"],
            fg=COLORS["subtext"],
        )
        self.status_icon.pack(side=tk.LEFT, padx=(0, 16))

        info_col = tk.Frame(card_inner, bg=COLORS["surface"])
        info_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(
            info_col,
            text="Aguardando consulta...",
            font=("Segoe UI", 13, "bold"),
            bg=COLORS["surface"],
            fg=COLORS["subtext"],
            anchor="w",
        )
        self.status_label.pack(fill=tk.X)

        self.detail_label = tk.Label(
            info_col,
            text="Digite uma porta acima e clique em Verificar",
            font=("Segoe UI", 10),
            bg=COLORS["surface"],
            fg=COLORS["subtext"],
            anchor="w",
        )
        self.detail_label.pack(fill=tk.X, pady=(3, 0))

        # ── Kill button ─────────────────────────────────────────────
        self.kill_btn = tk.Button(
            self.root,
            text="⬛  Encerrar Processo",
            command=self._kill_process,
            font=("Segoe UI", 12, "bold"),
            bg=COLORS["border"],
            fg=COLORS["subtext"],
            relief="flat",
            padx=20,
            pady=10,
            cursor="arrow",
            state=tk.DISABLED,
            activebackground=COLORS["button_kill_hover"],
            activeforeground=COLORS["bg"],
        )
        self.kill_btn.pack(pady=(0, 24))

        # ── Footer ──────────────────────────────────────────────────
        tk.Label(
            self.root,
            text=f"Python {sys.version.split()[0]}  •  psutil {psutil.__version__}  •  {sys.platform}",
            font=("Segoe UI", 8),
            bg=COLORS["bg"],
            fg=COLORS["border"],
        ).pack(side=tk.BOTTOM, pady=8)

    # ── Logic ────────────────────────────────────────────────────────

    def _check_port(self):
        raw = self.port_var.get().strip()
        try:
            port = int(raw)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Porta inválida", "Digite um número entre 1 e 65535.")
            return

        self.current_pid = None
        self.current_port = port
        self._set_state_idle("Verificando...")

        try:
            result = self._find_process_on_port(port)
        except psutil.AccessDenied:
            messagebox.showerror(
                "Permissão negada",
                "Execute como Administrador para visualizar todas as portas do sistema.",
            )
            self._set_state_idle("Sem permissão — execute como Administrador")
            return

        if result is None:
            self._set_state_free(port)
        else:
            pid, proc_name, status = result
            self._set_state_in_use(port, pid, proc_name, status)

    def _find_process_on_port(self, port):
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port:
                pid = conn.pid
                status = conn.status if conn.status else "—"
                proc_name = "Desconhecido"
                if pid:
                    try:
                        proc_name = psutil.Process(pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                return pid, proc_name, status
        return None

    def _kill_process(self):
        if not self.current_pid:
            return

        try:
            proc = psutil.Process(self.current_pid)
            proc_name = proc.name()
        except psutil.NoSuchProcess:
            messagebox.showinfo("Info", "O processo já não existe mais.")
            self._check_port()
            return
        except psutil.AccessDenied:
            proc_name = "Desconhecido"

        confirmed = messagebox.askyesno(
            "Confirmar encerramento",
            f"Encerrar o processo abaixo?\n\n"
            f"  Processo : {proc_name}\n"
            f"  PID      : {self.current_pid}\n"
            f"  Porta    : {self.current_port}",
        )
        if not confirmed:
            return

        try:
            proc = psutil.Process(self.current_pid)
            proc.terminate()
            time.sleep(0.6)
            if proc.is_running():
                proc.kill()
            messagebox.showinfo(
                "Processo encerrado",
                f"O processo '{proc_name}' (PID {self.current_pid}) foi encerrado com sucesso.",
            )
            self._check_port()
        except psutil.NoSuchProcess:
            messagebox.showinfo("Info", "O processo já havia sido encerrado.")
            self._check_port()
        except psutil.AccessDenied:
            messagebox.showerror(
                "Permissão negada",
                "Execute como Administrador para encerrar este processo.",
            )
        except Exception as exc:
            messagebox.showerror("Erro", f"Não foi possível encerrar o processo:\n{exc}")

    # ── UI state helpers ──────────────────────────────────────────────

    def _set_state_idle(self, message="Aguardando consulta..."):
        self.card.configure(highlightbackground=COLORS["border"])
        self.status_icon.configure(text="○", fg=COLORS["subtext"])
        self.status_label.configure(text=message, fg=COLORS["subtext"])
        self.detail_label.configure(text="", fg=COLORS["subtext"])
        self.kill_btn.configure(
            state=tk.DISABLED, bg=COLORS["border"], fg=COLORS["subtext"], cursor="arrow",
            text="⬛  Encerrar Processo"
        )

    def _set_state_free(self, port):
        self.card.configure(highlightbackground=COLORS["green"])
        self.status_icon.configure(text="●", fg=COLORS["green"])
        self.status_label.configure(text=f"Porta {port} está LIVRE", fg=COLORS["green"])
        self.detail_label.configure(
            text="Nenhum processo usando esta porta.", fg=COLORS["subtext"]
        )
        self.kill_btn.configure(
            state=tk.DISABLED, bg=COLORS["border"], fg=COLORS["subtext"], cursor="arrow",
            text="⬛  Encerrar Processo"
        )
        self.current_pid = None

    def _set_state_in_use(self, port, pid, proc_name, status):
        self.current_pid = pid
        self.card.configure(highlightbackground=COLORS["red"])
        self.status_icon.configure(text="●", fg=COLORS["red"])
        self.status_label.configure(text=f"Porta {port} está EM USO", fg=COLORS["red"])
        detail = f"PID: {pid}   •   Processo: {proc_name}   •   Status: {status}"
        self.detail_label.configure(text=detail, fg=COLORS["yellow"])

        if pid:
            self.kill_btn.configure(
                state=tk.NORMAL,
                bg=COLORS["button_kill"],
                fg=COLORS["bg"],
                cursor="hand2",
                text="⬛  Encerrar Processo",
            )
        else:
            self.kill_btn.configure(
                state=tk.DISABLED, bg=COLORS["border"], fg=COLORS["subtext"], cursor="arrow",
                text="⬛  PID indisponível"
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = PortKillerApp(root)
    root.mainloop()
