/* Cartão de fidelidade: clique na frente para virar; movimento sutil no ponteiro. */
(() => {
  "use strict";
  const cena = document.getElementById("cartao-cena");
  const cartao = document.getElementById("cartao");
  if (!cena || !cartao) return;

  const botaoVirar = document.getElementById("virar-cartao");
  const frente = document.getElementById("cartao-frente");
  const verso = document.getElementById("cartao-verso");
  const reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const bloqueado = cena.classList.contains("bloqueado");
  const limitar = (v, min, max) => Math.min(max, Math.max(min, v));

  let alvoX = 0;      // inclinação (graus) para onde o cartão quer ir
  let alvoY = 0;
  let atualX = 0;     // inclinação atual (suavizada)
  let atualY = 0;
  let giro = 0;       // 0 = frente, 180 = verso
  let giroAtual = 0;
  let sobre = false;  // dedo/mouse em cima do cartão
  let giroscopio = false;

  // ---- laço de animação: aproxima o cartão do alvo e atualiza a iluminação
  const quadro = (t) => {
    if (!reduzido && !sobre && !giroscopio) {            // repouso: balanço bem leve, como no ar
      alvoY = Math.sin(t / 1900) * 1.5;
      alvoX = Math.cos(t / 2400) * 1;
    }
    atualX += (alvoX - atualX) * 0.12;
    atualY += (alvoY - atualY) * 0.12;
    giroAtual += (giro - giroAtual) * (reduzido ? 1 : 0.1);

    cartao.style.setProperty("--rx", `${atualX.toFixed(2)}deg`);
    cartao.style.setProperty("--ry", `${(atualY + giroAtual).toFixed(2)}deg`);
    cena.style.setProperty("--mx", `${(50 + atualY * 1.7).toFixed(1)}%`);   // reflexo segue a inclinação
    cena.style.setProperty("--my", `${(32 - atualX * 1.7).toFixed(1)}%`);
    cena.style.setProperty("--foil", `${(50 + atualY * 2.2).toFixed(1)}%`);
    cena.style.setProperty("--foilpos", `${(50 + atualY * 2.6).toFixed(1)}%`);
    cena.style.setProperty("--sx", `${(-atualY * 0.9).toFixed(1)}px`);       // sombra desliza no chão
    cena.style.setProperty("--sc", (1 - Math.abs(atualX) * 0.004).toFixed(3));
    requestAnimationFrame(quadro);
  };
  requestAnimationFrame(quadro);

  // ---- ponteiro (mouse, caneta e dedo)
  const mover = (e) => {
    if (reduzido) return;
    const r = cena.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    sobre = true;
    alvoY = limitar(x * 8, -4, 4);
    alvoX = limitar(-y * 8, -4, 4);
  };
  cena.addEventListener("pointermove", mover);
  cena.addEventListener("pointerdown", mover);
  const soltar = () => { sobre = false; };
  cena.addEventListener("pointerleave", soltar);
  cena.addEventListener("pointerup", () => setTimeout(soltar, 250));
  cena.addEventListener("pointercancel", soltar);

  // ---- virar o cartão por um controle separado, sem colocar botões dentro de outro botão
  const virar = () => {
    if (bloqueado || !botaoVirar || !frente || !verso) return;
    giro = giro === 0 ? 180 : 0;
    const versoVisivel = giro === 180;
    botaoVirar.setAttribute("aria-pressed", versoVisivel ? "true" : "false");
    botaoVirar.textContent = versoVisivel ? "Voltar à frente do cartão" : "Ver código para outro aparelho";
    frente.setAttribute("aria-hidden", versoVisivel ? "true" : "false");
    verso.setAttribute("aria-hidden", versoVisivel ? "false" : "true");
    frente.inert = versoVisivel;
    verso.inert = !versoVisivel;
    botaoVirar.focus();
  };
  if (botaoVirar) botaoVirar.addEventListener("click", virar);
  if (frente && verso && !bloqueado) {
    frente.addEventListener("click", virar);
    frente.addEventListener("keydown", (evento) => {
      if (evento.key === "Enter" || evento.key === " ") {
        evento.preventDefault();
        virar();
      }
    });
  }

  // ---- giroscópio (celular): o cartão acompanha a inclinação do aparelho
  const ouvirGiroscopio = () => {
    window.addEventListener("deviceorientation", (e) => {
      if (e.gamma === null || e.gamma === undefined || reduzido) return;
      giroscopio = true;
      alvoY = limitar(e.gamma, -25, 25) * 0.7;
      alvoX = limitar((e.beta || 0) - 40, -25, 25) * -0.7;
    });
  };
  const botaoMovimento = document.getElementById("ativar-movimento");
  if (typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function") {
    if (botaoMovimento) {          // iPhone: o navegador exige um toque para liberar o giroscópio
      botaoMovimento.hidden = false;
      botaoMovimento.addEventListener("click", async () => {
        try {
          if ((await DeviceOrientationEvent.requestPermission()) === "granted") {
            ouvirGiroscopio();
            botaoMovimento.hidden = true;
          }
        } catch (erro) { /* permissão negada: o cartão continua respondendo ao toque */ }
      });
    }
  } else if ("DeviceOrientationEvent" in window && window.matchMedia("(pointer: coarse)").matches) {
    ouvirGiroscopio();
  }

  // ---- pontos subindo até o saldo
  const valor = document.getElementById("cartao-pontos-valor");
  const total = parseInt(cena.dataset.pontos, 10);
  if (valor && !bloqueado && total > 0 && !reduzido) {
    const inicio = performance.now();
    const contar = (agora) => {
      const k = Math.min(1, (agora - inicio) / 900);
      valor.textContent = Math.round(total * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(contar);
    };
    valor.textContent = "0";
    requestAnimationFrame(contar);
  }

  // ---- código de recuperação: escondido até tocar em "Mostrar"
  const codigo = document.getElementById("codigo-rec");
  const mostrar = document.getElementById("mostrar-codigo");
  if (codigo && mostrar) {
    const mascara = codigo.textContent;
    mostrar.addEventListener("click", () => {
      const visivel = codigo.textContent !== mascara;
      codigo.textContent = visivel ? mascara : codigo.dataset.codigo;
      mostrar.textContent = visivel ? "Mostrar" : "Esconder";
    });
  }

  const formularioVinculo = document.getElementById("gerar-vinculo-form");
  const codigoVinculo = document.getElementById("codigo-vinculo");
  const estadoVinculo = document.getElementById("codigo-vinculo-status");
  if (formularioVinculo && codigoVinculo && estadoVinculo) {
    let temporizadorExpiracao;
    formularioVinculo.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const botao = formularioVinculo.querySelector('button[type="submit"]');
      const token = formularioVinculo.elements.csrfmiddlewaretoken.value;
      botao.disabled = true;
      codigoVinculo.hidden = true;
      codigoVinculo.textContent = "";
      estadoVinculo.textContent = "Gerando seu código seguro…";
      if (temporizadorExpiracao) window.clearTimeout(temporizadorExpiracao);

      try {
        const resposta = await fetch(formularioVinculo.action, {
          method: "POST",
          body: new FormData(formularioVinculo),
          credentials: "same-origin",
          headers: { "X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest" },
        });
        let dados;
        try {
          dados = await resposta.json();
        } catch (erro) {
          throw new Error("Não foi possível gerar o código. Atualize a página e tente novamente.");
        }
        if (!resposta.ok) throw new Error(dados.erro || "Não foi possível gerar o código.");

        codigoVinculo.textContent = dados.codigo;
        codigoVinculo.hidden = false;
        botao.textContent = "Gerar outro código";
        estadoVinculo.textContent = `Código de uso único. Válido por ${dados.validade_minutos} minutos.`;
        temporizadorExpiracao = window.setTimeout(() => {
          codigoVinculo.textContent = "";
          codigoVinculo.hidden = true;
          estadoVinculo.textContent = "Código expirado. Gere outro para vincular um aparelho.";
        }, dados.validade_minutos * 60 * 1000);
      } catch (erro) {
        estadoVinculo.textContent = erro.message || "Não foi possível gerar o código. Tente novamente.";
      } finally {
        botao.disabled = false;
      }
    });
  }

})();