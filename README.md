# StockPilot

**SMART INVENTORY MANAGEMENT**  
*Controle inteligente. Gestão eficiente.*

Sistema de gestão para pequenos e médios comércios brasileiros (Windows): produtos e estoque, compras, vendas/PDV, financeiro,
estimativas de MEI/Simples Nacional, funcionários e folha estimada, relatórios em PDF/Excel, backup e licença offline.
Interface em português, valores em R$, datas DD/MM/AAAA. **Não há IA dentro do produto.**

> **Importante:** tributos e folha são **ESTIMATIVAS** de apoio à gestão. O sistema **não emite NFC-e/NF-e, não transmite eSocial,
> PGDAS-D, PGMEI nem DCTF** e não substitui o contador. Veja `docs/LIMITACOES.md`.

## Como obter o instalador do Windows
O instalador `.exe` precisa ser gerado **no Windows** (não é possível gerá-lo em Linux/Mac). Duas formas:

1. **No seu PC Windows (mais simples):** instale o [Python 3.12 64 bits](https://www.python.org/downloads/) (marque *Add python.exe to PATH*)
   e o [Inno Setup 6](https://jrsoftware.org/isdl.php); dê duplo clique em **`build_windows.bat`**. Ele instala as dependências, roda os testes,
   gera o programa, faz um autoteste do executável e cria `dist_installer\StockPilot-Setup-<versão>.exe`.
2. **GitHub Actions:** envie o projeto a um repositório, abra *Actions → Gerar instalador Windows → Run workflow* e baixe o artefato.

Só quer testar sem instalar? Duplo clique em **`INSTALAR_E_EXECUTAR.bat`** (roda do código-fonte).

## Desenvolvimento
```
python -m venv .venv && .venv\Scripts\activate      (Linux/Mac: source .venv/bin/activate)
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest          (Windows: set QT_QPA_PLATFORM=offscreen)
python run_stockpilot.py
```
Dados: `%LOCALAPPDATA%\StockPilot` (banco, backups, logs) — fora da pasta do programa; atualizar ou desinstalar **não apaga** os dados.
Para desenvolvimento use `STOCKPILOT_HOME=<pasta>`.

## Documentação
- `docs/STATUS.md` — o que está pronto, parcial e não testado
- `docs/LIMITACOES.md` — limitações e premissas (leia antes de vender)
- `docs/FONTES_TRIBUTARIAS_E_TRABALHISTAS.md` — de onde vêm as tabelas e como atualizá-las
- `docs/LICENCIAMENTO.md` — chaves de licença (hoje DESLIGADAS; o produto é vendido sem ativação)
- `docs/ASSINATURA_DO_INSTALADOR.md` — como assinar o instalador no Windows
- `docs/TERMOS_DE_USO.md`, `docs/POLITICA_DE_PRIVACIDADE.md` — modelos a preencher; `docs/pdf/` — PDFs (`python tools/build_docs_pdf.py`)
- `docs/POLITICA_DE_RETENCAO.md` — retenção de dados e LGPD
- `docs/MANUAL_DO_USUARIO.md` — guia rápido para o lojista
- `docs/FASE1_PLANEJAMENTO.md` — arquitetura, modelo de dados, riscos
