# Copyright 2024 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Original file changed by IHP PDK Authors 2025
# Adopting the Skywater PDK import_netlist.py file to IHP SG13G2 technology


import os
import re
import sys

import pya

from ihp130_pcell_templates import templates # Flavio: import absoluto, pymacros nao e um pacote


SI_MULTIPLIERS = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "µ": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}

# Flavio: opções de pino de entrada, saida, e bidircional
PIN_DIRECTIVES = ('*.iopin', '*.ipin', '*.opin')

# Flavio: chaves das propriedades gravadas nas cascas e pinos. Tem que ser numeros:
# o GDS descarta propriedades com chave de texto ao salvar (o OASIS guarda as duas).
# Os mesmos numeros sao lidos pelo PluginNat/pymacros/ratsnest.py
PROP_NAME = 1
PROP_NETS = 2
PROP_DIRECTION = 3

def parse_si_value(value):
    if not isinstance(value, str):
        return value

    cleaned = value.strip()
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Zµ]+)?", cleaned)
    if not match:
        return value

    number = float(match.group(1))
    suffix = match.group(2)
    if not suffix:
        return number

    suffix = suffix.lower()
    if suffix in SI_MULTIPLIERS:
        return number * SI_MULTIPLIERS[suffix]

    if suffix.endswith("m") and len(suffix) == 2:
        prefix = suffix[0]
        if prefix in SI_MULTIPLIERS:
            return number * SI_MULTIPLIERS[prefix]

    return value


def normalize_params(params):
    normalized = {}
    for key, value in params.items():
        normalized[key] = parse_si_value(value)
    return normalized



def create_pcell_instance(name_spice=None, pcell_name='CIRCLE', lib_name='Basic', params={},
                          pos=pya.Trans.R0, nets=None):
    """
    Create a new instance of a PCell
    and return its width and height
    """

    print(f"Creating PCell '{pcell_name}' with parameters:")
    print(f"Spice name: {name_spice}")
    for key, value in params.items():
        print(f' - {key}: {value}')

    # Get PCell Library
    # Flavio: correção -> lib = pya.Library.library_by_name(lib_name)
    lib = pya.Library.library_by_name(lib_name, 'sg13g2') # Flavio: fixar a biblbliopteca do ihp para
    # previnir erros de importacao


    if not lib:
        print(f'Error: Library not found {lib_name}')
        return (0, 0)

    # The PCell Declaration. This one will create PCell variants.
    pcell_decl = lib.layout().pcell_declaration(pcell_name)

    if not pcell_decl:
        print(f'Error: Pcell not found {pcell_name}')
        return (0, 0)

    # Get the active layout
    cellview = pya.CellView().active()
    layout = cellview.layout()
    if layout is None:
        print(f'Error: Couldn\'t get active layout.')
        return (0, 0)  # Flavio: o chamador desempacota (width, height)

    # Get the top cell. Assuming only one top cell exists
    top_cell = layout.top_cell()

    # Add a PCell variant
    pcell_var = layout.add_pcell_variant(lib, pcell_decl.id(), params)
    
    bbox = layout.cell(pcell_var).bbox()
    
    # Add an offset to the position to account for the origin
    offset = pya.Trans(pos, x=-bbox.left, y=-bbox.bottom)

    width = bbox.width()
    height = bbox.height()
    
    # Insert instance
    if name_spice:
        # Flavio: celula casca com o nome do SPICE, contendo o PCell. Assim o painel Cells
        # mostra o nome do SPICE e o PCell continua editavel (descendo um nivel)
        casca = layout.create_cell(name_spice)
        casca.insert(pya.CellInstArray(pcell_var, pya.Trans(-bbox.left, -bbox.bottom)))
        # FLavio: bbox.left e bbox.bottom para que o PCell fique na origem da celula casca
        instancia = top_cell.insert(pya.CellInstArray(casca.cell_index(), pos))
        instancia.set_property(PROP_NAME, name_spice) # Flavio: coloca o nome do componente gerado
        # igual o nome do SPICE
        if nets:
            instancia.set_property(PROP_NETS, " ".join(nets)) # Flavio: nets dos terminais, na ordem do SPICE,
            # lidas pelo ratsnest (PluginNat/pymacros/ratsnest.py)
    else:
        top_cell.insert(pya.CellInstArray(pcell_var, offset))
    return (width, height)

current_x = 0
spacing = 100

