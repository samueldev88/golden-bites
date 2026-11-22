/* Chat entre cliente e entregador (usado na página do pedido e no modo entregador).
   Atualiza sozinho a cada poucos segundos. */
(() => {
  "use strict";
  const raiz = document.getElementById("chat");
  if (!raiz) return;

  const urlLista = raiz.dataset.urlLista;
  const urlEnviar = raiz.dataset.urlEnviar;
  const eu = raiz.dataset.autor;
  const caixa = document.getElementById("chat-mensagens");
  const form = document.getElementById("chat-form");
  const campo = document.getElementById("chat-texto");
  const botao = document.getElementById("chat-enviar");
  const aviso = document.getElementById("chat-aviso");
  const tituloOriginal = document.title;
  const csrf = () => {
    const entrada = form.querySelector('[name="csrfmiddlewaretoken"]');
    return entrada ? entrada.value : "";
  };

  let ultimo = 0;
  let ativo = raiz.dataset.ativo === "1";
  let primeiraCarga = true;

  const mostrarVazio = () => {
    if (caixa.querySelector(".chat-bolha") || caixa.querySelector(".chat-vazio")) return;
    const p = document.createElement("p");
    p.className = "chat-vazio";
    p.textContent = raiz.dataset.vazio || "Nenhuma mensagem ainda.";
    caixa.appendChild(p);
  };

  const desenhar = (m) => {
    const vazio = caixa.querySelector(".chat-vazio");
    if (vazio) vazio.remove();
    const bolha = document.createElement("div");
    bolha.className = "chat-bolha " + (m.autor === eu ? "minha" : "outra");
    const texto = document.createElement("p");
    texto.textContent = m.texto; // textContent: nada de HTML vindo de outra pessoa
    const hora = document.createElement("small");
    hora.textContent = m.hora;
    bolha.append(texto, hora);
    caixa.appendChild(bolha);
  };

  const bip = () => {
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) return;
      const ctx = new Audio();
      const osc = ctx.createOscillator();
      const ganho = ctx.createGain();
      osc.frequency.value = 880;
      ganho.gain.value = 0.05;
      osc.connect(ganho);
      ganho.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.12);
      setTimeout(() => ctx.close(), 400);
    } catch (erro) { /* o navegador pode bloquear o som: tudo bem */ }
  };

  const mostrarAviso = (texto, tipo) => {
    aviso.textContent = texto;
    aviso.dataset.tipo = tipo;
    aviso.hidden = false;
  };

  const definirEstado = () => {
    campo.disabled = !ativo;
    botao.disabled = !ativo;
    if (!ativo) {
      mostrarAviso("O chat fica aberto enquanto o pedido está em andamento.", "inativo");
    } else if (aviso.dataset.tipo === "inativo") {
      aviso.hidden = true;
    }
  };

  const buscar = async () => {
    try {
      const resp = await fetch(`${urlLista}?depois=${ultimo}`, { credentials: "same-origin" });
      if (!resp.ok) return;
      const dados = await resp.json();
      ativo = dados.ativo;
      const estavaNoFim = caixa.scrollHeight - caixa.scrollTop - caixa.clientHeight < 60;
      dados.mensagens.forEach((m) => {
        desenhar(m);
        ultimo = Math.max(ultimo, m.id);
      });
      if (dados.mensagens.length) {
        if (estavaNoFim || primeiraCarga) caixa.scrollTop = caixa.scrollHeight;
        const recebeu = dados.mensagens.some((m) => m.autor !== eu);
        if (recebeu && !primeiraCarga) {
          bip();
          if (document.hidden) document.title = "(nova mensagem) " + tituloOriginal;
        }
      } else if (primeiraCarga) {
        mostrarVazio();
      }
      primeiraCarga = false;
      definirEstado();
    } catch (erro) { /* sem rede: tenta de novo no próximo ciclo */ }
  };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const texto = campo.value.trim();
    if (!texto || !ativo) return;
    botao.disabled = true;
    try {
      const resp = await fetch(urlEnviar, {
        method: "POST",
        body: new URLSearchParams({ texto }),
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
      });
      const dados = await resp.json().catch(() => ({}));
      if (!resp.ok || !dados.ok) {
        mostrarAviso(dados.erro || "Não foi possível enviar agora. Tente de novo.", "erro");
      } else {
        campo.value = "";
        aviso.hidden = true;
        await buscar();
      }
    } catch (erro) {
      mostrarAviso("Sem conexão. Tente de novo.", "erro");
    }
    botao.disabled = !ativo;
    campo.focus();
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) document.title = tituloOriginal;
  });

  const ciclo = async () => {
    await buscar();
    setTimeout(ciclo, document.hidden ? 15000 : 4000);
  };
  ciclo();
})();