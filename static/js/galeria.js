/* Golden Bites · interações da loja (JavaScript simples, sem dependências) */
(() => {
  "use strict";

  const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
  const $$ = (seletor, raiz = document) => Array.from(raiz.querySelectorAll(seletor));
  const moeda = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const csrf = () => (($('meta[name="csrf-token"]') || {}).content || "");

  const lembrado = () => {
    try { return JSON.parse(localStorage.getItem("mt_cliente") || "{}"); } catch (erro) { return {}; }
  };

  function mascararTelefone(campo) {
    campo.addEventListener("input", () => {
      const d = campo.value.replace(/\D/g, "").slice(0, 11);
      const corte = d.length > 10 ? 7 : 6;
      if (d.length > 6) campo.value = `(${d.slice(0, 2)}) ${d.slice(2, corte)}-${d.slice(corte)}`;
      else if (d.length > 2) campo.value = `(${d.slice(0, 2)}) ${d.slice(2)}`;
      else campo.value = d;
    });
  }

  /* ---------- avisos ---------- */
  function sumir(el, ms) {
    setTimeout(() => {
      el.classList.add("saindo");
      setTimeout(() => el.remove(), 400);
    }, ms);
  }
  function aviso(texto, tipo = "") {
    const caixa = $("#toasts");
    if (!caixa) return;
    const el = document.createElement("p");
    el.className = "toast " + tipo;
    el.textContent = texto;
    caixa.appendChild(el);
    sumir(el, 3200);
  }
  $$("#toasts .toast").forEach((el) => sumir(el, 4500));

  /* ---------- carrinho: botão redondo (só aparece com itens) ---------- */
  function atualizarCarrinho(qtd) {
    $$(".fab-carrinho").forEach((fab) => {
      fab.hidden = !qtd; // ao aparecer, o CSS faz a entrada animada
      fab.setAttribute("aria-label", `Abrir carrinho, ${qtd} item(ns)`);
    });
    $$(".fab-qtd").forEach((b) => {
      b.textContent = qtd;
      b.classList.remove("pulso");
      void b.offsetWidth; // reinicia a animação
      b.classList.add("pulso");
    });
  }

  /* ---------- "Adicionar" -> controle de quantidade (− 1 +) só depois do clique ---------- */
  const postar = async (url, dados) => {
    const resp = await fetch(url, {
      method: "POST",
      body: new URLSearchParams(dados),
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf() },
    });
    if (!resp.ok) throw new Error("erro " + resp.status);
    return resp.json();
  };

  // mostra o botão "Adicionar" (quantidade 0) ou o controle de quantidade (1 ou mais)
  const pintarQuantidade = (caixa, qtd) => {
    caixa.dataset.qtd = qtd;
    const adicionar = $(".comprar-adicionar", caixa);
    const passos = $(".stepper", caixa);
    adicionar.hidden = qtd > 0;
    passos.hidden = qtd <= 0;
    $("output", passos).textContent = qtd;
    $('[data-passo="1"]', passos).disabled = qtd >= 99;
  };

  document.addEventListener("submit", async (e) => {
    const form = e.target.closest(".comprar-adicionar");
    if (!form) return;
    e.preventDefault();
    const caixa = form.closest("[data-comprar]");
    const botao = $(".btn-add", form);
    botao.disabled = true;
    try {
      const dados = await postar(caixa.dataset.urlAdicionar, { quantidade: 1 });
      pintarQuantidade(caixa, dados.quantidade);
      atualizarCarrinho(dados.quantidade_total);
    } catch (erro) {
      botao.disabled = false;
      form.submit(); // sem JavaScript funcionando, envia o formulário do jeito tradicional
      return;
    }
    botao.disabled = false;
  });

  document.addEventListener("click", async (e) => {
    const botao = e.target.closest("[data-comprar] .stepper button[data-passo]");
    if (!botao) return;
    const caixa = botao.closest("[data-comprar]");
    const nova = Math.max(0, Math.min(99, (parseInt(caixa.dataset.qtd, 10) || 0) + parseInt(botao.dataset.passo, 10)));
    const botoes = caixa.querySelectorAll(".stepper button");
    botoes.forEach((b) => { b.disabled = true; });
    try {
      const dados = await postar(caixa.dataset.urlAtualizar, { quantidade: nova });
      botoes.forEach((b) => { b.disabled = false; });
      pintarQuantidade(caixa, dados.quantidade);
      atualizarCarrinho(dados.quantidade_total);
    } catch (erro) {
      botoes.forEach((b) => { b.disabled = false; });
      aviso("Não foi possível atualizar agora. Tente de novo.", "error");
    }
  });

  /* ---------- catálogo: busca e categorias ---------- */
  const grade = $("#grade");
  if (grade) {
    const busca = $("#busca");
    const chips = $$(".chip");
    const vazio = $("#sem-resultado");
    let categoria = "";
    const normalizar = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

    const filtrar = () => {
      const termo = normalizar(busca.value.trim());
      let visiveis = 0;
      $$(".produto", grade).forEach((card) => {
        const ok = (!categoria || card.dataset.categoria === categoria) &&
                   (!termo || normalizar(card.dataset.nome).includes(termo));
        card.hidden = !ok;
        if (ok) visiveis += 1;
      });
      vazio.hidden = visiveis > 0;
    };

    chips.forEach((chip) => chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.remove("ativo"));
      chip.classList.add("ativo");
      categoria = chip.dataset.filtro;
      filtrar();
    }));
    busca.addEventListener("input", filtrar);
  }

  /* ---------- folha "Como você quer receber?" ---------- */
  $$("[data-abrir]").forEach((botao) => botao.addEventListener("click", () => {
    const dialogo = document.getElementById(botao.dataset.abrir);
    if (dialogo && dialogo.showModal) dialogo.showModal();
  }));
  $$("dialog").forEach((dialogo) => dialogo.addEventListener("click", (e) => {
    if (e.target === dialogo || e.target.closest("[data-fechar]")) dialogo.close();
  }));

  /* ---------- finalização do pedido ---------- */
  const form = $("#form-checkout");
  if (form) {
    const subtotal = parseFloat(form.dataset.subtotal) || 0;
    const resTaxa = $("#res-taxa");
    const resTotal = $("#res-total");
    const linhaDesconto = $("#linha-desconto");
    const resDesconto = $("#res-desconto");
    const nota = $("#res-nota");
    const enviar = $("#enviar");
    const cupomCampo = form.elements["cupom"];
    const cupomMsg = $("#cupom-msg");
    const telefone = form.elements["telefone"];
    const cep = form.elements["cep"];
    const botaoRota = $("#calcular-rota");
    const avisoCep = $("#cep-aviso");
    const resumoRota = $("#rota-resumo");
    const avisoNumero = $("#aviso-numero");
    const pinLat = form.elements["pin_lat"];
    const pinLon = form.elements["pin_lon"];
    const botaoGps = $("#usar-localizacao");
    const statusGps = $("#gps-status");
    const textoGpsPadrao = statusGps.textContent;
    let cepDoPin = "";
    const limparPin = () => {
      pinLat.value = "";
      pinLon.value = "";
      cepDoPin = "";
      statusGps.textContent = textoGpsPadrao;
    };
    const radioRapida = form.querySelector('input[name="modalidade"][value="rapida"]');
    const radioAgendada = form.querySelector('input[name="modalidade"][value="agendada"]');
    let desconto = 0;
    let local = null;        // resultado do cálculo (zona, taxa, rota...)
    let calculando = false;
    let liberarEnvio = false; // permite enviar sem rota quando o cálculo está indisponível

    const modalidade = () => form.querySelector('input[name="modalidade"]:checked').value;
    const digitosCep = () => cep.value.replace(/\D/g, "");
    const kmTexto = (km) => km.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " km";
    const taxaTexto = (t) => (t === null || t === undefined ? "A consultar" : t === 0 ? "Grátis" : moeda(t));

    const estadoTaxa = () => {
      if (!local) return { tipo: "vazio" };
      if (local.zona === "fora" || local.zona === "invalido") return { tipo: "fora" };
      if (local.taxa === null || local.taxa === undefined) return { tipo: "consultar" };
      return { tipo: "valor", valor: local.taxa };
    };

    const atualizar = () => {
      const modo = modalidade();
      $$("[data-modo]", form).forEach((bloco) => { bloco.hidden = bloco.dataset.modo !== modo; });

      const estado = estadoTaxa();
      let taxa = 0;
      if (estado.tipo === "valor") {
        taxa = estado.valor;
        resTaxa.textContent = taxaTexto(taxa);
      } else {
        resTaxa.textContent = { vazio: "Calcule a entrega", fora: "Indisponível", consultar: "A consultar" }[estado.tipo];
      }

      linhaDesconto.hidden = !(desconto > 0);
      resDesconto.textContent = "-" + moeda(desconto);
      resTotal.textContent = moeda(Math.max(0, subtotal + taxa - desconto));

      const consultar = estado.tipo === "consultar";
      nota.hidden = !consultar;
      enviar.disabled = estado.tipo === "fora";
      enviar.textContent = consultar ? "Enviar pedido para confirmação" : "Ir para o pagamento";
    };

    const atualizarBotao = () => {
      botaoRota.disabled = calculando || digitosCep().length !== 8;
      botaoRota.textContent = calculando ? "Calculando rota…" : (local ? "Recalcular" : "Calcular entrega");
    };

    /* rua e bairro preenchidos pelo CEP são trocados quando o CEP muda; o que o cliente digita fica */
    const camposAuto = ["rua", "bairro"].map((n) => form.elements[n]);
    camposAuto.forEach((c) => c.addEventListener("input", () => { c.dataset.auto = ""; }));
    const preencher = (nome, valor) => {
      const campo = form.elements[nome];
      if (!valor || (campo.value && campo.dataset.auto !== "1")) return;
      campo.value = valor;
      campo.dataset.auto = "1";
    };
    const limparPreenchidos = () => camposAuto.forEach((c) => {
      if (c.dataset.auto === "1") { c.value = ""; c.dataset.auto = ""; }
    });
    const limparErrosCep = () => {
      const campo = cep.closest(".campo");
      campo.classList.remove("tem-erro");
      $$(".erro", campo).forEach((e) => e.remove());
      const erroModalidade = $("#erro-modalidade");
      if (erroModalidade) erroModalidade.innerHTML = "";
    };

    // nome da rua na hora: ViaCEP direto do navegador, assim que o CEP está completo
    const preencherEndereco = async (digitos) => {
      try {
        const resp = await fetch(`https://viacep.com.br/ws/${digitos}/json/`);
        const dados = await resp.json();
        if (digitosCep() !== digitos || dados.erro) return;
        preencher("rua", dados.logradouro);
        preencher("bairro", dados.bairro);
        if (document.activeElement === cep && form.elements["rua"].value && !form.elements["numero"].value) {
          form.elements["numero"].focus(); // próximo passo natural: o número
        }
      } catch (erro) { /* o cálculo da entrega também preenche */ }
    };

    const mostrarLocal = () => {
      if (!local) {
        resumoRota.hidden = true;
        avisoNumero.hidden = true;
        radioRapida.disabled = false;
        radioAgendada.disabled = false;
        atualizar();
        atualizarBotao();
        return;
      }
      const classes = { rapida: "ok", agendada: "info", desconhecida: "info", fora: "erro", invalido: "erro" };
      avisoCep.hidden = false;
      avisoCep.className = "aviso-cep " + (classes[local.zona] || "info");
      avisoCep.textContent = local.mensagem + (local.detalhe ? ` (detalhe técnico: ${local.detalhe})` : "");

      if (local.encontrado) {
        preencher("rua", local.rua);
        preencher("bairro", local.bairro);
      }

      const semEntrega = local.zona === "fora" || local.zona === "invalido";
      radioRapida.disabled = semEntrega || local.zona === "agendada";
      radioAgendada.disabled = semEntrega;
      if (radioRapida.disabled && radioRapida.checked && !radioAgendada.disabled) radioAgendada.checked = true;

      if (local.rota_km !== null && local.rota_km !== undefined) {
        resumoRota.hidden = false;
        const enderecoReconhecido = [local.rua, local.bairro].filter(Boolean).join(" — ");
        $("#rota-endereco-linha").hidden = !enderecoReconhecido;
        $("#rota-endereco").textContent = enderecoReconhecido;
        $("#rota-km").textContent = kmTexto(local.rota_km) + (local.rota_aproximada ? " (estimada)" : "");
        const mostrarTempo = local.zona === "rapida" && local.rota_minutos;
        $("#rota-tempo-linha").hidden = !mostrarTempo;
        if (mostrarTempo) $("#rota-tempo").textContent = `cerca de ${local.rota_minutos} min`;
        const previsao = local.zona === "rapida" && local.previsao_hora;
        $("#rota-previsao-linha").hidden = !previsao;
        const avisoAtraso = $("#rota-atraso");
        if (avisoAtraso) avisoAtraso.hidden = !previsao;
        if (previsao) $("#rota-previsao").textContent = `hoje, às ${local.previsao_hora} (cerca de ${local.previsao_min} min)`;
        $("#rota-taxa").textContent = taxaTexto(local.taxa);
      } else {
        resumoRota.hidden = true;
      }
      avisoNumero.hidden = !local.numero_nao_encontrado;
      atualizar();
      atualizarBotao();
    };

    const limparResultado = () => {
      if (!local && avisoCep.hidden) return;
      local = null;
      avisoCep.hidden = true;
      limparErrosCep();
      mostrarLocal();
    };

    // o botão "Calcular entrega": rota, distância, tempo e taxa
    const calcularRota = async () => {
      const digitos = digitosCep();
      if (digitos.length !== 8 || calculando) return false;
      calculando = true;
      limparErrosCep();
      resumoRota.hidden = true;
      avisoCep.hidden = false;
      avisoCep.className = "aviso-cep info";
      avisoCep.textContent = "Calculando a rota até você…";
      atualizarBotao();
      try {
        const params = new URLSearchParams({
          cep: digitos, bairro: form.elements["bairro"].value, numero: form.elements["numero"].value,
        });
        if (pinLat.value && pinLon.value) {
          params.set("lat", pinLat.value);
          params.set("lon", pinLon.value);
        }
        const resp = await fetch(form.dataset.urlCep + "?" + params);
        if (!resp.ok) throw new Error("erro " + resp.status);
        const dados = await resp.json();
        local = digitosCep() === digitos ? dados : null; // se o CEP mudou no meio, descarta
        if (local) cep.dataset.calculado = digitos;
      } catch (erro) {
        local = null;
        avisoCep.className = "aviso-cep info";
        avisoCep.textContent = `Não conseguimos calcular agora (${erro.message}). Tente de novo ou envie o pedido: confirmamos a entrega pelo WhatsApp.`;
        calculando = false;
        atualizarBotao();
        return false;
      }
      calculando = false;
      mostrarLocal();
      return !!local;
    };

    const aplicarCupom = async (silencioso) => {
      const codigo = cupomCampo.value.trim();
      if (!codigo) {
        desconto = 0;
        cupomMsg.textContent = "";
        atualizar();
        return;
      }
      const estado = estadoTaxa();
      const params = new URLSearchParams({ codigo });
      if (estado.tipo === "valor") params.set("taxa", estado.valor.toFixed(2));
      try {
        const resp = await fetch(form.dataset.urlCupom + "?" + params, { headers: { "X-Requested-With": "XMLHttpRequest" } });
        const dados = await resp.json();
        desconto = dados.ok ? dados.desconto : 0;
        cupomMsg.textContent = dados.ok && dados.frete_gratis && estado.tipo !== "valor"
          ? "Frete grátis: o desconto entra quando a taxa de entrega for confirmada."
          : dados.mensagem;
        cupomMsg.className = "ajuda " + (dados.ok ? "ok" : "erro");
      } catch (erro) {
        if (!silencioso) cupomMsg.textContent = "Não foi possível verificar o cupom agora.";
      }
      atualizar();
    };

    form.addEventListener("change", (e) => {
      if (e.target.matches('[name="modalidade"]')) {
        atualizar();
        if (cupomCampo.value.trim()) aplicarCupom(true);
      }
      // número ou bairro mudou depois do cálculo: refaz a rota com o endereço mais preciso
      if ((e.target === form.elements["numero"] || e.target === form.elements["bairro"]) &&
          local && local.zona !== "invalido" && !calculando) {
        calcularRota().then(() => { if (cupomCampo.value.trim()) aplicarCupom(true); });
      }
    });
    $("#aplicar-cupom").addEventListener("click", () => aplicarCupom(false));
    cupomCampo.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); aplicarCupom(false); }
    });
    botaoRota.addEventListener("click", async () => {
      await calcularRota();
      if (cupomCampo.value.trim()) aplicarCupom(true);
    });

    // dados lembrados neste aparelho (sem conta): o próximo pedido já vem preenchido
    const MEMORIA = ["nome", "sobrenome", "telefone", "cep", "rua", "numero", "complemento", "bairro", "referencia"];
    const salvo = lembrado();
    MEMORIA.forEach((n) => {
      const campo = form.elements[n];
      if (campo && !campo.value && salvo[n]) campo.value = salvo[n];
    });
    if (cep.value && salvo.cep === cep.value) camposAuto.forEach((c) => { if (c.value) c.dataset.auto = "1"; });

    mascararTelefone(telefone);

    // "Usar minha localização": GPS do cliente preenche rua, número e bairro e fixa o ponto da entrega
    botaoGps.addEventListener("click", () => {
      if (!navigator.geolocation) {
        statusGps.textContent = "Este aparelho não permite usar a localização.";
        return;
      }
      botaoGps.disabled = true;
      statusGps.textContent = "Buscando a sua localização…";
      navigator.geolocation.getCurrentPosition(async (pos) => {
        const { latitude, longitude } = pos.coords;
        try {
          const resp = await fetch(`${form.dataset.urlLocalizacao}?lat=${latitude}&lon=${longitude}`);
          if (!resp.ok) throw new Error("erro " + resp.status);
          const d = await resp.json();
          const colocar = (nome, valor) => {
            if (!valor) return;
            const campo = form.elements[nome];
            campo.value = valor;
            campo.dataset.auto = "1";
          };
          colocar("rua", d.rua);
          colocar("numero", d.numero);
          colocar("bairro", d.bairro);
          if (d.cep && d.cep.length === 8) {
            cep.value = `${d.cep.slice(0, 5)}-${d.cep.slice(5)}`;
            cep.dataset.endereco = d.cep;
          }
          pinLat.value = latitude;
          pinLon.value = longitude;
          cepDoPin = digitosCep();
          statusGps.textContent = d.rua
            ? "Localização confirmada. Confira a rua e o número abaixo."
            : "Localização salva. Preencha a rua e o número abaixo.";
          atualizarBotao();
          if (digitosCep().length === 8) {
            delete cep.dataset.calculado;
            await calcularRota();
          } else {
            statusGps.textContent += " Digite também o CEP para calcular a entrega.";
          }
        } catch (erro) {
          limparPin();
          statusGps.textContent = "Não conseguimos montar o endereço pela localização. Digite o CEP e o número.";
        }
        botaoGps.disabled = false;
      }, (erro) => {
        statusGps.textContent = erro.code === 1
          ? "Permissão negada. Libere a localização do navegador para este site."
          : "Não foi possível pegar a localização agora.";
        botaoGps.disabled = false;
      }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
    });

    // CEP: máscara, rua na hora e limpeza do resultado anterior ao mudar
    cep.addEventListener("input", () => {
      const d = digitosCep().slice(0, 8);
      cep.value = d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d;
      if (pinLat.value) {
        // o ponto do GPS vale para o CEP em que foi tirado; outro CEP, outro ponto
        if (!cepDoPin && d.length === 8) cepDoPin = d;
        else if (cepDoPin && d !== cepDoPin) limparPin();
      }
      if (cep.dataset.calculado !== d) {
        delete cep.dataset.calculado;
        limparErrosCep();
        limparResultado();
      }
      if (d.length === 8) {
        if (cep.dataset.endereco !== d) { limparPreenchidos(); preencherEndereco(d); }
        cep.dataset.endereco = d;
      } else {
        delete cep.dataset.endereco;
      }
      atualizarBotao();
    });

    form.addEventListener("submit", async (e) => {
      if (local && (local.zona === "fora" || local.zona === "invalido")) {
        e.preventDefault();
        avisoCep.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      if (!local && !liberarEnvio) {
        // ainda não calculou a entrega: calcula agora e envia se estiver tudo certo
        e.preventDefault();
        if (calculando) return;
        const ok = await calcularRota();
        if (ok && !(local.zona === "fora" || local.zona === "invalido")) {
          form.requestSubmit();
        } else if (!ok && digitosCep().length === 8) {
          liberarEnvio = true; // sem serviço de rotas: o servidor confere ao enviar
        } else {
          avisoCep.hidden = false;
          avisoCep.className = "aviso-cep erro";
          avisoCep.textContent = "Informe o CEP e toque em “Calcular entrega”.";
          avisoCep.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        return;
      }
      try {
        const dados = {};
        MEMORIA.forEach((n) => { dados[n] = form.elements[n].value; });
        localStorage.setItem("mt_cliente", JSON.stringify(dados));
      } catch (erro) { /* navegação privada: segue sem lembrar */ }
      enviar.disabled = true;
      enviar.textContent = "Enviando…";
    });

    atualizar();
    atualizarBotao();
    if (cupomCampo.value.trim()) aplicarCupom(true);
  }
})();