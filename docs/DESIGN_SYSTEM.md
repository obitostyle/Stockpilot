# Design system do StockPilot — "Precision Dark" (v0.4.0)

Todas as decisões visuais ficam em `src/stockpilot/ui/theme.py`, que reúne as cores, a fonte, o QSS e a paleta Qt. As telas usam só objectName e propriedades.

## Cores
| Token | Valor | Uso |
|---|---|---|
| BG | #0B0D12 | fundo das telas |
| SIDEBAR | #0F1219 | menu lateral, barra de status |
| PANEL | #141923 | painéis, tabelas, faixas de indicadores |
| RAISED | #191F2B | campos, hover, menus |
| BORDER | #252D3A | fios e bordas |
| TEXT / MUTED / SUBTLE | #F1F5F9 / #94A3B8 / #8291A7 | texto principal, secundário e auxiliar. Todos têm contraste de 4,5:1 ou mais sobre PANEL (WCAG AA) |
| ACCENT | #4F8CFF | item ativo, foco, seleção, gráfico |
| PRIMARY | #2F6FE8 | fundo do botão primário (texto branco 4,6:1) |
| OK / WARN / DANGER | #34D399 / #FBBF24 / #F87171 | positivo, vencido/atenção, negativo/destrutivo |

## Tipografia
- **Bahnschrift**, a fonte DIN que já vem no Windows, para títulos de página e valores dos indicadores. É a assinatura visual do produto e lembra etiqueta de estoque e precisão.
- **Segoe UI Variable** para o resto da interface.
- Escala: título 19pt, seção 11pt (peso 600), corpo 10pt, auxiliar 9 a 8,5pt. Não há rótulos em caixa alta.

## Espaçamento e forma
- Espaçamentos múltiplos de 4: 4, 8, 12, 16, 24, 32. As páginas têm margem de 32 px.
- Raios de 6 px nos controles e de 10 px nos painéis.

## Componentes
- **Botões** em quatro níveis: `primary` (ação principal), padrão (secundária), `ghost` (terciária, por exemplo Importar e Exportar) e `danger` / `danger-solid` (destrutiva).
- **Tabelas**:
  - Os títulos das colunas seguem o alinhamento dos dados.
  - As linhas têm 36 px, sem quebra de linha; o texto longo termina em "…" e aparece inteiro na dica.
  - A rolagem é suave e a lista vazia mostra uma mensagem que diz o que fazer.
- **Indicadores**: faixas (`strip`) com células separadas por fios, em vez de um cartão para cada número.
- **Avisos** (`hint`): painel neutro com um fio azul à esquerda.
- **Feedback**: um aviso rápido (`toast`) aparece após as ações, e as confirmações destrutivas mostram o botão vermelho com Cancelar como padrão.
- **Movimento**: troca de tela em 140 ms e abertura de diálogo em 110 ms. Não há outras animações.

## Componentes desenhados (v0.5.0)

O PySide6 não roda Tailwind nem bibliotecas web. A qualidade equivalente vem de componentes pintados com QPainter, em `ui/delegates.py` e `ui/charts.py`, e de animações reais com QPropertyAnimation.

- **Indicador do menu**: um realce com um fio azul desliza até a seção escolhida em 180 ms (OutCubic). É a única animação de destaque do produto.
- **Realce de linha**: ao passar o mouse, a linha inteira da tabela acende (`ROW_HOVER`), não só a célula.
- **Selos de situação**: ficam nas colunas "Situação" e "Tipo" de todas as tabelas. O tom vem do texto que o sistema já exibe:
  - verde: ativo, concluída, confirmada, quitada;
  - âmbar: rascunho, em aberto, férias;
  - vermelho: cancelada, vencida, estornada;
  - neutro: inativo, desligado;
  - azul: ajuste, inventário.
- **Medidor de estoque** em Produtos e na Reposição do painel:
  - A barra vai até o dobro do estoque mínimo.
  - Vermelho = zerado; âmbar = abaixo do mínimo; verde = ok.
- **Gráfico de vendas**: área com curva suave e preenchimento que esmaece. Ao passar o mouse aparece uma linha de cursor e um balão com a data e o valor.
- **Ícones**: os botões que usavam os caracteres "＋" e "−" recebem automaticamente ícones de traço fino.
- **Colunas adaptáveis**: em janelas com menos de 1180 px, a tabela de produtos esconde Cód. barras e Categoria.
