# Política de retenção de dados (proposta técnica — valide com seu jurídico/contador)

| Dado | Retenção no sistema | Observação |
|---|---|---|
| Vendas, compras, lançamentos financeiros, movimentações de estoque | **Nunca apagados** (livros imutáveis por trigger no banco); correções por estorno | Obrigações fiscais/contábeis costumam exigir guarda de ~5 anos |
| Funcionários e folha estimada | Mantidos; desligamento não apaga o cadastro | Dados pessoais (LGPD): acesso só Admin/Gerente; guarde pelo prazo trabalhista/previdenciário aplicável |
| Estimativas tributárias | Mantidas (as substituídas ficam marcadas, não apagadas) | |
| Backups automáticos | 14 mais recentes (rotação automática) | Manuais e de segurança nunca são apagados pelo programa |
| Logs | Rotativos em `%LOCALAPPDATA%\StockPilot\logs` | Não registram senhas |
| Senhas | Hash scrypt com sal; nunca em texto | |

Exclusão de dados pessoais a pedido do titular (LGPD) conflita com obrigações de guarda: o sistema **não** tem "apagar funcionário/cliente".
Tratar caso a caso com o responsável jurídico. O backup contém todos os dados pessoais: proteja a pasta/mídia onde for copiado.
