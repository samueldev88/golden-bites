/* Previsão de entrega: mostra quanto falta (ou quanto atrasou) e os pontos de fidelidade do atraso.
   Usado na página do pedido (cliente) e no modo entregador. */
(() => {
  "use strict";
  const caixas = document.querySelectorAll("[data-prazo]");
  if (!caixas.length) return;

  const atualizar = () => {
    caixas.forEach((caixa) => {
      const prazo = new Date(caixa.dataset.prazo);
      const nota = caixa.querySelector(".prazo-nota");
      if (!nota || Number.isNaN(prazo.getTime())) return;
      const cliente = caixa.dataset.modo === "cliente";
      const faltam = Math.ceil((prazo - Date.now()) / 60000);
      if (faltam >= 0) {
        caixa.classList.remove("atrasado");
        nota.textContent = cliente
          ? `Faltam ${faltam} min. Se passar do horário, você ganha 1 ponto a cada 5 minutos de atraso.`
          : `Faltam ${faltam} min para o prazo.`;
      } else {
        const atraso = Math.floor((Date.now() - prazo) / 60000);
        const pontos = Math.floor(atraso / 5);
        const plural = pontos === 1 ? "" : "s";
        caixa.classList.add("atrasado");
        nota.textContent = cliente
          ? `Passou da previsão em ${atraso} min. Você já soma ${pontos} ponto${plural} de fidelidade, que entram quando o pedido for entregue.`
          : `Atrasado ${atraso} min. O cliente já soma ${pontos} ponto${plural}.`;
      }
    });
  };
  atualizar();
  setInterval(atualizar, 20000);
})();