# Manual rápido do StockPilot

1. **Empresa** — cadastre razão social, CNPJ, regime (MEI/Simples) e data de início da atividade (necessária para as estimativas).
2. **Produtos** — cadastre um a um ou **Importar planilha** (baixe o modelo). Estoque inicial vira uma entrada no histórico.
3. **Fornecedores → Compras** — crie a compra (rascunho), confira e **confirme**: só então o estoque sobe e o financeiro é lançado (uma única vez). Compra a prazo gera *contas a pagar*.
4. **Vendas (PDV)** — leia o código de barras ou busque pelo nome, ajuste quantidade/desconto, **F2** para finalizar, escolha as formas de pagamento (pode misturar). Desconto acima do limite exige gerente/admin. O comprovante é **interno, sem valor fiscal**. Em *Histórico*: reimprimir comprovante, devolução, cancelamento (estorna estoque e caixa).
5. **Financeiro** — resumo (resultado **estimado**), contas a pagar/receber (dar baixa, estornar baixa), fluxo de caixa, lançamentos manuais, contas e categorias.
6. **Tributário** — informe o faturamento dos meses sem vendas no sistema, escolha a competência e *Calcular estimativa*. Leia os avisos e os **dados que faltam**. Confirme sempre com o PGDAS-D/PGMEI e o contador.
7. **Funcionários** — cadastro, benefícios, folha do mês estimada, simulações de 13º/férias/rescisão. Dados sensíveis: só Admin/Gerente.
8. **Relatórios** — 15 relatórios com filtros; exporte em Excel ou PDF.
9. **Backup** — faça backup manual, mantenha o automático ligado e **copie a pasta de backups para um pen drive/nuvem**. Restaurar substitui os dados atuais (guarda cópia de segurança antes).
10. **Configurações** (Admin) — desconto máximo, estoque negativo, RAT/terceiros, usuários/login e licença.

## Leitor de código de barras

O StockPilot funciona com leitores USB comuns que "digitam" o código como um teclado (modo HID). Não é preciso instalar nada: basta conectar o leitor. A maioria já vem de fábrica enviando **Enter** no final da leitura, que é o padrão recomendado. O envio de **Tab** no final também é aceito.

- **Produtos**:
  - Leia o produto com o foco em qualquer ponto da tela.
  - Se ele existir, a linha fica selecionada e aparece "Produto encontrado", com o estoque atual. Use **Entrada** ou **Editar** para atualizar.
  - Se não existir, aparece "Código … não cadastrado" e o botão **Cadastrar com este código**, que abre o cadastro já preenchido.
- **Cadastro de produto**:
  - A leitura preenche o campo Código de barras mesmo que o cursor esteja em outro campo.
  - O Enter do leitor **não salva** o cadastro.
  - O sistema avisa na hora se o código já pertence a outro produto, porque um código não pode se repetir.
  - Produtos sem código de barras continuam podendo ser cadastrados.
- **Vendas (PDV)**:
  - Leituras seguidas somam a quantidade no carrinho.
  - Um código não cadastrado mostra um aviso e **não** adiciona um produto parecido.
- **Compras**: a leitura escolhe o produto da linha da compra.
- **Estoque**:
  - A leitura filtra o histórico daquele produto.
  - Em seguida, Entrada, Saída, Ajuste e Inventário já abrem com o produto escolhido.
- **Entrada, saída e ajuste**: a leitura escolhe o produto e leva o cursor direto para a quantidade.

Como o sistema distingue o leitor da digitação: o leitor envia as teclas com poucos milissegundos de intervalo, enquanto uma pessoa digita muito mais devagar. Se o seu leitor não envia Enter nem Tab no final, configure-o pelo manual do aparelho, normalmente lendo um código de configuração ("Add CR suffix").

## Gestão de estoque (v0.7.0)

- **Situação do estoque** (topo da tela Estoque): valor em estoque a custo, produtos abaixo do mínimo, sem saldo e parados há 90+ dias.
- **Em lote** (Entrada, Saída ou Inventário): leia os códigos com o leitor (cada leitura soma 1) ou busque pelo nome, ajuste as quantidades na tabela e lance tudo de uma vez. Se algum item der erro, nada é gravado. Reenviar o mesmo lote não duplica.
- **Reposição sugerida**: lista o que comprar e quanto, com o motivo (sem saldo, abaixo do mínimo ou pouca cobertura). Os critérios aparecem na própria tela. Dá para editar as quantidades, exportar para Excel ou dar entrada direto. É uma sugestão: confira antes de comprar.
- **Proteção contra repetição**: lançar entrada/saída idêntica logo após outra pede confirmação; o clique duplo no botão não grava duas vezes.
- **Produtos**: a lista mostra até 500 linhas (com aviso do total); use a busca, o leitor ou os filtros "Estoque baixo" e "Sem saldo" para achar o restante.
- **Relatórios → Giro e reposição de estoque**: saídas, média diária e cobertura por produto no período.
