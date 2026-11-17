"""
Ratsnest estilo Cadence - ao selecionar uma casca de componente (criada pelo
import_netlist) ou um pino, desenha linhas ate os outros componentes/pinos que dividem
alguma net com ele. Sem selecao, as linhas somem.

Le as propriedades gravadas pelo import_netlist:
  - casca de componente: "name" (ex.: XM6) e "nets" (ex.: "RFN LON net2 GND")
  - shape de pino (Metal1 pin 8/2): "name" (ex.: VDC), que e a propria net
"""

import pya

RATSNEST_CATEGORY = "ratsnest"

# Flavio: nets ignoradas (ligam quase tudo e viram uma teia). Edite conforme o circuito
IGNORED_NETS = {"GND", "sub!"}

METAL1_PIN = pya.LayerInfo(8, 2)

# Flavio: chaves numericas das propriedades (iguais as do import_netlist.py). Numeros porque o
# GDS descarta chaves de texto ao salvar; as de texto ficam como alternativa para arquivos antigos
PROP_NAME = 1
PROP_NETS = 2


def _prop(obj, key, old_key):
    """Flavio: le a propriedade pela chave numerica; se nao tiver, tenta a chave de texto antiga."""
    value = obj.property(key)
    return value if value is not None else obj.property(old_key)

# Flavio: o KLayout nao tem evento de "objeto movido", entao um timer confere a posicao
# do que esta selecionado e redesenha quando ela muda (ou seja, quando o movimento termina)
CHECK_INTERVAL_MS = 300

_timer = None
_last_signature = None


def _collect_nodes(layout, top_cell):
    """
    lista todos os nos do ratsnest na top cell: (nome, nets, centro em um).
    Cascas de componentes vem das instancias; pinos vem dos shapes de Metal1 pin.
    """
    nodes = []

    for inst in top_cell.each_inst():
        nets = _prop(inst, PROP_NETS, "nets")
        if nets:
            nodes.append((str(_prop(inst, PROP_NAME, "name")), set(str(nets).split()), inst.dbbox().center()))

    pin_layer = layout.find_layer(METAL1_PIN)
    if pin_layer is not None:
        for shape in top_cell.shapes(pin_layer).each():
            name = _prop(shape, PROP_NAME, "name")
            if name:
                nodes.append((str(name), {str(name)}, shape.dbbox().center()))

    return nodes


def _selected_names(view):
    """nomes das cascas/pinos selecionados (sobe ate a top cell se clicou dentro da casca)."""
    names = set()
    for obj in view.each_object_selected():
        if len(obj.path) > 0:
            # path[0] e a instancia na top cell (a casca), mesmo se o PCell dentro dela foi clicado
            name = _prop(obj.path[0].inst(), PROP_NAME, "name")
        else:
            # shape solto na top cell (pino)
            name = _prop(obj.shape, PROP_NAME, "name")
        if name:
            names.add(str(name))
    return names


def _selection_signature(view):
    """"assinatura" da selecao = posicoes dos objetos selecionados. Muda quando algo e movido."""
    sig = []
    for obj in view.each_object_selected():
        if len(obj.path) > 0:
            sig.append(str(obj.path[0].inst().dbbox()))
        else:
            sig.append(str(obj.shape.dbbox()))
    return tuple(sorted(sig))


def _clear(view):
    old = [a for a in view.each_annotation() if a.category == RATSNEST_CATEGORY]
    for a in old:
        a.delete()


def update_ratsnest(view=None):
    """Flavio: apaga as linhas antigas e desenha as da selecao atual (view atual por padrao)."""
    if view is None:
        mw = pya.Application.instance().main_window()
        view = mw.current_view() if mw else None
    if view is None:
        return

    global _last_signature
    _last_signature = _selection_signature(view)

    _clear(view)

    cv = view.active_cellview()
    if not cv.is_valid():
        return
    layout = cv.layout()
    top_cell = layout.top_cell()
    if top_cell is None:
        return

    selected = _selected_names(view)
    if not selected:
        return

    nodes = _collect_nodes(layout, top_cell)
    sources = [n for n in nodes if n[0] in selected]

    # Flavio: estrela - do componente selecionado ate cada outro no que divide uma net
    for src_name, src_nets, src_pos in sources:
        src_nets = src_nets - IGNORED_NETS
        for dst_name, dst_nets, dst_pos in nodes:
            if dst_name == src_name:
                continue
            for net in sorted(src_nets & dst_nets):
                a = pya.Annotation()
                a.p1 = src_pos
                a.p2 = dst_pos
                a.style = pya.Annotation.StyleLine
                a.outline = pya.Annotation.OutlineDiag
                a.fmt = net
                a.category = RATSNEST_CATEGORY
                view.insert_annotation(a)


def _on_selection_changed():
    try:
        update_ratsnest()
    except Exception as e:
        print(f"Ratsnest: erro {e}")


def _check_moved():
    """Flavio: chamado pelo timer. Redesenha so se a posicao do que esta selecionado mudou."""
    try:
        mw = pya.Application.instance().main_window()
        view = mw.current_view() if mw else None
        if view is None or not view.has_object_selection():
            return
        if _selection_signature(view) != _last_signature:
            update_ratsnest(view)
    except Exception as e:
        print(f"Ratsnest: erro {e}")


def _hook_current_view():
    mw = pya.Application.instance().main_window()
    view = mw.current_view() if mw else None
    if view is not None:
        # Flavio: "=" substitui o handler anterior, para nao registrar duas vezes na mesma view
        view.on_selection_changed = _on_selection_changed


def register_ratsnest():
    """chamado pelo autorun.lym. Liga o ratsnest na view atual e nas que forem abertas."""
    mw = pya.Application.instance().main_window()
    if mw is None:
        return
    mw.on_current_view_changed = _hook_current_view
    _hook_current_view()

    global _timer
    if _timer is None:
        _timer = pya.QTimer(mw)
        _timer.timeout += _check_moved
        _timer.start(CHECK_INTERVAL_MS)
