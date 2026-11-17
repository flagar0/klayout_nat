import glob
import inspect
import os
import subprocess
import sys
import traceback
from pathlib import Path

import pya

_HERE_STR = str(Path(__file__).resolve().parent)

if _HERE_STR in sys.path:
    sys.path.remove(_HERE_STR)
sys.path.insert(0, _HERE_STR)

# Flavio: o protobuf do klayout-pex importa "kpex.*" e precisa da propria pasta no sys.path.
# Usa a pasta do pacote instalado; um caminho fixo misturava versoes do klayout-pex
try:
    import klayout_pex_protobuf
    _PROTOBUF = os.path.dirname(os.path.realpath(klayout_pex_protobuf.__file__))
    if _PROTOBUF not in sys.path:
        sys.path.append(_PROTOBUF)
except ImportError:
    pass

    
# Flavio: usa o klayout-pex nativo do container (/usr/local/lib/python3.12/dist-packages/klayout_pex),
# testado com v0.3.12 e v0.9.0
# pex25d_builder/pex25d nao existem nessa versao -> pex_25d desativado
try:
    from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext, GDSPair
    from klayout_pex.tech_info import TechInfo
    from klayout_pex.magic.magic_runner import (
        run_magic, prepare_magic_script,
        MagicPEXMode, MagicShortMode, MagicMergeMode
    )
except Exception as e:
    err_msg = traceback.format_exc()
    pya.MessageBox.critical(
        "LivePEX",
        f"Error loading klayout-pex:\n\n{err_msg}\n\n",
        pya.MessageBox.Ok
    )
    print(err_msg)


_janela_instancia = None


def argumentos_aceitos(func, valores):
    """Ajusta os argumentos de nome para a assinatura de func na versao instalada.

    prepare_magic_script do klayout-pex muda entre versoes (a 0.3.12 tem
    tolerance, a 0.9.0 tem threshold/min_res/min_delay/unique_mode). Os valores que
    a versao instalada nao aceita sao descartados. Um parametro obrigatorio que
    nao esta em valores (de uma versao futura) recebe o DEFAULT do seu enum, se
    houver, ou None, que no klayout-pex significa "padrao do Magic".
    """
    aceitos = {}
    for nome, p in inspect.signature(func).parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if nome in valores:
            aceitos[nome] = valores[nome]
        elif p.default is p.empty:
            tipo = p.annotation
            aceitos[nome] = getattr(tipo, "DEFAULT", None) if isinstance(tipo, type) else None
            print(f"[LivePEX] {func.__name__}: new parameter '{nome}' set to {aceitos[nome]!r}")
    return aceitos


_KNOWN_RUN_LVS_PATHS = [
    "/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/lvs/run_lvs.py",
    "/foss/pdks/sky130A/libs.tech/klayout/lvs/run_lvs.py"
]

