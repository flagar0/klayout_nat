"""LiveDRC Plugin - executa o DRC do PDK automaticamente ao salvar o layout.

Ao detectar que o arquivo GDS/OAS foi salvo (via polling de mtime),
o plugin executa o script run_drc.py do PDK IHP SG13G2 diretamente
via subprocess, sem depender de actions Ruby do menu.
Ao terminar, carrega o relatório .lyrdb na view atual do KLayout.
"""

import glob
import os
import shutil
import subprocess
import traceback

import pya


# =================== CONFIG ===================

# icones do botao (gerados por PluginNat/icons/make_icons.py): laranja = off, verde = on
_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "icons")
_ICON_OFF = os.path.join(_ICON_DIR, "drc_off.png")
_ICON_ON = os.path.join(_ICON_DIR, "drc_on.png")

# Caminhos conhecidos onde o run_drc.py pode estar
_KNOWN_RUN_DRC_PATHS = [
    "/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py",
]

# Flags booleanas suportadas pelo run_drc.py
_DRC_BOOLEAN_FLAGS = [
    "no_feol",
    "no_beol",
    "disable_extra_rules",
    "no_density",
    "density_only",
    "density_sanity",
    "antenna",
    "antenna_only",
    "no_offgrid",
    "no_angle",
    "no_recommended",
]

# Opções padrão (mesmo esquema do macro Ruby sg13g2_drc.lym)
_DEFAULT_OPTIONS = {
    "top_cell": "",
    "run_mode": "deep",
    "table": "all",
    "run_dir": "",
    "parallel_runs": 1,
    "density_thr": 1,
    "no_feol": False,
    "no_beol": False,
    "disable_extra_rules": False,
    "no_density": True,
    "density_only": False,
    "density_sanity": False,
    "antenna": False,
    "antenna_only": False,
    "no_offgrid": False,
    "no_angle": False,
    "no_recommended": False,
}

# Intervalo de polling para detectar save (ms)
_SAVE_CHECK_INTERVAL_MS = 2000

# Intervalo de polling para monitorar o processo DRC (ms)
_DRC_MONITOR_INTERVAL_MS = 500