def create_subckt_instance(name, subckt_definitions):
    global current_x
    global spacing

    for pcell_inst in subckt_definitions[name]['pcells']:
        (width, height) = create_pcell_instance(
            pcell_inst['name_spice'],  # Flavio: passando o nome do componente que consta no SPICE
            pcell_inst['pcell_name'],
            pcell_inst['pcell_library'],
            pcell_inst['params'],
            pya.Trans(current_x, 0),
            pcell_inst.get('nets')  # Flavio: nets do componente, para o ratsnest
        )
        current_x += width + spacing

    for subckt_inst in subckt_definitions[name]['subckts']:
        if subckt_inst not in subckt_definitions:
            print(f'Error: Unknown subckt {subckt_inst}')
        else:
            create_subckt_instance(subckt_inst, subckt_definitions)

# Flavio: camadas do Metal1 no SG13G2 (sg13g2.lyp); o LVS le os labels de 8/25
METAL1_DRAWING = pya.LayerInfo(8, 0)
METAL1_PIN = pya.LayerInfo(8, 2)
METAL1_TEXT = pya.LayerInfo(8, 25)
PIN_SIZE_UM = 1.0
PIN_SPACING_UM = 4.0
PIN_ROW_Y_UM = -10.0 # Flavio: fila de pinos abaixo da fila de dispositivos

def create_pin_instance(name, direction, x):
    """
    Flavio: cria uma celula casca PIN_<nome> com um quadrado de Metal1
    (drawing + pin) e o label do pino, e a insere na top cell.
    Retorna quanto avancar em x (em dbu) para o proximo pino.
    """
    layout = pya.CellView().active().layout()
    top_cell = layout.top_cell()


    x0 = x
    y0 = int(round(PIN_ROW_Y_UM / layout.dbu))
    size = int(round(PIN_SIZE_UM / layout.dbu))
    box = pya.Box(x0, y0, x0 + size, y0 + size)

    top_cell.shapes(layout.layer(METAL1_DRAWING)).insert(box)
    pin_shape = top_cell.shapes(layout.layer(METAL1_PIN)).insert(box)
    top_cell.shapes(layout.layer(METAL1_TEXT)).insert(pya.Text(name, pya.Trans(box.center().x, box.center().y)))

    pin_shape.set_property(PROP_NAME, name)
    pin_shape.set_property(PROP_DIRECTION, direction)

    # Flavio: pino em casca abaixo
    # size = int(round(PIN_SIZE_UM / layout.dbu))
    # box = pya.Box(0, 0, size, size)

    # pin_cell = layout.create_cell(f'PIN_{name}')
    # pin_cell.shapes(layout.layer(METAL1_DRAWING)).insert(box)
    # pin_cell.shapes(layout.layer(METAL1_PIN)).insert(box)
    # pin_cell.shapes(layout.layer(METAL1_TEXT)).insert(pya.Text(name, pya.Trans(box.center().x, box.center().y)))

    # y = int(round(PIN_ROW_Y_UM / layout.dbu))
    # instancia = top_cell.insert(pya.CellInstArray(pin_cell.cell_index(), pya.Trans(x, y)))
    # instancia.set_property('name', name)
    # instancia.set_property('direction', direction)

    print(f'Creating pin {name} ({direction})')
    return size + int(round(PIN_SPACING_UM / layout.dbu))

def ihp130_import_netlist(netlist_path=None):

    # Get the schematic netlist
    # Flavio: o caminho pode vir da janela do plugin; sem ele, abre o dialogo como antes
    if netlist_path is None:
        netlist_path = pya.FileDialog.ask_open_file_name("Choose the schematic netlist", '.', "SPICE (*.spice)")

    print(f'Info: The netlist importer is still experimental.')
    
    # Check whether file exists
    if not netlist_path or not os.path.isfile(netlist_path):
        print(f'Error: {netlist_path} is not a file!')
        return # Flavio: era sys.exit(0); dentro de um botao isso tentaria encerrar o Python do KLayout

    subckt_definitions = ler_netlist(netlist_path) # Flavio: leitura separada para o Update netlist reusar
    instanciar(subckt_definitions)


