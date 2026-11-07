# Assinatura digital do instalador (Windows)

O instalador do StockPilot **sai sem assinatura** até você ter um certificado de assinatura de código. Sem ele, o Windows mostra
"O Windows protegeu seu computador" (SmartScreen) e, com o *Controle de Aplicativo Inteligente* ligado, pode até bloquear a execução.
Eu não consigo comprar nem validar certificado por você: ele exige comprovação de identidade (CPF/CNPJ) e pagamento em seu nome.

## O que o build já faz
`build_windows.bat` assina **StockPilot.exe** e **o instalador** automaticamente quando as variáveis abaixo estão definidas.
Sem elas, gera o instalador normalmente e avisa que ele está sem assinatura.

```
set SIGN_PFX=C:\caminho\seu-certificado.pfx
set SIGN_PFX_PASSWORD=sua-senha
build_windows.bat
```
Precisa do `signtool.exe` (vem no *Windows SDK*, componente "Ferramentas de Assinatura"). A senha **não** é gravada em arquivo.

## Como obter o certificado
1. Compre um certificado de **assinatura de código** em uma autoridade certificadora (Sectigo, DigiCert, SSL.com e revendedores no Brasil). Ele pode ser OV (validação de organização) ou EV.
2. Faça a validação de identidade que a autoridade pedir. Em geral são alguns dias.
3. Receba o certificado em arquivo `.pfx` ou em token USB. **Token USB não funciona neste script** sem ajuste: use `.pfx`, ou peça a variação para o seu fornecedor.
4. Valores e regras mudam: cote antes. Há também o serviço da própria Microsoft (*Trusted Signing*), mas ele tem restrição de país e tipo de empresa; confira se você é elegível.

## O que esperar (honestamente)
- Assinar **remove o aviso de "editor desconhecido"** e ajuda o Controle de Aplicativo Inteligente a aceitar o programa.
- O SmartScreen também usa **reputação**. Mesmo assinado, um instalador novo pode mostrar o aviso nas primeiras semanas, até ganhar reputação com downloads. Isso varia por tipo de certificado.
- Até lá, mantenha na página de download as instruções com imagens: "Mais informações" → "Executar assim mesmo", e clicar com o botão direito no arquivo → Propriedades → "Desbloquear".

## Conferir
No Windows: botão direito no instalador → Propriedades → aba **Assinaturas Digitais**. Ela deve listar o seu certificado.