class LiveDRC:
    """Detecta save e executa o DRC do PDK automaticamente via subprocess."""

    def __init__(self):
        self.ativo = False
        self.last_modified_time = None
        self.last_filename = None
        self.main_window = None
        self.action = None

        # Processo DRC em execução
        self.drc_process = None
        self.drc_running = False
        self.current_run_dir = None

        # Caminho do run_drc.py (descoberto na ativação)
        self.run_drc_script = None

        # Timers
        self.save_timer = None
        self.monitor_timer = None

        self.setup_menu()
        print("[LiveDRC] Plugin started")

    def setup_menu(self):
        """Cria o botão na toolbar e inicializa os timers."""
        try:
            self.main_window = pya.Application.instance().main_window()
            if not self.main_window:
                print("[LiveDRC] Error: main window not found")
                return False

            self.action = pya.Action()
            self.action.title = "LiveDRC"
            self.action.icon = _ICON_OFF # comeca desligado (laranja)
            self.action.on_triggered(self.toggle_live_drc)

            menu = self.main_window.menu()
            menu.insert_item("@toolbar.end", "live_drc_action", self.action)

            # Timer para detectar saves (polling de mtime)
            self.save_timer = pya.QTimer(self.main_window)
            self.save_timer.timeout += self.check_changes

            # Timer para monitorar processo DRC
            self.monitor_timer = pya.QTimer(self.main_window)
            self.monitor_timer.timeout += self.monitor_drc_output

            print("[LiveDRC] Toolbar button created")
            return True

        except Exception as e:
            print(f"[LiveDRC] setup_menu error: {e}")
            traceback.print_exc()
            return False

    def toggle_live_drc(self):
        """Alterna entre ativo e inativo."""
        if not self.ativo:
            self.ativar()
        else:
            self.desativar()

    def janela_ativo(self):
        """Abre a janela de info onde o usuario confirma o caminho do drc e escolhe o modo de execução."""
        dlg = pya.QDialog(pya.Application.instance().main_window())
        dlg.setWindowTitle("LiveDRC")
        lay = pya.QVBoxLayout(dlg)

        lay.addWidget(pya.QLabel(
            "LiveDRC enabled.\n\n"
            "Save the layout to run DRC automatically.\n\n"
            f"Script: {self.run_drc_script}",
            dlg,
        ))

        # escolha do modo
        row = pya.QHBoxLayout()
        row.addWidget(pya.QLabel("DRC Mode:", dlg))
        deep = pya.QRadioButton("deep", dlg)
        flat = pya.QRadioButton("flat", dlg)
        deep.setChecked(True)  # padrão
        row.addWidget(deep)
        row.addWidget(flat)
        row.addStretch()
        lay.addLayout(row)

        ok = pya.QPushButton("OK", dlg)
        ok.clicked = lambda *a: dlg.accept()
        lay.addWidget(ok)

        dlg.exec_()
        return "deep" if deep.isChecked() else "flat"
        # valor do extra: extra.isChecked()


    def ativar(self):
        """Ativa o monitoramento de saves. Verifica se o run_drc.py existe."""
        try:
            # Descobrir o run_drc.py
            self.run_drc_script = self.find_run_drc_script()
            if not self.run_drc_script:
                pya.MessageBox.warning(
                    "LiveDRC",
                    "IHP SG13G2 PDK run_drc.py script not found.\n\n"
                    "Check that the PDK is installed and that PDKPATH\n"
                    "or KLAYOUT_PATH are set correctly.\n\n"
                    "Paths checked:\n"
                    "  - $PDKPATH/libs.tech/klayout/tech/drc/run_drc.py\n"
                    "  - $KLAYOUT_PATH/.../drc/run_drc.py\n"
                    "  - /foss/pdks/ihp-sg13g2/.../drc/run_drc.py",
                    pya.MessageBox.Ok,
                )
                return False

            self.ativo = True
            self.save_timer.start(_SAVE_CHECK_INTERVAL_MS)
            

            print(f"[LiveDRC] Enabled - using: {self.run_drc_script}")
            modo = self.janela_ativo()

            if modo == "deep":
                _DEFAULT_OPTIONS["run_mode"] = "deep"
            else:
                _DEFAULT_OPTIONS["run_mode"] = "flat"
            # pya.MessageBox.info(
            #     "LiveDRC",
            #     "LiveDRC ativo.\n\n"
            #     "Salva o layout para disparar o DRC automaticamente.\n\n"
            #     f"Script: {self.run_drc_script}",
            #     pya.MessageBox.Ok,
            # )

            if self.action:
                self.action.title = f"LiveDRC [ON][{_DEFAULT_OPTIONS['run_mode'][0]}]"
                self.action.icon = _ICON_ON #ligado = verde
            return True

        except Exception as e:
            print(f"[LiveDRC] Error enabling: {e}")
            self.ativo = False
            if self.action:
                self.action.icon = _ICON_OFF # falhou ao ligar, volta para laranja
            return False

    def desativar(self):
        """Desativa o monitoramento e mata qualquer DRC em execução."""
        try:
            self.ativo = False
            self.save_timer.stop()

            # Matar processo DRC se estiver rodando
            self._kill_drc_process()

            if self.action:
                self.action.title = "LiveDRC"
                self.action.icon = _ICON_OFF # desligado = laranja

            print("[LiveDRC] Disabled")
            pya.MessageBox.info("LiveDRC", "LiveDRC disabled.", pya.MessageBox.Ok)
            return True

        except Exception as e:
            print(f"[LiveDRC] Error disabling: {e}")
            return False

    # =================== DESCOBERTA DE CAMINHOS ===================

    def find_run_drc_script(self):
        """Localiza o run_drc.py do PDK IHP SG13G2.

        Estratégia de busca:
        1. Variável de ambiente PDKPATH
        2. KLAYOUT_PATH (pode ter múltiplos diretórios separados por :)
        3. Caminhos conhecidos (Docker IIC-OSIC-TOOLS, etc.)
        """
        candidates = []

        # Via PDKPATH
        pdkpath = os.environ.get("PDKPATH", "")
        if pdkpath:
            candidates.append(
                os.path.join(pdkpath, "libs.tech", "klayout", "tech", "drc", "run_drc.py")
            )

        # Via KLAYOUT_PATH (pode conter múltiplos caminhos)
        klayout_path = os.environ.get("KLAYOUT_PATH", "")
        if klayout_path:
            for p in klayout_path.split(":"):
                p = p.strip()
                if not p:
                    continue
                candidates.append(os.path.join(p, "drc", "run_drc.py"))
                candidates.append(os.path.join(p, "tech", "drc", "run_drc.py"))

        # Caminhos conhecidos
        candidates.extend(_KNOWN_RUN_DRC_PATHS)

        for c in candidates:
            if os.path.isfile(c):
                print(f"[LiveDRC] run_drc.py found: {c}")
                return c

        # Log dos caminhos tentados para debug
        print("[LiveDRC] run_drc.py NOT found. Paths checked:")
        for c in candidates:
            print(f"  - {c}")

        return None

    # =================== OPÇÕES DO DRC ===================

    def load_yaml_options(self):
        """Lê opções DRC do arquivo YAML do PDK.

        O YAML fica em ~/.ihp_pdk/ihp_sg13g2_drc_options.yml
        (mesmo local usado pelo macro Ruby sg13g2_drc_options.lym).
        Se o arquivo não existir ou yaml não estiver instalado,
        retorna os defaults.
        """
        options = dict(_DEFAULT_OPTIONS)

        yaml_path = os.path.join(
            os.path.expanduser("~"), ".ihp_pdk", "ihp_sg13g2_drc_options.yml"
        )

        if not os.path.exists(yaml_path):
            print(f"[LiveDRC] YAML not found: {yaml_path} (using defaults)")
            return options

        try:
            import yaml

            with open(yaml_path, "r") as f:
                user_opts = yaml.safe_load(f) or {}

            options.update(user_opts)
            print(f"[LiveDRC] Options loaded from {yaml_path}")

        except ImportError:
            print("[LiveDRC] PyYAML not installed - using defaults")
        except Exception as e:
            print(f"[LiveDRC] Error reading YAML: {e} - using defaults")

        return options

    # =================== DETECÇÃO DE SAVE ===================

    def check_changes(self):
        """Timer callback - detecta se o arquivo GDS foi salvo (via mtime)."""
        if not self.ativo:
            return

        try:
            mw = pya.Application.instance().main_window()
            if not mw:
                return

            view = mw.current_view()
            if not view:
                return

            cv = view.active_cellview()
            if not cv or not cv.is_valid():
                return

            filename = cv.filename()
            if not filename or not os.path.exists(filename):
                return

            mtime = os.path.getmtime(filename)

            if self.last_filename != filename or self.last_modified_time != mtime:
                if self.last_filename is not None:
                    print(f"[LiveDRC] Save detected: {os.path.basename(filename)}")
                    self.executar_drc()

                self.last_filename = filename
                self.last_modified_time = mtime

        except Exception as e:
            print(f"[LiveDRC] check_changes error: {e}")

    # =================== EXECUÇÃO DO DRC ===================

    def executar_drc(self):
        """Executa o DRC chamando run_drc.py diretamente via subprocess."""
        # Proteção contra execuções simultâneas
        if self.drc_running:
            print("[LiveDRC] DRC already running - ignoring new save")
            return False

        try:
            # Obter informações do layout atual
            mw = pya.Application.instance().main_window()
            view = mw.current_view()
            cv = view.active_cellview()
            filename = cv.filename()
            topcell = cv.cell_name

            if not filename:
                print("[LiveDRC] No file open")
                return False

            if not self.run_drc_script:
                print("[LiveDRC] run_drc.py not configured")
                return False

            # Carregar opções
            options = self.load_yaml_options()

            # Determinar topcell
            opt_topcell = options.get("top_cell", "")
            if opt_topcell and opt_topcell.strip():
                topcell = opt_topcell.strip()

            # Determinar run_dir
            opt_run_dir = options.get("run_dir", "")
            if opt_run_dir and opt_run_dir.strip():
                self.current_run_dir = os.path.expanduser(opt_run_dir.strip())
            else:
                self.current_run_dir = os.path.join(
                    os.path.dirname(filename), f"drc_run_{topcell}"
                )

            # Limpar run_dir anterior (mesmo comportamento do macro Ruby)
            if os.path.isdir(self.current_run_dir):
                try:
                    shutil.rmtree(self.current_run_dir)
                except Exception as e:
                    print(f"[LiveDRC] Warning: could not clean {self.current_run_dir}: {e}")

            # Construir o comando (mesmo formato do sg13g2_drc.lym)
            cmd = [
                "python3",
                self.run_drc_script,
                f"--path={filename}",
                f"--run_mode={_DEFAULT_OPTIONS['run_mode']}",
                f"--topcell={topcell}",
                f"--run_dir={self.current_run_dir}",
                f"--mp={options.get('parallel_runs', 1)}",
                f"--density_thr={options.get('density_thr', 1)}",
            ]

            # Adicionar flags booleanas
            for flag in _DRC_BOOLEAN_FLAGS:
                if options.get(flag, False):
                    cmd.append(f"--{flag}")

            # Adicionar tabela se especificada
            table = options.get("table", "all")
            if table and table != "all":
                cmd.append(f"--table={table}")

            print(f"[LiveDRC] Running DRC...")
            print(f"[LiveDRC] Command: {' '.join(cmd)}")

            # Feedback visual
            if self.action:
                self.action.title = "LiveDRC [RUNNING...]"

            # Executar em background.
            # IMPORTANTE: usar DEVNULL para stdout/stderr.
            # O run_drc.py grava tudo em arquivo de log no run_dir.
            # Se usarmos PIPE sem drenar continuamente, o buffer enche
            # e o processo filho trava esperando leitura (deadlock).
            self.drc_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.drc_running = True

            # Iniciar timer de monitoramento
            self.monitor_timer.start(_DRC_MONITOR_INTERVAL_MS)

            print(f"[LiveDRC] DRC started (PID={self.drc_process.pid})")
            return True

        except Exception as e:
            print(f"[LiveDRC] executar_drc error: {e}")
            traceback.print_exc()
            self.drc_running = False
            if self.action and self.ativo:
                self.action.title = f"LiveDRC [ON][{_DEFAULT_OPTIONS['run_mode'][0]}]"

            return False

    # =================== MONITORAMENTO DO DRC ===================

    def monitor_drc_output(self):
        """Timer callback - verifica se o processo DRC terminou.

        Nota: stdout/stderr são DEVNULL, então só checamos o retcode.
        Os logs ficam no arquivo de log dentro do run_dir.
        """
        if self.drc_process is None:
            self.monitor_timer.stop()
            self.drc_running = False
            return

        retcode = self.drc_process.poll()

        if retcode is not None:
            # DRC terminou - parar o timer
            self.monitor_timer.stop()

            # run_drc.py tem dois códigos de saída normais:
            #   0 = sem violações (layout passou no DRC)
            #   1 = violações encontradas (layout falhou no DRC)
            # Em ambos os casos o .lyrdb é gerado e deve ser carregado.
            # Outros códigos indicam erro fatal (ex: arquivo não encontrado).
            if retcode in (0, 1):
                if retcode == 0:
                    print("[LiveDRC] DRC finished: no violations ✅")
                else:
                    print("[LiveDRC] DRC finished: violations found ❌ (see markers)")
                self.load_drc_results()
            else:
                print(f"[LiveDRC] DRC failed with a fatal error (code={retcode})")
                log_path = self._find_log_file()
                if log_path:
                    print(f"[LiveDRC] See the log at: {log_path}")

            # Reset estado
            self.drc_process = None
            self.drc_running = False

            if self.action and self.ativo:
                self.action.title = f"LiveDRC [ON][{_DEFAULT_OPTIONS['run_mode'][0]}]"


    # =================== RESULTADOS DO DRC ===================

    def load_drc_results(self):
        """Carrega o arquivo .lyrdb gerado pelo DRC na view atual do KLayout."""
        if not self.current_run_dir:
            print("[LiveDRC] run_dir not set")
            return

        pattern = os.path.join(self.current_run_dir, "*.lyrdb")
        lyrdb_files = glob.glob(pattern)

        if not lyrdb_files:
            print(f"[LiveDRC] No .lyrdb result in: {self.current_run_dir}")
            return

        # Usar o primeiro arquivo encontrado (ou o _full se existir)
        full_files = [f for f in lyrdb_files if "_full.lyrdb" in f]
        result_file = full_files[0] if full_files else lyrdb_files[0]

        try:
            rdb = pya.ReportDatabase()
            rdb.load(result_file)

            mw = pya.Application.instance().main_window()
            if mw and mw.current_view():
                view = mw.current_view()
                rdb_index = view.add_rdb(rdb)
                cv_index = view.active_cellview_index
                view.show_rdb(rdb_index, cv_index)
                print(f"[LiveDRC] Results loaded: {os.path.basename(result_file)}")
            else:
                print("[LiveDRC] Warning: no active view to show results")

        except Exception as e:
            print(f"[LiveDRC] Error loading results: {e}")

    # =================== UTILITÁRIOS ===================

    def _kill_drc_process(self):
        """Mata o processo DRC se estiver rodando."""
        if self.drc_process is not None:
            try:
                self.drc_process.terminate()
                self.drc_process.wait(timeout=5)
                print(f"[LiveDRC] DRC process terminated")
            except subprocess.TimeoutExpired:
                self.drc_process.kill()
                print(f"[LiveDRC] DRC process forced to stop")
            except Exception as e:
                print(f"[LiveDRC] Error killing process: {e}")
            finally:
                self.drc_process = None
                self.drc_running = False
                self.monitor_timer.stop()

    def _find_log_file(self):
        """Encontra o arquivo de log gerado pelo run_drc.py no run_dir."""
        if not self.current_run_dir:
            return None
        log_files = glob.glob(os.path.join(self.current_run_dir, "*.log"))
        return log_files[0] if log_files else None

    def _reset_titulo(self):
        """Reseta o título do botão para o estado ativo."""
        if self.action and self.ativo:
            self.action.title = f"LiveDRC [ON][{_DEFAULT_OPTIONS['run_mode'][0]}]"



# =================== REGISTRO ===================
_live_drc_instance = None


def register_plugin():
    global _live_drc_instance
    try:
        if _live_drc_instance is None:
            _live_drc_instance = LiveDRC()
            print("[LiveDRC] Plugin registered")
    except Exception as e:
        print(f"[LiveDRC] Registration error: {e}")
        traceback.print_exc()


register_plugin()
