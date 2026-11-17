# klayout-NAT architecture

User documentation: [doc/readme.html](doc/readme.html). This file is for whoever changes the code.

## Startup

KLayout runs every macro in a package's `pymacros/` folder that is marked as autorun. Here that is
`pymacros/autorun.lym`, which:

1. adds `pymacros/` to `sys.path`;
2. calls `live_drc.register_plugin()`, `live_pex.plugin_pex()` and `ratsnest.register_ratsnest()`;
3. loads `import_netlist.py` by file path (`importlib.util.spec_from_file_location`) and calls
   `plugin_import_netlist()`. A plain `import import_netlist` could pick up the PDK's own
   `import_netlist` package, which is also on `sys.path`.

Each `register`/`plugin` function adds one `pya.Action` at `@toolbar.end`, except Ratsnest, which only
hooks into the views.

## Modules

| Module | Entry point | Main pieces |
|---|---|---|
| `live_drc.py` | `register_plugin()` | `LiveDRC`: toolbar action, a 2 s timer that compares the file time of the active cellview, `run_drc.py` started with `subprocess.Popen`, a 500 ms timer that waits for it and loads the `.lyrdb` |
| `live_pex.py` | `plugin_pex()` | `PluginLivePex` (`QDialog`): `pex_magic()` uses `klayout_pex.magic.magic_runner` to write the Tcl script and run Magic; `pex_25d()` and `run_lvs()` are kept but the button is disabled |
| `import_netlist.py` | `plugin_import_netlist()` | `JanelaImportNetlist` (window); `importar()` parses the netlist (`ler_netlist`), creates the PCells and pins (`instanciar`) and optionally moves them (`posicionar_pelo_xschem`); `atualizar()` compares w/l (`comparar_netlist`) and changes the PCells inside one undo transaction |
| `ihp130_pcell_templates.py` | `templates` | one regex per SPICE device model, mapped to an SG13G2 PCell and its parameters |
| `ratsnest.py` | `register_ratsnest()` | `on_selection_changed` on every view plus a 300 ms timer that redraws when the selection moves; lines are `pya.Annotation` rulers in their own category |

## Data shared between modules

Import Netlist writes, and Ratsnest reads, user properties with integer keys (GDS drops string keys):

| Key | Stored on | Value |
|---|---|---|
| 1 | device cell instance, Metal1 pin shape (8/2) | SPICE instance name or pin name |
| 2 | device cell instance | terminal nets in SPICE order, separated by spaces |
| 3 | Metal1 pin shape | `ipin`, `opin` or `iopin` |

The device cell is named after the SPICE instance and contains a single PCell instance with its
lower-left corner at the origin. Update Netlist relies on that layout of the cell.

## External programs and files

| Tool | Uses | Writes |
|---|---|---|
| LiveDRC | `python3 run_drc.py` from the PDK, `~/.ihp_pdk/ihp_sg13g2_drc_options.yml` | `drc_run_<topcell>/` next to the layout (recreated on each run) |
| LivePEX | `klayout-pex` Python package, `magic`, PDK `.magicrc` | `pex_magic_<topcell>/` next to the layout |
| Import Netlist | xschem `.spice` and, optionally, `.sch` | only the open layout |

## Packaging

`grain.xml` follows the KLayout package format: `name` identifies the package and must not change
(a new name is a new package for KLayout), `version` must go up on every release, and `doc-url`
points to `doc/readme.html`, relative to the package folder.
