/* Modo entregador (celular): envia a localização do GPS para o cliente acompanhar no mapa. */
(() => {
  "use strict";
  const raiz = document.getElementById("entregador");
  const botao = document.getElementById("compartilhar");
  const estado = document.getElementById("estado-gps");
  if (!raiz || !botao) return;

  const url = raiz.dataset.urlPosicao;
  const csrf = () => ((raiz.querySelector('[name="csrfmiddlewaretoken"]') || {}).value || "");
  let observador = null;
  let ultimoEnvio = 0;
  let tela = null;

  const enviar = async (pos) => {
    const agora = Date.now();
    if (agora - ultimoEnvio < 4000) return; // no máximo uma atualização a cada 4 s
    ultimoEnvio = agora;
    try {
      const resp = await fetch(url, {
        method: "POST",
        body: new URLSearchParams({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf() },
      });
      estado.textContent = resp.ok
        ? `Localização enviada às ${new Date().toLocaleTimeString("pt-BR")}. O cliente está vendo você no mapa.`
        : `Não consegui enviar a localização (erro ${resp.status}).`;
    } catch (erro) {
      estado.textContent = "Sem conexão. Tentando de novo…";
      ultimoEnvio = 0;
    }
  };

  const parar = () => {
    if (observador !== null) navigator.geolocation.clearWatch(observador);
    observador = null;
    botao.textContent = "Compartilhar minha localização";
    if (tela) { tela.release().catch(() => {}); tela = null; }
  };

  const falhou = (erro) => {
    estado.textContent = erro.code === 1
      ? "Permissão negada. Libere a localização do navegador para este site."
      : "Não consegui pegar o GPS. Confira se a localização do aparelho está ligada.";
    parar();
  };

  const manterTelaLigada = async () => {
    try {
      if ("wakeLock" in navigator) tela = await navigator.wakeLock.request("screen");
    } catch (erro) { /* sem suporte: tudo bem */ }
  };

  const iniciar = () => {
    if (!navigator.geolocation) {
      estado.textContent = "Este aparelho não permite usar a localização.";
      return;
    }
    estado.textContent = "Buscando o GPS…";
    observador = navigator.geolocation.watchPosition(enviar, falhou, {
      enableHighAccuracy: true, maximumAge: 2000, timeout: 20000,
    });
    botao.textContent = "Parar de compartilhar";
    manterTelaLigada();
  };

  botao.addEventListener("click", () => (observador === null ? iniciar() : parar()));

  // ao voltar para a tela, pede de novo para ela não apagar
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && observador !== null && !tela) manterTelaLigada();
  });

  // se a permissão já foi dada antes, começa sozinho
  if (raiz.dataset.ativo === "1" && navigator.permissions && navigator.permissions.query) {
    navigator.permissions.query({ name: "geolocation" })
      .then((p) => { if (p.state === "granted") iniciar(); })
      .catch(() => {});
  }

  // confirmação da entrega com o código de 4 dígitos do cliente
  const bloco = document.getElementById("confirmar-entrega");
  if (bloco) {
    const campo = document.getElementById("codigo-entrega");
    const mensagem = document.getElementById("codigo-msg");
    const botaoConfirmar = document.getElementById("confirmar");
    let enviando = false;

    const confirmar = async () => {
      const digitos = campo.value.replace(/\D/g, "");
      if (digitos.length !== 4 || enviando) return;
      enviando = true;
      botaoConfirmar.disabled = true;
      mensagem.textContent = "Conferindo o código…";
      try {
        const resp = await fetch(bloco.dataset.url, {
          method: "POST",
          body: new URLSearchParams({ codigo: digitos }),
          credentials: "same-origin",
          headers: { "X-CSRFToken": csrf() },
        });
        const dados = await resp.json().catch(() => ({}));
        if (resp.ok && dados.ok) {
          mensagem.textContent = "Entrega confirmada! Obrigado.";
          mensagem.className = "p-nota ok";
          parar();
          setTimeout(() => window.location.reload(), 1200);
          return;
        }
        mensagem.textContent = dados.erro || "Não foi possível confirmar agora.";
        mensagem.className = "p-nota erro";
        campo.value = "";
        campo.focus();
      } catch (erro) {
        mensagem.textContent = "Sem conexão. Tente de novo.";
      }
      enviando = false;
      botaoConfirmar.disabled = false;
    };

    campo.addEventListener("input", () => {
      campo.value = campo.value.replace(/\D/g, "").slice(0, 4);
      if (campo.value.length === 4) confirmar(); // facilita: confirma ao digitar o 4º número
    });
    campo.addEventListener("keydown", (e) => { if (e.key === "Enter") confirmar(); });
    botaoConfirmar.addEventListener("click", confirmar);
  }
})();