def ler_netlist(netlist_path):
    """Flavio: le o netlist e devolve subckt_definitions, sem criar nada no layout."""
    print(f'Reading Spice netlist: {netlist_path}')

    # Parse the spice netlist
    with open(netlist_path, 'r') as netlist_file:
        netlist_content = netlist_file.read()

    # Continue lines starting with '+'
    netlist_content = netlist_content.replace('\n+', '')
    
    # Split lines
    netlist_lines = netlist_content.split('\n')

    # Subckt data
    subckt_definitions = {'root': {'subckts': [], 'pcells': [], 'pins': [], 'references': 0}}
    # Flavio: alteração para guardar os pinos do subckt 
    active_subckt = 'root' # Flavio: faz o código nao precisar de um subckt no comeco, podendo
    # colocar só os componentes

    # Parameter data
    global_parameters = {}

    # Handle ".include" statements
    found = True
    while found:
        found = False
        for i, line in enumerate(netlist_lines):

            # Ignore comments
            if line.startswith('*'):
                continue

            # Find start of include statement
            if line.startswith('.include') or line.startswith('.INCLUDE'):
                found = True
                include_path = line.split(' ')[1]
                
                # Relative path
                if not os.path.isabs(include_path):
                    include_path = os.path.join(os.path.dirname(netlist_path), include_path)

                # Get the content
                with open(include_path, 'r') as include_file:
                    include_content = include_file.read()
                
                # Continue lines starting with '+'
                include_content = include_content.replace('\n+', '')
                
                # Split lines
                include_lines = include_content.split('\n')

                # Replace ".include" with the lines
                netlist_lines[i:i+1] = include_lines
                
                break

    # Scan for parameters
    for line in netlist_lines:
        # Ignore comments
        if line.startswith('*'):
            continue

        # Find start of subckt definitions
        if line.startswith('.param') or line.startswith('.PARAM'):
            parameter = line.split(' ')[1]
            name, value = parameter.split('=')
            global_parameters[name] = value
    
    # Apply parameters
    for i, line in enumerate(netlist_lines):
        # Ignore comments
        if line.startswith('*'):
            continue

        # Find start of subckt definitions
        def replace_parameters(matchobj):
            if matchobj.group(1) in global_parameters:
                return global_parameters[matchobj.group(1)]
            print(f'Error: Unknown parameter "{matchobj.group(1)}"')
            return matchobj.group(1)

        netlist_lines[i] = re.sub(r'{(.*?)}', replace_parameters, line)

    # Scan for subckts
    for line in netlist_lines:

        # Flavio: guarda as infos dos pinos de entrada e saida 
        if line.lower().startswith(PIN_DIRECTIVES):
            direction, pin = line.split()[:2]
            pins = subckt_definitions[active_subckt]['pins']
            if pin not in [p['name'] for p in pins]: # Flavio: o xschem pode repetir pinos ex: GND
                pins.append({'name': pin, 'direction': direction.lower().lstrip('*.')})
            continue

        # Ignore comments
        if line.startswith('*'):
            continue

        # Find start of subckt definitions
        if line.startswith('.subckt') or line.startswith('.SUBCKT'):
            active_subckt = line.split(' ')[1]
            subckt_definitions[active_subckt] = {'subckts': [], 'pcells': [], 'pins': [], 'references': 0}
            # Flavio: alteração para guardar os pinos do subckt 

    for line in netlist_lines:
        # Ignore comments
        if line.startswith('*'):
            continue

        # Find start of subckt definitions
        if line.startswith('.subckt') or line.startswith('.SUBCKT'):
            active_subckt = line.split(' ')[1]
            
            if active_subckt not in subckt_definitions:
                print(f'Error: Unknown subckt "{active_subckt}"')  # Flavio: subckt nao existe aqui (NameError)

        # Find end of subckt definitions
        if line.startswith('.ends') or line.startswith('.ENDS'):
            active_subckt = None

        print(f"Searching for match with '{line}'!")
        any_match = False
        for template in templates:
      
            match = template['regex'].match(line)
            if match:
                any_match = True
                # Flavio: templates com keep_strings ex: cmim mandam os parametros "string"
                # como texto para o PCell, sem converter para float
                keep_strings = template.get('keep_strings', False)
                if keep_strings:
                    params = dict(template['default_params'])
                else:
                    params = normalize_params(template['default_params'])

                # Parse parameters
                for param in template['params']:
                    print(f"Parsing parameter {param['name']}")
                    if param["type"] == "string":
                        if keep_strings:
                            parsed_value = match.group(param['name'])
                        else:
                            parsed_value = parse_si_value(match.group(param['name']))
                        params[param['name']] = parsed_value
                    if param["type"] == "int":
                        if match.group(param['name']) is None:
                            params[param['name']] = 1
                        else:
                            parsed_value = parse_si_value(match.group(param['name']))
                            params[param['name']] = int(parsed_value)
                    if param["type"] == "float":
                        parsed_value = parse_si_value(match.group(param['name']))
                        params[param['name']] = float(parsed_value)
              
                # Multiplicity 'm'
                m = 1
                if 'm' in params:
                    m = params.pop('m')
              
                # Divide 'w' by 'nf' to get individual finger width
                if 'nf' in params and params['nf'] > 1:
                    if 'w' in params:
                        params['w'] /= params['nf']
              
                print(f'Instantiating Pcell with: {params}')

                # Flavio: nets do componente = tokens entre o nome (XM6) e o modelo (sg13_lv_nmos).
                # O modelo e o token logo antes do primeiro "chave=valor"
                tokens = line.split()
                first_kv = next((k for k, t in enumerate(tokens) if '=' in t), len(tokens))
                nets = tokens[1:first_kv - 1]

                for i in range(m):
                    subckt_definitions[active_subckt]['pcells'].append({
                        'name_spice':       line.split()[0] if m == 1 else f"{line.split()[0]}_{i+1}", 
                        # Flavio: salvando o nome do componente que consta no SPICE para 
                        # passalo ao PCell e manter a consistencia do nome
                        'pcell_name':       template['pcell_name'],
                        'pcell_library':    template['pcell_library'],
                        'params':           params.copy(),
                        'nets':             nets,
                    })

        # Line was handled by template
        # no need to parse subcircuit
        if any_match:
            continue

        # Subckt instantiation
        # TODO: handle parameters
        if line.startswith('x') or line.startswith('X'):
            subckt = line.split(' ')[-1]
            subckt_definitions[active_subckt]['subckts'].append(subckt)
            
            if subckt not in subckt_definitions:
                print(f'Error: Unknown subckt "{subckt}"')  # Flavio: mostra o subckt que falta, nao o pai
            else:
                subckt_definitions[subckt]['references'] += 1

    return subckt_definitions


