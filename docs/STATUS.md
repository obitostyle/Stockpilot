# Status das funcionalidades

Legenda: ✅ concluído e testado (Linux) · 🟡 parcial · ⏳ pendente · ⚠️ não testado em Windows

| Módulo | Status | Observações |
|---|---|---|
| Empresa (CNPJ numérico/alfanumérico, CNAE, regime) | ✅ | valida formato, não consulta a Receita |
| Produtos, estoque, movimentações imutáveis, estorno, CMP | ✅ | |
| Importação de produtos por planilha (tudo-ou-nada) e inventário em lote | ✅ | |
| Fornecedores | ✅ | |
| Compras (rascunho → confirmação idempotente, cancelamento) | ✅ | |
| Vendas/PDV (multi-pagamento, desconto com autorização, devolução, cancelamento, comprovante interno) | ✅ | sem emissão fiscal |
| Financeiro (contas, a pagar/receber, fluxo, conciliação manual, resultado estimado) | ✅ | |
| Painel com indicadores reais e gráfico | ✅ | |
| Tributário: MEI e Simples Anexo I (estimativa, histórico, obrigações, tabelas versionadas) | 🟡 | só comércio/Anexo I; 2027+ não implementado; Presumido/Real só dados |
| Funcionários, folha estimada, 13º/férias/rescisão | 🟡 | ver LIMITACOES.md (rescisão bruta; redutor Lei 15.270 em 13º/férias não verificado) |
| 15 relatórios (Excel e PDF) | ✅ | |
| Backup manual/automático, verificação SHA-256, restauração com cópia de segurança | ✅ | |
| Usuários, perfis (Admin/Gerente/Operador), login opcional | ✅ | |
| Licença offline (Ed25519), avaliação 30 dias | 🟡 | política pós-avaliação é decisão comercial |
| PyInstaller (Linux) com autoteste | ✅ | |
| Executável e instalador Windows (PyInstaller + Inno Setup) | ⚠️ | scripts prontos; **nunca executados em Windows** |
| Assinatura de código, atualização automática | ⏳ | |
| NFC-e/NF-e, eSocial, PGDAS-D | ⏳ | fora do escopo da v1 |
| Importação de extrato (OFX), multi-loja, rede | ⏳ | |

## Testes
`QT_QPA_PLATFORM=offscreen python -m pytest` — resultado na entrega (ver resumo). Cobrem validadores, estoque, compras, vendas, financeiro,
tributário (vetores: 5,65% p/ RBT12 360 mil; MEI 82,05), folha (INSS teto 988,09; redução 179,75), backup/restauração (inclui arquivo adulterado),
importação, licença, usuários, relatórios (15 × Excel/PDF) e fluxos de interface em Qt offscreen.
