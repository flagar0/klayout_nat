# 🏗️ Arquitetura - Live DRC Plugin

## 📐 Visão Geral

```
┌─────────────────────────────────────────┐
│          KLayout Application            │
│  ┌───────────────────────────────────┐  │
│  │      Main Window / Menu           │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  Tools > Live DRC 👁️       │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
│                  ↓                      │
│  ┌───────────────────────────────────┐  │
│  │      LiveDRC Plugin Class         │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  • setup_menu()             │  │  │
│  │  │  • toggle_live_drc()        │  │  │
│  │  │  • ativar_live_drc()        │  │  │
│  │  │  • desativar_live_drc()     │  │  │
│  │  │  • on_view_changed()        │  │  │
│  │  │  • executar_drc()           │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
│                  ↓                      │
│  ┌───────────────────────────────────┐  │
│  │    Layout View / Cellview         │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  • active_cellview()        │  │  │
│  │  │  • layout()                 │  │  │
│  │  │  • cell()                   │  │  │
│  │  │  • add_marker()             │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│        DRC Engine (KLayout)             │
│  ┌───────────────────────────────────┐  │
│  │  • Carrega script DRC             │  │
│  │  • Executa regras                 │  │
│  │  • Gera relatório                 │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│        PDK DRC File                     │
│  ihp-sg13g2.drc                         │
└─────────────────────────────────────────┘
```

## 🔧 Componentes Principais

### 1. LiveDRC Class (`live_drc.py`)

**Responsabilidade**: Gerenciar todo o ciclo de vida do plugin

**Estados**:
```python
self.ativo = "False"          # Status do Live DRC ("True"/"False")
self.ultima_analise = None    # Timestamp da última análise
self.main_window = None       # Referência à janela principal
self.action = None            # Action do menu
```

**Métodos Públicos**:
- `setup_menu()`: Cria botão no menu Tools
- `toggle_live_drc()`: Liga/desliga o modo Live DRC
- `ativar_live_drc()`: Ativa o monitoramento
- `desativar_live_drc()`: Desativa o monitoramento

**Métodos Privados**:
- `on_view_changed()`: Callback quando view muda (save)
- `executar_drc()`: Executa análise DRC no layout

### 2. Inicialização (`__init__.py`)

**Responsabilidade**: Auto-carregar o plugin quando KLayout inicia

```python
from . import live_drc  # Import do módulo principal
```

### 3. Registro Global

**Responsabilidade**: Criar instância singleton do plugin

```python
_live_drc_instance = None

def register_plugin():
    global _live_drc_instance
    if _live_drc_instance is None:
        _live_drc_instance = LiveDRC()

# Auto-register
register_plugin()
```

## 🔄 Fluxo de Execução

### Inicialização

```
1. KLayout inicia
   ↓
2. Carrega módulos Python da pasta salt/
   ↓
3. Executa __init__.py
   ↓
4. Import live_drc.py
   ↓
5. register_plugin() cria instância LiveDRC
   ↓
6. LiveDRC.__init__() chama setup_menu()
   ↓
7. Menu item "Live DRC 👁️" aparece em Tools
```

### Ativação do Live DRC

```
1. Usuário clica "Tools > Live DRC 👁️"
   ↓
2. toggle_live_drc() verifica self.ativo
   ↓
3. Se "False": chama ativar_live_drc()
   ↓
4. Valida se DRC_FILE existe
   ↓
5. Conecta callback: app.on_view_changed(self.on_view_changed)
   ↓
6. Atualiza menu: "Live DRC ✅ (Ativo)"
   ↓
7. Mostra popup de confirmação
```

### Análise DRC (ao salvar)

```
1. Usuário salva layout (Ctrl+S)
   ↓
2. KLayout dispara evento view_changed
   ↓
3. on_view_changed() verifica se ativo == "True"
   ↓
4. Delay de 0.5s (garantir que salvou)
   ↓
5. Chama executar_drc(view)
   ↓
6. Pega cellview ativo
   ↓
7. Limpa markers anteriores
   ↓
8. Carrega arquivo DRC do PDK
   ↓
9. Cria DRC Engine
   ↓
10. Executa script DRC
    ↓
11. Coleta resultados (erros)
    ↓
12. Adiciona markers no layout
    ↓
13. Calcula estatísticas (tempo, num erros)
    ↓
14. Loga no console
    ↓
15. Se erros > 0: mostra popup
```

