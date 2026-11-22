/* Acompanhamento do entregador no mapa (como 99 e iFood): a moto se move até o endereço do cliente. */
(() => {
  "use strict";
  const raiz = document.getElementById("rastreio");
  if (!raiz) return;

  const url = raiz.dataset.url;
  const icone = raiz.dataset.icone;
  const mapaEl = document.getElementById("rastreio-mapa");
  const texto = document.getElementById("rastreio-texto");

  let mapa = null;
  let moto = null;
  let destinoMarcador = null;
  let linha = null;
  let contorno = null;
  let posicaoAtual = null;
  let enquadrou = false;
  let animacao = null;

  const carregarLeaflet = () => new Promise((ok, falha) => {
    if (window.L) { ok(); return; }
    const base = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = base + "leaflet.min.css";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = base + "leaflet.min.js";
    js.onload = ok;
    js.onerror = falha;
    document.head.appendChild(js);
  });

  const iniciarMapa = (dados) => {
    mapa = L.map(mapaEl, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap",
    }).addTo(mapa);
    const centro = dados.destino || dados.loja;
    mapa.setView([centro.lat, centro.lon], 15);
  };

  // desliza a moto suavemente entre duas posições do GPS
  const deslizar = (de, para, ms) => {
    cancelAnimationFrame(animacao);
    const inicio = performance.now();
    const passo = (agora) => {
      const k = Math.min(1, (agora - inicio) / ms);
      moto.setLatLng([de[0] + (para[0] - de[0]) * k, de[1] + (para[1] - de[1]) * k]);
      if (k < 1) animacao = requestAnimationFrame(passo);
    };
    animacao = requestAnimationFrame(passo);
  };

  // trecho da rota que ainda falta: o que a moto já passou não é desenhado
  const trajetoRestante = (rota, pos, destino) => {
    if (!rota || rota.length < 2) return [pos, destino];
    let melhor = 0;
    let menor = Infinity;
    rota.forEach((p, i) => {
      const d = (p[0] - pos[0]) ** 2 + (p[1] - pos[1]) ** 2;
      if (d < menor) { menor = d; melhor = i; }
    });
    const resto = [pos, ...rota.slice(melhor + 1)];
    return resto.length < 2 ? [pos, destino] : resto;
  };

  const desenhar = (dados) => {
    if (dados.destino && !destinoMarcador) {
      destinoMarcador = L.circleMarker([dados.destino.lat, dados.destino.lon], {
        radius: 9, color: "#B8863F", weight: 4, fillColor: "#fff", fillOpacity: 1,
      }).bindTooltip("Você", { permanent: false }).addTo(mapa);
    }

    if (!dados.entregador) {
      texto.textContent = "O entregador já saiu! Assim que a localização dele estiver disponível, ela aparece aqui.";
      return;
    }

    const pos = [dados.entregador.lat, dados.entregador.lon];
    if (!moto) {
      const iconeMoto = L.divIcon({
        className: "entregador-icone",
        html: `<img src="${icone}" alt="Entregador">`,
        iconSize: [76, 52], iconAnchor: [38, 46],
      });
      moto = L.marker(pos, { icon: iconeMoto, keyboard: false, zIndexOffset: 1000 }).addTo(mapa);
    } else if (posicaoAtual) {
      deslizar(posicaoAtual, pos, 1800);
    }
    posicaoAtual = pos;

    if (dados.destino) {
      const destino = [dados.destino.lat, dados.destino.lon];
      // a moto olha para o lado do destino
      moto.getElement().classList.toggle("espelhado", destino[1] < pos[1]);
      const pontos = trajetoRestante(dados.rota, pos, destino);
      const real = Boolean(dados.rota); // com rota das ruas: traço cheio; sem ela: tracejado até o destino
      const estilo = { color: "#B8863F", weight: real ? 6 : 4, opacity: 0.95, dashArray: real ? null : "6 8" };
      if (!linha) {
        contorno = L.polyline(pontos, { color: "#fff", weight: real ? 10 : 0, opacity: 0.9 }).addTo(mapa);
        linha = L.polyline(pontos, estilo).addTo(mapa);
      } else {
        contorno.setLatLngs(pontos);
        contorno.setStyle({ weight: real ? 10 : 0 });
        linha.setLatLngs(pontos);
        linha.setStyle(estilo);
      }
      const limites = L.latLngBounds(pontos);
      if (!enquadrou || !mapa.getBounds().pad(-0.1).contains(pos)) {
        mapa.fitBounds(limites, { padding: [48, 48], maxZoom: 17 });
        enquadrou = true;
      }
    } else if (!enquadrou) {
      mapa.setView(pos, 16);
      enquadrou = true;
    }

    let mensagem = "O entregador está a caminho.";
    if (dados.eta_min !== null && dados.restante_km !== null) {
      const km = dados.restante_km.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
      mensagem = `O entregador está a ${km} km e chega em cerca de ${dados.eta_min} min.`;
    }
    if (dados.previsao) mensagem += ` Previsão de entrega: ${dados.previsao}.`;
    texto.textContent = mensagem;
  };

  const atualizar = async () => {
    let dados;
    try {
      const resp = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (!resp.ok) return;
      dados = await resp.json();
    } catch (erro) { return; }
    if (!dados.ativo) { window.location.reload(); return; } // entregue (ou outro status): mostra a página nova
    if (!mapa) iniciarMapa(dados);
    desenhar(dados);
  };

  carregarLeaflet().then(() => {
    atualizar();
    setInterval(atualizar, 4000);
  }).catch(() => {
    mapaEl.hidden = true;
    texto.textContent = "O entregador saiu com o seu pedido. O mapa não carregou, mas você pode falar com ele pelo chat.";
  });
})();   