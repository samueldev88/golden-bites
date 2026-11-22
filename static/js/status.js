/* Página do pedido: confere o status a cada poucos segundos e recarrega quando ele muda
   (pagamento aprovado, pedido em preparo, saiu para entrega...). Assim o cliente não precisa
   atualizar a página, e funciona sem webhook, até em localhost. */
(() => {
  "use strict";
  const url = window.STATUS_PEDIDO_URL;
  const inicial = window.STATUS_ATUAL;
  if (!url) return;

  let tentativas = 0;
  const conferir = async () => {
    tentativas += 1;
    try {
      const resp = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (resp.ok) {
        const dados = await resp.json();
        if (dados.status !== inicial) {
          if (inicial === "aguardando_pagamento" && dados.pago) {
            const destino = new URL(window.location.href);
            destino.searchParams.set("pagamento", "aprovado");
            window.location.assign(destino.href);
          } else {
            window.location.reload();
          }
          return;
        }
      }
    } catch (erro) { /* tenta de novo no próximo ciclo */ }
    if (tentativas < 800) setTimeout(conferir, tentativas < 20 ? 5000 : 15000);
  };
  setTimeout(conferir, 4000);
})();