class PluginLivePex(pya.QDialog):

    def __init__(self, parent=None):
        super(PluginLivePex, self).__init__(parent)

        # VARIAVEIS
        self.run_lvs_script = None
        self.PDK = os.environ.get("PDK")
        self.PDK_ROOT = os.environ.get("PDK_ROOT")

        self.setWindowTitle("LivePEX Panel")
        self.resize(800, 600)
        
        layout = pya.QVBoxLayout(self)


        linha = pya.QHBoxLayout()

        self.label_resultado = pya.QLabel("Analysis results:", self)
        self.label_resultado.setWordWrap(True)
        linha.addWidget(self.label_resultado, 1)

        self.label_modo_pex = pya.QLabel("PEX mode:", self)
        linha.addWidget(self.label_modo_pex)

        self.combo_modo_pex = pya.QComboBox(self)
        for modo in ["CC", "RC", "R"]:
            self.combo_modo_pex.addItem(modo)
        self.combo_modo_pex.setCurrentIndex(0)  # CC é o padrão
        self.combo_modo_pex.setToolTip(
            "CC: capacitance | RC: capacitance + resistance | R: resistance"
        )
        linha.addWidget(self.combo_modo_pex)
        
        layout.addLayout(linha)

        self.saida_analise = pya.QPlainTextEdit()
        self.saida_analise.setReadOnly(True)
        layout.addWidget(self.saida_analise)

        self.label_info = pya.QLabel("Select the PEX engine:", self)
        layout.addWidget(self.label_info)
        
        # btn 2.5d
        # self.btn_25d = pya.QPushButton("2.5D", self)
        # layout.addWidget(self.btn_25d)

        # btn fastercap
        # self.btn_fastercap = pya.QPushButton("FasterCap", self)
        # layout.addWidget(self.btn_fastercap)
        
        # bnt magic
        self.btn_magic = pya.QPushButton("Magic", self)
        layout.addWidget(self.btn_magic)

        # TESTE - rodando  paenas para magic
        self.btn_magic.clicked.connect(self.pex_magic)
        # self.btn_25d.clicked.connect(self.pex_25d)


    def mostrar_resultado(self, path):
        """Mostra o conteúdo do .pex.spice em saida_analise e atualiza o label."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                self.saida_analise.setPlainText(f.read())
        except OSError as e:
            self.saida_analise.setPlainText(f"Error reading {path}:\n{e}")
        self.label_resultado.setText(f"Analysis results: {path}")

    def pex_magic(self):
        """Desativa o botao Magic enquanto roda o PEX e reativa em qualquer saida."""
        # Flavio: try/finally reativa o botao tambem nos return antecipados e em excecoes
        self.btn_magic.setEnabled(False)
        try:
            return self.executar_pex_magic()
        finally:
            self.btn_magic.setEnabled(True)

    def executar_pex_magic(self):
        """Roda PEX usando Magic: gera script TCL, executa magic, retorna caminho do .pex.spice."""
        layout_path, topcell = self.get_current_layout_info()
        if not layout_path or not topcell:
            return None

        # Caminhos de saída
        base_dir   = Path(layout_path).parent
        run_dir    = base_dir / f"pex_magic_{topcell}"
        run_dir.mkdir(parents=True, exist_ok=True)

        script_path  = str(run_dir / f"{topcell}_magic_script.tcl")
        log_path     = str(run_dir / f"{topcell}_magic_output.txt")
        netlist_path = str(run_dir / f"{topcell}.pex.spice")

        # Localiza magicrc via env (PDK_ROOT/PDK) ou pede ao usuário
        magicrc_path = self._find_magicrc()
        if not magicrc_path:
            pya.MessageBox.warning(
                "LivePEX",
                ".magicrc file not found.\n\n"
                "Set the environment variables:\n"
                "  PDK_ROOT=<path>\n"
                "  PDK=<pdk_name>  (e.g. ihp-sg13g2)\n\n"
                "Or set KPEX_MAGICRC=<path_to_.magicrc>",
                pya.MessageBox.Ok,
            )
            return None

        magic_exe = os.environ.get("KPEX_MAGIC_EXE", "magic")

        modo = self.combo_modo_pex.currentText
        print(modo)
        if modo == "CC":
            modo_pex = MagicPEXMode.CC
        elif modo == "RC":
            modo_pex = MagicPEXMode.RC
        elif modo == "R":
            modo_pex = MagicPEXMode.R

        # Gera script TCL (importado do klayout-pex)
        # Flavio: valores das duas versoes; argumentos_aceitos passa so os que a instalada aceita
        valores_magic = dict(
            gds_path=layout_path,
            cell_name=topcell,
            run_dir_path=str(run_dir),
            script_path=script_path,
            output_netlist_path=netlist_path,
            pex_mode=modo_pex,          # CC = capacitância (padrão)
            c_threshold=0.0,
            r_threshold=0.0,
            tolerance=1.0,              # klayout-pex 0.3.12
            threshold=None,             # klayout-pex 0.9.0 (None = padrao do Magic)
            min_res=None,
            min_delay=None,
            halo=None,
            short_mode=MagicShortMode.NONE,
            merge_mode=MagicMergeMode.NONE,
        )
        prepare_magic_script(**argumentos_aceitos(prepare_magic_script, valores_magic))

        self.label_info.setText("Running Magic PEX...")
        pya.Application.instance().process_events()

        try:
            run_magic(
                exe_path=magic_exe,
                magicrc_path=magicrc_path,
                script_path=script_path,
                log_path=log_path,
            )
        except Exception as e:
            pya.MessageBox.critical("LivePEX", f"Magic failed:\n{e}", pya.MessageBox.Ok)
            self.label_info.setText("Magic PEX error.")
            return None

        self.label_info.setText("Magic PEX finished!")
        self.mostrar_resultado(netlist_path)
        pya.MessageBox.info(
            "LivePEX",
            f"PEX netlist generated at:\n{netlist_path}",
            pya.MessageBox.Ok,
        )
        return netlist_path


    def _find_magicrc(self):
        """Localiza o .magicrc: env KPEX_MAGICRC > PDK_ROOT/PDK > caminhos conhecidos."""
        # 1. Variável direta
        direct = os.environ.get("KPEX_MAGICRC")
        if direct and os.path.isfile(direct):
            return direct

        # 2. PDK_ROOT + PDK
        if self.PDK_ROOT and self.PDK:
            candidate = os.path.join(self.PDK_ROOT, self.PDK, "libs.tech", "magic", f"{self.PDK}.magicrc")
            if os.path.isfile(candidate):
                return candidate

        # 3. Caminhos conhecidos (Docker IIC-OSIC-TOOLS / IHP)
        known = [
            "/foss/pdks/ihp-sg13g2/libs.tech/magic/ihp-sg13g2.magicrc",
            "/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
        ]
        for p in known:
            if os.path.isfile(p):
                return p

        return None


    def pex_25d(self):
        """Roda PEX 2.5D usando klayout-pex: gera .pex25d a partir do .lvsdb do PDK."""
        
        # logica para rodar o PEX 25d
        # Flavio: run_lvs retorna None quando falha (PEP 8: return consistente)
        lvs_result = self.run_lvs()
        if lvs_result is None:
            return None
        lvsdb_path, layout_path, topcell_name = lvs_result

        tech_pb_json = self._find_tech_pb_json()
        if not tech_pb_json:
            pya.MessageBox.warning(
                "LivePEX",
                "PDK tech.pb.json file not found.\n\n"
                "Set the PDK_ROOT and PDK environment variables.\n"
                "Expected path: /usr/local/lib/python3.12/dist-packages/klayout_pex_protobuf/\n\n"
                "Or install klayout-pex with the PDK configured.",
                pya.MessageBox.Ok
            )
            return None

        # Prepara diretório de saída
        base_dir = Path(lvsdb_path).parent.parent
        run_dir  = base_dir / f"pex_25d_{topcell_name}"
        run_dir.mkdir(parents=True, exist_ok=True)
        pex25d_out = str(run_dir / f"{topcell_name}.pex25d")

        # Carrega o LVSDB
        self.label_info.setText("Loading LVSDB...")
        pya.Application.instance().process_events()
        lvsdb = pya.LayoutVsSchematic()
        lvsdb.read(lvsdb_path)

        # Carrega TechInfo
        self.label_info.setText("Loading PDK TechInfo...")
        pya.Application.instance().process_events()
        try:
            tech_info = TechInfo.from_json(tech_pb_json, dielectric_filter=None)
        except Exception as e:
            pya.MessageBox.critical("LivePEX", f"Error loading TechInfo:\n{e}", pya.MessageBox.Ok)
            return None

        # Prepara contexto de extração (KLayoutExtractionContext)
        self.label_info.setText("Preparing 2.5D extraction context...")
        pya.Application.instance().process_events()
        try:
            pex_context = KLayoutExtractionContext.prepare_extraction(
                lvsdb=lvsdb,
                top_cell=topcell_name,
                tech=tech_info,
                blackbox_devices=True,   # ignora geometria interna de dispositivos
            )
        except Exception as e:
            pya.MessageBox.critical("LivePEX", f"Error preparing extraction:\n{e}", pya.MessageBox.Ok)
            return None

        # Gera o PEX25DFile
        self.label_info.setText("Generating PEX25D file...")
        pya.Application.instance().process_events()
        try:
            pex25d_file = build_pex25d_file(
                pex_context=pex_context,
                tech_info=tech_info,
                cell_name=topcell_name,
                options=BuilderOptions(
                    grid_um='0.0001',          # grade padrão (0.1 nm)
                    include_resistance=True,
                    domain_margin_um=None,     # sem domínio explícito
                )
            )
        except Exception as e:
            pya.MessageBox.critical("LivePEX", f"Error generating PEX25D:\n{e}", pya.MessageBox.Ok)
            self.label_info.setText("PEX 2.5D error.")
            return None

        # Salva o .pex25d
        try:
            spec = infer_artifact_spec(pex25d_out,
                                    kind=ArtifactKind.FILE,
                                    format=ArtifactFormat.TEXT)
            save_artifact(pex25d_file, spec)
        except Exception as e:
            pya.MessageBox.critical("LivePEX", f"Error saving .pex25d:\n{e}", pya.MessageBox.Ok)
            self.label_info.setText("Error saving PEX25D.")
            return None
        self.label_info.setText("PEX 2.5D finished!")
        pya.MessageBox.info(
            "LivePEX",
            f"PEX25D file generated at:\n{pex25d_out}",
            pya.MessageBox.Ok
        )
        return pex25d_out


    def _find_tech_pb_json(self):
        """Localiza o pdk_tech.pb.json: env PDK_ROOT/PDK"""
        # PDK_ROOT + PDK
        if self.PDK_ROOT and self.PDK:
            candidate = os.path.join(self.PDK_ROOT, self.PDK, "libs.tech", "klayout_pex_protobuf", f"{self.PDK}_tech.pb.json")
            if os.path.isfile(candidate):
                return candidate
                
        known = [
            "/usr/local/lib/python3.12/dist-packages/klayout_pex_protobuf/ihp-sg13g2_tech.pb.json",
            "/usr/local/lib/python3.12/dist-packages/klayout_pex_protobuf/sky130A_tech.pb.json",
            "/usr/local/lib/python3.12/dist-packages/klayout_pex_protobuf/gf180mcuD_tech.pb.json"
        ]
        for p in known:
            if os.path.isfile(p):
                return p
        return None

    # =================== MAPEAMENTO DE CAMADAS ===================
    def map_internal_layers(self, internal_layout):
        """Mapeia os layer_indexes internos para nomes legiveis."""
        conductors = {}  # {nome_camada: layer_index}
        vias = {}        # {nome_camada: layer_index}

        # Palavras-chave para diferenciar condutores de furos de via/contato
        via_keywords = ["via", "cont", "contact"]

        for layer_idx in internal_layout.layer_indexes():
            info = internal_layout.get_info(layer_idx)
            name = info.name.lower() if info.name else f"layer_{info.layer}_{info.datatype}"

            # Ignora marcadores, camadas de texto ou pinos
            if any(ignore in name for ignore in ["_pin", "_text", "_mask", "_filler", "_slit"]):
                continue

            if any(vk in name for vk in via_keywords):
                vias[name] = layer_idx
            else:
                conductors[name] = layer_idx

        return conductors, vias

    # =================== EXTRAÇÃO DE POLÍGONOS ===================
    # USADO PARA O MOTOR 2.5 E FASTERCAP
    def extract_net_conductors(self, l2n, circuit, conductors_map, dbu):
        """Extrai os poligonos de cada net em microns para cada camada condutora."""
        nets_data = {}

        for net in circuit.each_net():
            net_name = net.name
            nets_data[net_name] = {}

            for layer_name, layer_idx in conductors_map.items():
                # Obtem a regiao geometrica associada ao no e camada
                region = l2n.shapes_of_net(net, layer_idx)

                if region.is_empty():
                    continue

                # Merge para unificar retangulos/poligonos sobrepostos
                region.merge()

                # Converte as coordenadas inteiras de DBU para microns
                polygons_um = []
                for poly in region.each():
                    points = [(pt.x * dbu, pt.y * dbu) for pt in poly.each_point_hull()]
                    polygons_um.append(points)

                if polygons_um:
                    nets_data[net_name][layer_name] = {
                        "polygons": polygons_um,
                        "bbox": (
                            region.bbox().left * dbu,
                            region.bbox().bottom * dbu,
                            region.bbox().right * dbu,
                            region.bbox().top * dbu
                        )
                    }

        return nets_data

    # =================== EXTRAÇÃO DE VIAS ===================
    def extract_net_vias(self, l2n, circuit, vias_map, dbu):
        """Extrai a posicao e coordenadas de cada via associada as redes."""
        vias_data = {}

        for net in circuit.each_net():
            net_name = net.name
            vias_data[net_name] = {}

            for via_name, via_idx in vias_map.items():
                region = l2n.shapes_of_net(net, via_idx)

                if region.is_empty():
                    continue

                cut_boxes_um = []
                for box in region.each():
                    bbox = box.bbox()
                    cut_boxes_um.append({
                        "center": (bbox.center().x * dbu, bbox.center().y * dbu),
                        "box": (bbox.left * dbu, bbox.bottom * dbu, bbox.right * dbu, bbox.top * dbu),
                        "area_um2": (bbox.area()) * (dbu ** 2)
                    })

                if cut_boxes_um:
                    vias_data[net_name][via_name] = cut_boxes_um

        return vias_data

    # =================== EXTRAÇÃO DE DISPOSITIVOS E TERMINAIS ===================
    def extract_devices_and_pins(self, circuit, dbu):
        """Mapeia cada dispositivo extraido, seus terminais e posicoes fisicas."""
        devices_data = []

        for device in circuit.each_device():
            dev_class = device.device_class()
            dev_info = {
                "name": device.name,
                "class_name": dev_class.name,
                "terminals": {}
            }

            # Itera sobre os terminais do componente (ex: D, G, S, B em MOS)
            for term_def in dev_class.terminal_definitions():
                term_id = term_def.id()
                term_name = term_def.name()
                net = device.terminal_net(term_id)

                net_name = net.name if net else "OPEN"

                # Le a posicao/caixa delimitadora do terminal no espaco fisico
                term_geom = device.terminal_geometry(term_id)
                bbox = term_geom.bbox() if not term_geom.is_empty() else None

                dev_info["terminals"][term_name] = {
                    "net": net_name,
                    "center": (bbox.center().x * dbu, bbox.center().y * dbu) if bbox else None,
                    "bbox": (
                        bbox.left * dbu, bbox.bottom * dbu,
                        bbox.right * dbu, bbox.top * dbu
                    ) if bbox else None
                }

            devices_data.append(dev_info)

        return devices_data


    def run_lvs(self):
        # logica para rodar o LVS, etapa inicial do PEX 

        # do PDK IPH:
        # run_lvs.py [--layout=<layout_path>]
        #    [--netlist=<netlist_path>] [--layout_netlist=<layout_netlist_path>] [--run_dir=<run_dir_path>]
        #    [--topcell=<topcell_name>] [--run_mode=<run_mode>]
        #    [--no_net_names] [--spice_comments] [--net_only] [--no_simplify]
        #    [--no_series_res] [--no_parallel_res] [--combine_devices] [--top_lvl_pins]
        #    [--purge] [--purge_nets] [--ignore_top_ports_mismatch]
        #    [--implicit_nets=<nets>]
        # Descobrir o run_lvs.py

        self.run_lvs_script = self.find_run_lvs_script()
        if not self.run_lvs_script:
            pya.MessageBox.warning(
                "LivePEX",
                "IHP SG13G2 PDK run_lvs.py script not found.\n\n"
                "Check that the PDK is installed and that PDKPATH\n"
                "or KLAYOUT_PATH are set correctly.\n\n"
                "Paths checked:\n"
                "  - $PDKPATH/libs.tech/klayout/tech/lvs/run_lvs.py\n"
                "  - $KLAYOUT_PATH/.../lvs/run_lvs.py\n"
                "  - /foss/pdks/ihp-sg13g2/.../lvs/run_lvs.py",
                pya.MessageBox.Ok,
            )
            return None

        layout_path, topcell = self.get_current_layout_info()
        if not layout_path or not topcell:
            return None
        
        base_dir = Path(layout_path).parent
        # Diretorio para o Passo 1 (apenas extracao do .cir)
        dir_p1 = base_dir / f"lvs_{topcell}_pass1_extract"
        # Diretorio para o Passo 2 (onde ficara o .lvsdb final)
        dir_p2 = base_dir / f"lvs_{topcell}_pass2_lvsdb"
        python_bin = "python3"

        # Feedback visual inicial
        # Flavio: o botao 2.5D esta comentado no __init__; sem ele isso dava AttributeError
        if hasattr(self, "btn_25d"):
            self.btn_25d.setEnabled(False)
        self.label_info.setText("Running step 1: extracting netlist...")
        pya.Application.instance().process_events() # Forca a interface a redesenhar

        try:
            # Executar Passo 1
            extracted_cir = self.execute_pass1_extract(
                python_bin, self.run_lvs_script, layout_path, topcell, dir_p1
            )
            if not extracted_cir:
                pya.MessageBox.critical("LivePEX", "Netlist extraction failed (step 1).", pya.MessageBox.Ok)
                return None

            # Feedback visual intermediario
            self.label_info.setText("Running step 2: generating LVSDB...")
            pya.Application.instance().process_events()

            # Executar Passo 2
            lvsdb_path = self.execute_pass2_lvsdb(
                python_bin, self.run_lvs_script, layout_path, topcell, extracted_cir, dir_p2
            )
            if not lvsdb_path:
                pya.MessageBox.critical("LivePEX", "Failed to create the .lvsdb (step 2).", pya.MessageBox.Ok)
                return None

            # Conclusao com sucesso
            self.label_info.setText("LVSDB generated successfully!")
            pya.MessageBox.info(
                "LivePEX",
                f".lvsdb file generated successfully for PEX:\n{lvsdb_path}",
                pya.MessageBox.Ok
            )

        except Exception as e:
            pya.MessageBox.critical("LivePEX", f"Error in step 1:\n{e}", pya.MessageBox.Ok)
            print(traceback.format_exc())
            return None
        finally:
            if hasattr(self, "btn_25d"):
                self.btn_25d.setEnabled(True)
        # Flavio: return saiu do finally; la dentro ele anulava os return None e as excecoes (PEP 8)
        return lvsdb_path, layout_path, topcell  # passo o layout_path e o topcell para não precisar rodar denovo

    # =================== DESCOBERTA DE CAMINHOS ===================

    def find_run_lvs_script(self):
        """Localiza o run_lvs.py dos PDKS.

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
                os.path.join(pdkpath, "libs.tech", "klayout", "tech", "lvs", "run_lvs.py")
            )

        # Via KLAYOUT_PATH (pode conter múltiplos caminhos)
        klayout_path = os.environ.get("KLAYOUT_PATH", "")
        if klayout_path:
            for p in klayout_path.split(":"):
                p = p.strip()
                if not p:
                    continue
                candidates.append(os.path.join(p, "lvs", "run_lvs.py"))
                candidates.append(os.path.join(p, "tech", "lvs", "run_lvs.py"))

        # Caminhos conhecidos
        candidates.extend(_KNOWN_RUN_LVS_PATHS)

        # sky130A: hash de versão variável, precisa de glob
        if self.PDK == "sky130A":
            matches = glob.glob("/foss/pdks/ciel/sky130/versions/*/sky130A/libs.tech/klayout/lvs/run_lvs.py")
            if matches:
                print(f"[LivePEX] run_lvs.py found via glob: {matches[0]}")
                return matches[0]
                
        for c in candidates:
            if os.path.isfile(c):
                print(f"[LivePEX] run_lvs.py found: {c}")
                return c

        print("[LivePEX] run_lvs.py NOT found. Paths checked:")
        for c in candidates:
            print(f"  - {c}")

        return None


    # =================== DESCOBERTA DO LAYOUT ===================
    def get_current_layout_info(self):
        """Obtém o caminho do layout e o nome da célula ativa no KLayout."""

        mw = pya.Application.instance().main_window()
        view = mw.current_view() if mw else None
        if not view:
            pya.MessageBox.warning("LivePEX", "No active layout view found.", pya.MessageBox.Ok)
            return None, None

        cv = view.active_cellview()
        if not cv or not cv.is_valid():
            pya.MessageBox.warning("LivePEX", "Invalid active cell.", pya.MessageBox.Ok)
            return None, None

        layout_path = cv.filename()
        if not layout_path or not os.path.isfile(layout_path):
            pya.MessageBox.warning(
                "LivePEX",
                "The current layout has not been saved to disk yet.\n"
                "Save the file (.gds or .oas) before running LVS.",
                pya.MessageBox.Ok
            )
            return None, None

        topcell_name = cv.cell_name
        return layout_path, topcell_name



    def execute_pass1_extract(self, python_bin, run_lvs_script, layout_path, topcell, run_dir_1):
        """Executa o Passo 1 do LVS. Detecta o PDK pelo caminho do script e monta os args corretos."""
        os.makedirs(run_dir_1, exist_ok=True)

        if self.PDK == "sky130A":
            # sky130A: --design / --net ; sem --topcell nem --run_dir
            # Passo 1 = extracao sem netlist de referencia (gera o extracted)
            extracted_cir = os.path.join(run_dir_1, f"{topcell}_extracted.cir")
            cmd_pass1 = [
                python_bin, "-u", run_lvs_script,
                f"--design={layout_path}",
                f"--net={extracted_cir}",   # netlist de saida
                "--run_mode=flat",
                "--set_scale",
            ]
        else:
            # IHP SG13G2
            cmd_pass1 = [
                python_bin, "-u", run_lvs_script,
                f"--layout={layout_path}",
                f"--topcell={topcell}",
                "--run_mode=flat",
                f"--run_dir={run_dir_1}"
            ]

        print(f"[LivePEX] Running step 1 (extraction): {' '.join(cmd_pass1)}")
        result = subprocess.run(cmd_pass1, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        if result.returncode != 0:
            print(f"[LivePEX] Error in step 1:\n{result.stdout}")
            return None

        cir_candidates = glob.glob(os.path.join(run_dir_1, "*_extracted.cir"))
        if not cir_candidates:
            print("[LivePEX] Error: *_extracted.cir file not found after step 1.")
            return None

        extracted_cir = cir_candidates[0]
        print(f"[LivePEX] Extracted netlist generated at: {extracted_cir}")
        return extracted_cir

    def execute_pass2_lvsdb(self, python_bin, run_lvs_script, layout_path, topcell, extracted_cir, run_dir_2):
        """Executa o Passo 2 do LVS. Detecta o PDK pelo caminho do script e monta os args corretos."""
        os.makedirs(run_dir_2, exist_ok=True)

        if self.PDK == "sky130A":
            # sky130A: --design / --net
            cmd_pass2 = [
                python_bin, "-u", run_lvs_script,
                f"--design={layout_path}",
                f"--net={extracted_cir}",
                "--run_mode=flat",
                "--set_scale",
            ]
        else:
            # IHP SG13G2
            cmd_pass2 = [
                python_bin, "-u", run_lvs_script,
                f"--layout={layout_path}",
                f"--netlist={extracted_cir}",
                f"--topcell={topcell}",
                "--run_mode=flat",
                "--ignore_top_ports_mismatch",
                f"--run_dir={run_dir_2}"
            ]

        print(f"[LivePEX] Running step 2 (LVSDB generation): {' '.join(cmd_pass2)}")
        result = subprocess.run(cmd_pass2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        lvsdb_candidates = glob.glob(os.path.join(run_dir_2, "*.lvsdb"))
        if not lvsdb_candidates:
            print(f"[LivePEX] Could not find the .lvsdb generated in step 2:\n{result.stdout}")
            return None

        lvsdb_path = lvsdb_candidates[0]
        print(f"[LivePEX] Success! Database generated at: {lvsdb_path}")
        return lvsdb_path


def abrir_ou_focar_janela():
    """Garante que apenas uma instância da janela exista aberta."""
    global _janela_instancia
    mw = pya.Application.instance().main_window()

    if _janela_instancia is None:
        _janela_instancia = PluginLivePex(mw)
    
    _janela_instancia.show()
    _janela_instancia.raise_()
    _janela_instancia.activateWindow()

def plugin_pex():
    app = pya.Application.instance()
    mw = app.main_window()
    menu = mw.menu()

    _path = Path(__file__).parent.parent
    nat = str(_path/"icons"/"pex.png")
    # nat = str(_path/"natt.jpg")

    # Criação da ação da toolbar
    acao = pya.Action()
    acao.title = "LivePEX"
    acao.tool_tip = "Run PEX"
    acao.icon = nat
    acao.on_triggered = abrir_ou_focar_janela

    # Adiciona à toolbar principal
    menu.insert_item("@toolbar.end", "live_pex", acao)

# Executa o registro ao carregar a macro
plugin_pex()