## 📦 Dependências

### KLayout Python API (`pya`)

**Módulos usados**:
- `pya.Application`: Acesso à aplicação principal
- `pya.QObject`: Base class para objetos Qt
- `pya.Action`: Item de menu
- `pya.MessageBox`: Popups/dialogs
- `pya.DRC.DRCEngine`: Engine de DRC
- `pya.ReportDatabase`: Relatórios de DRC

### Python Standard Library

- `os`: Manipulação de paths
- `time`: Delays e timing
- `datetime`: Timestamps

## 🔀 Estados e Transições

```
┌─────────────┐
│  Desativado │  (self.ativo = "False")
│    👁️       │
└──────┬──────┘
       │ toggle_live_drc()
       │ (click no botão)
       ↓
┌─────────────┐
│  Validando  │  (verifica DRC_FILE)
└──────┬──────┘
       │ DRC_FILE OK
       ↓
┌─────────────┐
│   Ativado   │  (self.ativo = "True")
│    ✅       │  (conecta callback)
└──────┬──────┘
       │ on_view_changed()
       │ (evento de save)
       ↓
┌─────────────┐
│  Executando │  (rodando DRC)
│    🔍       │
└──────┬──────┘
       │ DRC completo
       ↓
┌─────────────┐
│  Mostrando  │  (markers + popup)
│  Resultado  │
│    📊       │
└──────┬──────┘
       │ volta para
       ↓
┌─────────────┐
│   Ativado   │  (aguardando próximo save)
│    ✅       │
└─────────────┘
```

## 🎨 Design Patterns Utilizados

### Singleton Pattern
- Instância global `_live_drc_instance`
- Garante único plugin ativo

### Observer Pattern
- `app.on_view_changed()` observa mudanças na view
- Callback `on_view_changed()` reage a eventos

### Command Pattern
- `pya.Action` encapsula comando do menu
- `on_triggered()` executa ação

## 🛡️ Tratamento de Erros

**Estratégia**: Catch genérico + log + continue

```python
try:
    # logica principal
    return True
except BaseException as e:
    print(f"❌ Erro: {e}")
    return False
```

**Pontos de falha tratados**:
1. Setup do menu
2. Arquivo DRC não existe
3. Cellview inválido
4. Erro ao executar DRC
5. Erro ao processar resultados

## 📊 Performance

**Otimizações**:
- Delay de 0.5s evita múltiplas execuções
- Verifica `self.ativo` antes de processar
- Limpa markers anteriores antes de adicionar novos

**Bottlenecks conhecidos**:
- Execução do DRC script (depende do PDK)
- Processamento de layouts grandes
- Callback pode disparar múltiplas vezes

**Melhorias futuras**:
- Debounce/throttle no callback
- DRC incremental (só área modificada)
- Cache de resultados

## 🔐 Thread Safety

**Atual**: Single-threaded (roda na main thread do KLayout)

**Considerações**:
- Callbacks rodam na thread principal
- Sem concorrência de acesso a `self.ativo`
- DRC Engine é blocking

## 📝 Logging

**Formato**:
```python
print("✅ Mensagem de sucesso")
print("❌ Mensagem de erro")
print("🔍 Ação em progresso")
print("📊 Estatísticas")
```

**Níveis** (informal):
- ✅ = Info/Success
- ❌ = Error
- 🔍 = Debug/Progress
- 📊 = Metrics

## 🔄 Ciclo de Vida

```
Plugin Load → Setup Menu → Idle
                             ↓
                    (user clicks button)
                             ↓
                    Activate → Monitor
                                 ↓
                          (save detected)
                                 ↓
                    Execute DRC → Show Results
                                 ↓
                          Back to Monitor
                                 ↓
                    (user clicks button again)
                                 ↓
                          Deactivate → Idle
```

---

**Nota**: Esta arquitetura prioriza simplicidade e funcionalidade sobre complexidade desnecessária. É código funcional, não código "bonito". 😎
