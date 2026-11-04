# Limitações e premissas

Leia antes de comercializar. Nada aqui é escondido do usuário: as telas mostram os mesmos avisos.

## O que o produto NÃO faz
- **Não emite NFC-e/NF-e/NFS-e** nem se comunica com a SEFAZ. A venda gera um "comprovante interno — não é documento fiscal". Lojas que precisam de cupom fiscal precisam de outro sistema/emissor integrado (projeto à parte: certificado digital, homologação por UF).
- **Não transmite** PGDAS-D, PGMEI, DASN, DCTF, eSocial, FGTS Digital, SPED. Só estima valores e organiza dados.
- **Não calcula** tributos de Lucro Presumido/Lucro Real (guarda faturamento e gera relatórios para o contador).
- **Não é folha oficial**: sem holerite legal, sem rescisão homologável, sem GPS/GFIP.

## Tributário (Simples Nacional / MEI)
- Simples: só **Anexo I (comércio)**. Anexos II–V e Fator R não estão carregados (o usuário pode cadastrar novas tabelas, mas o cálculo implementado é o do Anexo I).
- **Não** segrega ICMS-ST, monofásico (PIS/COFINS), isenções ou receitas de exportação: se o cliente vende esses produtos, o DAS estimado tende a ser **maior** que o oficial.
- RBT12 conforme Res. CGSN 140 art. 22 (1º mês × 12; média até o 12º mês; soma dos 12 anteriores depois). Meses sem faturamento registrado deixam a estimativa **INCOMPLETA** e são listados.
- **Competências a partir de 01/2027:** a Res. CGSN 190/2026 altera regras; **não implementadas** — o sistema avisa e marca como incompleta.
- Vencimento exibido = dia 20 do mês seguinte, sem ajuste de dia útil (fontes divergem). Confirmar no PGDAS-D/PGMEI.
- MEI: DAS fixo = 5% do salário mínimo + ICMS (R$ 1) e/ou ISS (R$ 5); limite anual R$ 81.000 (R$ 6.750/mês proporcional no ano de abertura). Alerta a partir de 80%; não calcula DAS complementar de excesso nem desenquadramento.

## Folha e simulações
- INSS progressivo e IRRF mensal 2026 (tabela + dedução por dependente + desconto simplificado, usando o que dá menos imposto) + **redução da Lei 15.270/2025**.
- **Não verificado:** se a redução da Lei 15.270 se aplica a 13º, férias e rescisão. As simulações **não** a aplicam e avisam "NÃO verificada".
- Rescisão: **bruta** — não calcula INSS/IRRF sobre as verbas, FGTS sobre verbas, estabilidades, médias de variáveis, nem convenção coletiva.
- Não calcula: hora noturna reduzida, insalubridade/periculosidade, comissões, pensão alimentícia, desconto de DSR por faltas, reflexos de variáveis em férias/13º.
- Encargos do empregador: Simples (Anexos I, II, III, V) = CPP incluída no DAS (patronal = 0); demais regimes exigem RAT/FAP e terceiros informados em Configurações — sem eles o custo total é **"não calculado"** (nunca preenchido com chute). MEI com empregado: contribuição patronal **não implementada**.
- Acesso a funcionários/folha restrito a Administrador e Gerente.

## Estoque e financeiro
- Custo médio ponderado; estornar uma **entrada** depois que o custo médio mudou devolve só a quantidade (não recalcula o custo retroativamente).
- Financeiro: faturamento por competência (data da venda); recebimentos em caixa; cartão é lançado no ato da venda (sem taxa da operadora, sem prazo de repasse); despesas em regime de caixa; compra de mercadoria não é despesa (chega ao resultado via CMV). **Resultado operacional é estimativa gerencial.**
- Conciliação é manual (marcação), sem importação de extrato OFX.
- Sem multi-loja, sem multi-usuário simultâneo em rede (banco local de um computador).

## Licenciamento
- Chave assinada (Ed25519) validada offline para o ID da instalação. Qualquer verificação local pode ser burlada por quem editar o programa; o objetivo é conformidade, não anticópia.
- **Decisão comercial pendente:** o que acontece após os 30 dias de avaliação. Hoje: **nada é bloqueado**, só aparece o aviso (`ENFORCE_AFTER_EVAL = False`).

## Testes e plataforma
- Desenvolvido e testado em **Linux** (pytest + Qt offscreen + executável PyInstaller Linux com autoteste). **Nada foi executado em Windows**: o `.exe`, o instalador Inno Setup e o comportamento visual no Windows precisam de teste real (loja piloto) antes de vender.
- Executável não assinado digitalmente: o Windows SmartScreen/antivírus pode alertar. Recomenda-se certificado de assinatura de código.

## Pasta de dados

- Pasta de dados: as instalações novas usam `%LOCALAPPDATA%\StockPilot`. Se existir apenas a pasta antiga `StockPilotAI`, ela continua sendo usada, para não perder dados.

## Exclusão de produtos (v0.3.0)

- Só é possível excluir de vez um produto **sem histórico**, ou seja, sem movimentação de estoque, venda ou compra (inclusive rascunho).
- Um produto cadastrado com estoque inicial já tem uma movimentação. O livro de estoque é imutável e as vendas, compras e relatórios dependem desses registros. Por isso, nesses casos o sistema explica o motivo e oferece **Inativar**, que funciona como exclusão lógica: o produto sai das listas e da venda, e o histórico continua nos relatórios.
- Uma exclusão confirmada não pode ser desfeita, a não ser restaurando um backup.

## Gestão de estoque (v0.7.0)

- A reposição sugerida usa só o histórico de saídas do período escolhido e o estoque mínimo cadastrado; não considera sazonalidade, prazo de entrega do fornecedor nem lote mínimo de compra.
- "Parado" = com saldo e sem nenhuma movimentação há 90 dias (valor fixo).
- O valor do estoque usa o custo médio cadastrado; saldos negativos não entram no valor.
- A tela de Produtos exibe no máximo 500 linhas por consulta.
- Testado em Linux (182 testes + autoteste); nada novo foi executado no Windows.