def instanciar(subckt_definitions):
    """Flavio: cria no layout os PCells e os pinos dos subckts de topo."""
    # Instanciate all top-level subckts
    for name in subckt_definitions.keys():
        if subckt_definitions[name]['references'] == 0:
            create_subckt_instance(name, subckt_definitions)

            # Flavio: pinos so do subckt de topo
            pin_x = 0
            for pin in subckt_definitions[name]['pins']:
                pin_x += create_pin_instance(pin['name'], pin['direction'], pin_x)


# =================== POSICOES DO XSCHEM ===================
# Flavio: simbolos do xschem que nao sao componentes nem pinos de I/O (rotulos, fontes de alimentacao, codigo...)
XSCHEM_IGNORADOS = {"lab_pin", "lab_wire", "gnd", "vdd", "code", "code_shown", "title", "launcher", "noconn"}
XSCHEM_PINOS = {"ipin", "opin", "iopin"}
XSCHEM_GAP_UM = 2.0  # folga minima entre componentes ao calcular a escala


def bloco_chaves(texto, inicio):
    """Devolve (conteudo, fim) do bloco {...} que abre em texto[inicio] (aceita chaves aninhadas e escapadas)."""
    nivel = 0
    i = inicio
    while i < len(texto):
        c = texto[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            nivel += 1
        elif c == "}":
            nivel -= 1
            if nivel == 0:
                return texto[inicio + 1:i], i + 1
        i += 1
    return texto[inicio + 1:], len(texto)


def ler_posicoes_xschem(sch_path):
    """
    Le as instancias do .sch do xschem (linhas "C {simbolo} x y rot flip {atributos}").
    Devolve dois dicionarios com a posicao (x, y) no sistema do xschem (y cresce para baixo):
      - componentes: chave = nome no netlist em maiusculas (spiceprefix + name, ex.: XM1)
      - pinos: chave = nome do pino (lab do ipin/opin/iopin)
    """
    texto = open(sch_path, encoding="utf-8", errors="replace").read()
    componentes, pinos = {}, {}

    for m in re.finditer(r"^C \{([^}]*)\}\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(?=\{)", texto, re.M):
        atributos, _ = bloco_chaves(texto, m.end())
        simbolo = os.path.splitext(os.path.basename(m.group(1)))[0]
        x, y = float(m.group(2)), float(m.group(3))

        def attr(nome):
            a = re.search(r"(?:^|\s)" + nome + r"=([^\s\"]+)", atributos)
            return a.group(1) if a else ""

        if simbolo in XSCHEM_PINOS:
            if attr("lab"):
                pinos[attr("lab")] = (x, y)
        elif simbolo not in XSCHEM_IGNORADOS and attr("name"):
            componentes[(attr("spiceprefix") + attr("name")).upper()] = (x, y)

    return componentes, pinos


def escala_sem_sobreposicao(itens):
    """
    Menor escala (um por unidade do xschem) em que nenhum par de componentes se sobrepoe.
    itens: lista de (x, y, largura_um, altura_um). Dois componentes nao se tocam se a distancia entre os
    centros, em x OU em y, for maior que a soma das meias-larguras (+ folga).
    """
    escala = 0.0
    for i in range(len(itens)):
        xi, yi, wi, hi = itens[i]
        for j in range(i + 1, len(itens)):
            xj, yj, wj, hj = itens[j]
            dx, dy = abs(xi - xj), abs(yi - yj)
            precisa_x = ((wi + wj) / 2 + XSCHEM_GAP_UM) / dx if dx > 0 else float("inf")
            precisa_y = ((hi + hj) / 2 + XSCHEM_GAP_UM) / dy if dy > 0 else float("inf")
            par = min(precisa_x, precisa_y)
            if par != float("inf"):
                escala = max(escala, par)
    return escala or 1.0


def posicionar_pelo_xschem(sch_path):
    """
    Move as cascas dos componentes e os pinos do layout para as posicoes do .sch, proporcionalmente.
    O componente mais a esquerda/acima do esquematico fica em (0, 0); y do xschem e invertido (cresce para baixo).
    Rotacao e espelhamento do xschem nao sao aplicados.
    """
    componentes, pinos_sch = ler_posicoes_xschem(sch_path)
    layout = pya.CellView.active().layout()
    top_cell = layout.top_cell()

    # cascas dos componentes: casam pelo nome; copias de m>1 (XM5_1, XM5_2) usam a posicao do original
    cascas = []
    sem_posicao = []
    for inst in top_cell.each_inst():
        nome = inst.property(PROP_NAME)
        if not nome:
            continue
        nome = str(nome).upper()
        base, copia = nome, 0
        m = re.fullmatch(r"(.+)_(\d+)", nome)
        if nome not in componentes and m and m.group(1) in componentes:
            base, copia = m.group(1), int(m.group(2)) - 1
        if base in componentes:
            cascas.append((inst, componentes[base], copia))
        else:
            sem_posicao.append(inst)

    # pinos: os 3 shapes (Metal1 drawing, pin e label) que o importador criou para cada pino
    l_draw, l_pin, l_text = (layout.layer(METAL1_DRAWING), layout.layer(METAL1_PIN), layout.layer(METAL1_TEXT))
    pinos = []
    for s in top_cell.shapes(l_pin).each():
        nome = s.property(PROP_NAME)
        if nome and str(nome) in pinos_sch:
            caixa = s.box
            juntos = [s] + [d for d in top_cell.shapes(l_draw).each() if d.is_box() and d.box == caixa]
            juntos += [t for t in top_cell.shapes(l_text).each()
                       if t.is_text() and t.text_string == str(nome) and caixa.contains(t.bbox().center())]
            pinos.append((juntos, s.dbbox(), pinos_sch[str(nome)]))

    if not cascas and not pinos:
        print(f"[Import Netlist] No component of the netlist was found in {sch_path}")
        return

    # escala proporcional: a menor que evita sobreposicao (copias de m>1 contam como um bloco so)
    itens = [(p[0], p[1], i.dbbox().width(), i.dbbox().height()) for i, p, c in cascas if c == 0]
    itens += [(p[0], p[1], b.width(), b.height()) for _, b, p in pinos]
    escala = escala_sem_sobreposicao(itens)

    # origem (0, 0) = canto mais a esquerda/acima entre os que foram importados (fontes, indutores etc. do .sch nao contam)
    usados = [p for _, p, _ in cascas] + [p for _, _, p in pinos]
    x0 = min(p[0] for p in usados)
    y0 = min(p[1] for p in usados)

    def destino(p):
        return pya.DPoint((p[0] - x0) * escala, -(p[1] - y0) * escala)  # y do xschem cresce para baixo

    for inst, p, copia in cascas:
        b = inst.dbbox()
        alvo = destino(p) + pya.DVector(copia * (b.width() + XSCHEM_GAP_UM), 0)
        inst.transform(pya.DTrans(alvo - b.center()))

    for juntos, b, p in pinos:
        desloc = pya.DTrans(destino(p) - b.center())
        for s in juntos:
            s.transform(desloc)

    # componentes que nao estao no .sch: numa fila abaixo do resto
    if sem_posicao:
        y_fila = min(i.dbbox().bottom for i, _, _ in cascas) - 10.0 if cascas else 0.0
        x = 0.0
        for inst in sem_posicao:
            b = inst.dbbox()
            inst.transform(pya.DTrans(pya.DVector(x - b.left, y_fila - b.top)))
            x += b.width() + XSCHEM_GAP_UM
        print(f"[Import Netlist] Not found in the xschem file (placed in a row below): "
              f"{[str(i.property(PROP_NAME)) for i in sem_posicao]}")

    print(f"[Import Netlist] Placed {len(cascas)} components and {len(pinos)} pins from {sch_path} "
          f"(scale {escala:.4f} um per xschem unit)")


# =================== UPDATE NETLIST ===================
UPDATE_PARAMS = ("w", "l")  # Flavio: parametros comparados e atualizados


def valor_num(v):
    """'2u' / '2e-6' / 2e-06 -> float em metros (None se nao for numero)."""
    try:
        return float(parse_si_value(v) if isinstance(v, str) else v)
    except (TypeError, ValueError):
        return None


def formatar_um(v):
    n = valor_num(v)
    return f"{n * 1e6:g}u" if n is not None else str(v)


def comparar_netlist(netlist_path):
    """
    Compara os componentes do layout (cascas, pelo nome) com o netlist novo.
    Devolve a lista de mudancas: (instancia do PCell, nome, {param: valor atual}, {param: valor novo}).
    So entram componentes que existem nos dois e cujo w ou l mudou.
    """
    definicoes = ler_netlist(netlist_path)
    novos = {str(p["name_spice"]).upper(): p for d in definicoes.values() for p in d["pcells"]}

    top_cell = pya.CellView.active().layout().top_cell()
    mudancas, no_layout = [], set()
    for inst in top_cell.each_inst():
        nome = inst.property(PROP_NAME)
        if not nome:
            continue
        nome = str(nome)
        no_layout.add(nome.upper())
        novo = novos.get(nome.upper())
        pcell = next(inst.cell.each_inst(), None)
        if novo is None or pcell is None or not pcell.cell.is_pcell_variant():
            continue

        atuais = pcell.cell.pcell_parameters_by_name()
        alterar = {}
        for k in UPDATE_PARAMS:
            if k in novo["params"] and k in atuais:
                a, b = valor_num(atuais[k]), valor_num(novo["params"][k])
                if a is not None and b is not None and abs(a - b) > 1e-6 * max(abs(a), abs(b)):
                    alterar[k] = novo["params"][k]
        if alterar:
            mudancas.append((pcell, nome, {k: atuais[k] for k in alterar}, alterar))

    # Flavio: so informativo no log; o update nao cria nem apaga componentes
    so_netlist = sorted(set(novos) - no_layout)
    so_layout = sorted(no_layout - set(novos))
    if so_netlist:
        print(f"[Update Netlist] In the netlist but not in the layout (ignored): {so_netlist}")
    if so_layout:
        print(f"[Update Netlist] In the layout but not in the netlist (ignored): {so_layout}")
    return mudancas


class AvisoUpdate(pya.QDialog):
    """Aviso geral antes do update, com a lista de todos os componentes que vao mudar."""

    def __init__(self, mudancas, parent=None):
        super(AvisoUpdate, self).__init__(parent)
        self.aceito = False
        self.setWindowTitle("Update Netlist")
        self.resize(520, 360)

        layout = pya.QVBoxLayout(self)
        layout.addWidget(pya.QLabel(f"The following {len(mudancas)} component(s) will be changed:", self))

        lista = pya.QListWidget(self)
        for _, nome, atuais, novos in mudancas:
            detalhes = ", ".join(f"{k}: {formatar_um(atuais[k])} -> {formatar_um(novos[k])}" for k in novos)
            lista.addItem(f"{nome}   ({detalhes})")
        layout.addWidget(lista, 1)

        linha_botoes = pya.QHBoxLayout()
        linha_botoes.addStretch()
        btn_aplicar = pya.QPushButton("Apply changes", self)
        btn_cancelar = pya.QPushButton("Cancel", self)
        linha_botoes.addWidget(btn_aplicar)
        linha_botoes.addWidget(btn_cancelar)
        layout.addLayout(linha_botoes)

        btn_aplicar.clicked.connect(self.aplicar)
        btn_cancelar.clicked.connect(self.reject)

    def aplicar(self, *args):
        self.aceito = True
        self.accept()


def atualizar(netlist_path):
    """Update netlist - mostra o aviso e, se aceito, troca w/l dos PCells do layout pelos do netlist."""
    try:
        if pya.CellView.active().layout() is None:
            pya.MessageBox.warning("Update Netlist", "Open the layout to be updated first.", pya.MessageBox.Ok)
            return

        mudancas = comparar_netlist(netlist_path)
        if not mudancas:
            pya.MessageBox.info("Update Netlist", "No w/l changes found between the netlist and the layout.", pya.MessageBox.Ok)
            return

        aviso = AvisoUpdate(mudancas, pya.Application.instance().main_window())
        aviso.exec_()
        if not aviso.aceito:
            print("[Update Netlist] Changes rejected by the user")
            return

        # Flavio: uma transacao so, para o Ctrl+Z desfazer o update inteiro
        view = pya.Application.instance().main_window().current_view()
        view.transaction("Update netlist")
        try:
            for pcell, nome, atuais, novos in mudancas:
                pcell.change_pcell_parameters(novos)
                # mantem o canto inferior esquerdo do PCell na origem da casca, como no import
                b = pcell.bbox()
                pcell.transform(pya.Trans(-b.left, -b.bottom))
                print(f"[Update Netlist] {nome}: " + ", ".join(f"{k} {formatar_um(atuais[k])} -> {formatar_um(novos[k])}" for k in novos))
        finally:
            view.commit()
        print(f"[Update Netlist] {len(mudancas)} component(s) updated")
    except Exception as e:
        print(f"[Update Netlist] Error: {e}")
        pya.MessageBox.warning("Update Netlist", f"Error updating the netlist:\n{e}", pya.MessageBox.Ok)


def importar(netlist_path=None, xschem_path=None):
    """Importa o netlist no layout aberto. Precisa de um layout aberto para receber os dispositivos."""
    global current_x
    current_x = 0  # Flavio: zera a cada importacao, senao acumula entre execucoes
    try:
        if pya.CellView.active().layout() is None:
            pya.MessageBox.warning("Import Netlist", "Open or create a layout before importing the netlist.", pya.MessageBox.Ok)
            return
        ihp130_import_netlist(netlist_path)
        if xschem_path:
            posicionar_pelo_xschem(xschem_path) # Flavio: com o .sch, reposiciona como no esquematico
    except Exception as e:
        print(f"[Import Netlist] Error: {e}")
        pya.MessageBox.warning("Import Netlist", f"Error importing the netlist:\n{e}", pya.MessageBox.Ok)


class JanelaImportNetlist(pya.QDialog):
    """Janela do botao Import Netlist escolhe entre importar um netlist novo ou atualizar."""

    def __init__(self, parent=None):
        super(JanelaImportNetlist, self).__init__(parent)
        self.setWindowTitle("Import Netlist")
        self.resize(560, 200)

        layout = pya.QVBoxLayout(self)

        # opcao 1: importar um netlist novo
        self.opcao_novo = pya.QRadioButton("Import new netlist", self)
        self.opcao_novo.setChecked(True)
        layout.addWidget(self.opcao_novo)

        # seletor de arquivo do netlist, logo abaixo da opcao 1 (recuado)
        linha_arquivo = pya.QHBoxLayout()
        linha_arquivo.addSpacing(24)
        self.label_arquivo = pya.QLabel("Xschem location:", self)
        dica_xschem = "Used to generate the components in the same positions as in xschem." # Flavio: balao de info
        self.label_arquivo.setToolTip(dica_xschem)
        linha_arquivo.addWidget(self.label_arquivo)
        self.campo_arquivo = pya.QLineEdit(self)
        self.campo_arquivo.setPlaceholderText("Optional: path to the xschem schematic (.sch)") # Flavio: campo opcional, aceita .sch
        self.campo_arquivo.setToolTip(dica_xschem)
        linha_arquivo.addWidget(self.campo_arquivo, 1)
        self.btn_procurar = pya.QPushButton("Browse...", self)
        linha_arquivo.addWidget(self.btn_procurar)
        layout.addLayout(linha_arquivo)

        # opcao 2: atualizar um netlist ja importado
        self.opcao_update = pya.QRadioButton("Update netlist", self)
        layout.addWidget(self.opcao_update)

        # Flavio: seletor do netlist SPICE que sera importado, abaixo das opcoes
        linha_spice = pya.QHBoxLayout()
        linha_spice.addWidget(pya.QLabel("SPICE netlist:", self))
        self.campo_spice = pya.QLineEdit(self)
        self.campo_spice.setPlaceholderText("Path to the SPICE netlist to import (.spice)")
        linha_spice.addWidget(self.campo_spice, 1)
        self.btn_procurar_spice = pya.QPushButton("Browse...", self)
        linha_spice.addWidget(self.btn_procurar_spice)
        layout.addLayout(linha_spice)

        layout.addStretch()

        # botoes
        linha_botoes = pya.QHBoxLayout()
        # Flavio: aviso de PDK suportado
        linha_botoes.addWidget(pya.QLabel("Only for IHP-SG13G2 PDK", self))
        linha_botoes.addStretch()
        self.btn_ok = pya.QPushButton("OK", self)
        self.btn_cancelar = pya.QPushButton("Cancel", self)
        linha_botoes.addWidget(self.btn_ok)
        linha_botoes.addWidget(self.btn_cancelar)
        layout.addLayout(linha_botoes)

        self.btn_procurar.clicked.connect(self.procurar_arquivo)
        self.btn_procurar_spice.clicked.connect(self.procurar_spice)
        self.opcao_novo.toggled.connect(self.atualizar_campos)
        self.btn_ok.clicked.connect(self.confirmar)
        self.btn_cancelar.clicked.connect(self.reject)

    def atualizar_campos(self, *args):
        """Acao do botao abre (ou traz para frente) a janela do Import Netlist."""
        ativo = self.opcao_novo.isChecked()
        self.label_arquivo.setEnabled(ativo)
        self.campo_arquivo.setEnabled(ativo)
        self.btn_procurar.setEnabled(ativo)

    def procurar_arquivo(self, *args):
        inicio = os.path.dirname(self.campo_arquivo.text) if self.campo_arquivo.text else "."
        caminho = pya.FileDialog.ask_open_file_name("Choose the xschem schematic", inicio,
                                                    "Xschem schematic (*.sch)") # Flavio: so .sch
        if caminho:
            self.campo_arquivo.setText(caminho)

    def procurar_spice(self, *args):
        """Seletor do netlist SPICE que sera importado."""
        inicio = os.path.dirname(self.campo_spice.text) if self.campo_spice.text else "."
        caminho = pya.FileDialog.ask_open_file_name("Choose the SPICE netlist", inicio,
                                                    "SPICE (*.spice *.spc *.sp *.cir);;All files (*)")
        if caminho:
            self.campo_spice.setText(caminho)

    def confirmar(self, *args):
        if self.opcao_novo.isChecked():
            # Flavio: o netlist SPICE e obrigatorio; o xschem (.sch) e opcional
            spice = self.campo_spice.text.strip()
            if not spice or not os.path.isfile(spice):
                pya.MessageBox.warning("Import Netlist", "Select a valid SPICE netlist file.", pya.MessageBox.Ok)
                return
            xschem = self.campo_arquivo.text.strip()
            if xschem and (not xschem.lower().endswith(".sch") or not os.path.isfile(xschem)):
                pya.MessageBox.warning("Import Netlist", "Select a valid xschem schematic (.sch) file or leave it empty.", pya.MessageBox.Ok)
                return
            self.accept()
            importar(spice, xschem or None) # Flavio: o .sch (opcional) define as posicoes
        else:
            # Flavio: Update netlist - usa o mesmo campo do SPICE
            spice = self.campo_spice.text.strip()
            if not spice or not os.path.isfile(spice):
                pya.MessageBox.warning("Import Netlist", "Select a valid SPICE netlist file.", pya.MessageBox.Ok)
                return
            self.accept()
            atualizar(spice)


_janela_import = None


def abrir_janela_import():
    """Acao do botao abre (ou traz para frente) a janela do Import Netlist."""
    global _janela_import
    if _janela_import is None:
        _janela_import = JanelaImportNetlist(pya.Application.instance().main_window())
    _janela_import.show()
    _janela_import.raise_()
    _janela_import.activateWindow()


def plugin_import_netlist():
    """Cria o botao "Import Netlist" na toolbar, no mesmo padrao do LivePEX e do Live DRC."""
    mw = pya.Application.instance().main_window()
    if mw is None:
        return

    acao = pya.Action()
    acao.title = "Import Netlist"
    acao.tool_tip = "Import a SPICE netlist (xschem) as IHP-SG13G2 PCells"
    acao.icon = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "icons", "netlist.png")
    acao.on_triggered = abrir_janela_import # Flavio: o botao agora abre a janela de opcoes

    mw.menu().insert_item("@toolbar.end", "import_netlist", acao)
