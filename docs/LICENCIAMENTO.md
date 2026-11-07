> **Desligado.** Desde 06/11/2026 o StockPilot é vendido sem ativação por licença (`LICENSING_ENABLED = False`). Este documento descreve o mecanismo que continua no código, caso a decisão mude.

# Licenciamento (pagamento único, offline)

**Como funciona:** o cliente abre *Configurações → Licença*, copia o **ID da instalação** (`SP-XXXX-XXXX-XXXX-XXXX`) e envia a você.
Você emite uma chave assinada para esse ID e ele a cola na tela. O programa confere a assinatura Ed25519 com a **chave pública** embutida.
Sem internet, sem servidor.

## Emitir uma licença (no SEU computador, nunca no do cliente)
```
python tools/license_tool.py issue --key CHAVE_PRIVADA_DO_FABRICANTE.pem --id SP-XXXX-XXXX-XXXX-XXXX --customer "Mercado Exemplo"
```
Imprime a chave para enviar ao cliente. Para conferir: `python tools/license_tool.py check --id SP-... --license "<chave>"`.

## Sobre a chave privada
Foi gerado um par de chaves para este projeto. A **pública** já está em `src/stockpilot/licensing/public_key.py`.
A **privada** (`CHAVE_PRIVADA_DO_FABRICANTE.pem`) vem **em arquivo separado, fora do projeto**: guarde-a em local seguro (cofre de senhas, pen drive offline),
**não a coloque no repositório nem no instalador**. Se vazar, qualquer um emite licenças. Para trocar o par antes de vender:
`python tools/license_tool.py gen-keys` (grava a nova pública no código e cria a nova privada; recompile).
Licenças emitidas com a chave antiga deixam de valer após a troca — faça isso **antes** da primeira venda.

## Reinstalação / troca de computador
O ID fica no banco de dados. Reinstalar o programa mantém o ID (os dados ficam em `%LOCALAPPDATA%\StockPilot`). Se o cliente formatar o PC sem backup
ou migrar de computador sem restaurar o banco, o ID muda: emita nova chave manualmente (política comercial sua).

## Comportamento
Sem licença: **modo de avaliação de 30 dias**, tudo liberado, aviso na barra de status. Depois: aviso continua; **nada é bloqueado** e os dados nunca ficam inacessíveis.
Para decidir bloquear funções após a avaliação é preciso uma decisão comercial (e implementação) — hoje `ENFORCE_AFTER_EVAL = False`.
