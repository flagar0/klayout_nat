# 👁️ Live DRC Plugin - KLayout

Executa o DRC do PDK IHP SG13G2 automaticamente ao salvar o layout.

## Instalar

1. Copia `PluginNat/` pra `~/.klayout/salt/` (Linux) ou `%APPDATA%\KLayout\salt\` (Windows)
2. Reinicia KLayout
3. Botão "Live DRC" aparece na toolbar

## Usar

- Clica no botão "Live DRC" na toolbar → muda pra `[ON]`
- Salva o layout (Ctrl+S)
- Plugin detecta o save e executa o DRC automaticamente via `run_drc.py`
- Resultados `.lyrdb` são carregados como markers na view

## Requisitos

- PDK IHP SG13G2 instalado
- `run_drc.py` acessível via uma das opções:
  - Variável `PDKPATH` apontando para `ihp-sg13g2/`
  - Variável `KLAYOUT_PATH` incluindo o diretório `tech/`
  - Caminho padrão IIC-OSIC-TOOLS: `/foss/pdks/ihp-sg13g2/...`
- Python 3.9+
- KLayout 0.29+

## Opções do DRC

O plugin lê opções do arquivo `~/.ihp_pdk/ihp_sg13g2_drc_options.yml` (mesmo arquivo usado pelo menu DRC do PDK). Se não existir, usa defaults:

- `run_mode: deep`
- `no_density: true` (checks de densidade desabilitados por padrão)
- `parallel_runs: 1`

## Status

- ✅ Detecção de save via polling de mtime
- ✅ Execução automática do DRC via subprocess
- ✅ Carregamento automático dos resultados na view
- ✅ Proteção contra execuções simultâneas

## Debug

Console: F5

Logs esperados ao salvar:
```
[Live DRC] Save detectado: arquivo.gds
[Live DRC] Executando DRC...
[Live DRC] Comando: python3 .../run_drc.py --path=...
[Live DRC] DRC iniciado (PID=12345)
[Live DRC] DRC finalizado com sucesso (code=0)
[Live DRC] Resultados carregados: arquivo_TOP_main.lyrdb
```
