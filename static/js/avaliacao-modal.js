(() => {
  "use strict";

  const dialogo = document.getElementById("modal-avaliacao");
  if (!dialogo) return;

  const abrir = document.querySelector("[data-abrir-avaliacao]");
  const fechar = dialogo.querySelector("[data-fechar-avaliacao]");

  if (typeof dialogo.showModal === "function" && dialogo.open) {
    dialogo.close();
    dialogo.showModal();
  }

  abrir?.addEventListener("click", () => {
    if (!dialogo.open && typeof dialogo.showModal === "function") dialogo.showModal();
  });
  fechar?.addEventListener("click", () => dialogo.close());
  dialogo.addEventListener("click", (evento) => {
    if (evento.target === dialogo) dialogo.close();
  });
})();
