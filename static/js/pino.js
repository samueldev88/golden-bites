/* Golden Bites · confirmação do ponto de entrega (pino arrastável + localização do aparelho) */
(() => {
  "use strict";
  const form = document.getElementById("form-checkout");
  const bloco = document.getElementById("pino-bloco");
  if (!form || !bloco) return;

  const mapaEl = document.getElementById("pino-mapa");
  const msg = document.getElementById("pino-msg");
  const botaoGps = document.getElementById("pino-gps");
  const botaoOk = document.getElementById("pino-ok");
  const campoLat = form.elements["destino_lat"];
  const campoLon = form.elements["destino_lon"];
  const campoOrigem = form.elements["destino_origem"];
  const cep = form.elements["cep"];
  const digitosCep = () => cep.value.replace(/\D/g, "");

  let mapa = null;
  let pino = null;
  let confirmado = !!(campoLat.value && campoLon.value); // volta preenchido se o envio deu erro
  let cepDoPino = digitosCep();

  const SVG_PINO = `
    <svg viewBox="0 0 34 44" width="34" height="44" aria-hidden="true">
      <path d="M17 43C17 43 3 27 3 16a14 14 0 0 1 28 0c0 11-14 27-14 27z" fill="#4B1E0E" stroke="#fff" stroke-width="2.5"/>
      <circle cx="17" cy="16" r="6" fill="#B8863F"/>
    </svg>`;
  const estilo = document.createElement("style");
  estilo.textContent = ".pino-icone{background:none;border:0}";
  document.head.appendChild(estilo);

  const dizer = (texto) => { msg.textContent = texto; };

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

  // grava o ponto escolhido pelo cliente e avisa o checkout para recalcular rota e taxa
  const gravar = (lat, lon, origem) => {
    campoLat.value = lat.toFixed(6);
    campoLon.value = lon.toFixed(6);
    campoOrigem.value = origem;
    confirmado = true;
    botaoOk.disabled = true;
    document.dispatchEvent(new CustomEvent("pino:mudou"));
  };
  const limpar = () => {
    campoLat.value = campoLon.value = campoOrigem.value = "";
    confirmado = false;
    botaoOk.disabled = false;
  };

  const criarMapa = (centro, zoom) => {
    mapa = L.map(mapaEl, { scrollWheelZoom: false }).setView(centro, zoom);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap",
      referrerPolicy: "strict-origin-when-cross-origin", // o OpenStreetMap exige o Referer
    }).addTo(mapa);
    pino = L.marker(centro, {
      draggable: true, title: "Arraste até a sua porta",
      icon: L.divIcon({ className: "pino-icone", html: SVG_PINO, iconSize: [34, 44], iconAnchor: [17, 42] }),
    }).addTo(mapa);
    pino.on("dragend", () => {
      const p = pino.getLatLng();
      gravar(p.lat, p.lng, "pino");
      dizer("Ponto marcado. Recalculando a entrega…");
    });
    mapa.on("click", (e) => {
      pino.setLatLng(e.latlng);
      gravar(e.latlng.lat, e.latlng.lng, "pino");
      dizer("Ponto marcado. Recalculando a entrega…");
    });
  };

  const mostrar = (centro, zoom, mover) => {
    if (!mapa) criarMapa(centro, zoom);
    else {
      pino.setLatLng(centro);
      if (mover) mapa.setView(centro, zoom);
    }
    mapa.invalidateSize();
  };

  // o checkout avisa sempre que a entrega é (re)calculada
  document.addEventListener("entrega:calculada", async (e) => {
    const local = e.detail;
    if (!local || local.zona === "invalido") { bloco.hidden = true; return; }
    bloco.hidden = false;
    try {
      await carregarLeaflet();
    } catch (erro) {
      mapaEl.hidden = true;
      dizer("Não foi possível carregar o mapa agora. Você pode enviar o pedido assim mesmo.");
      return;
    }
    mapaEl.hidden = false;

    if (confirmado) { // o pino do cliente não sai do lugar quando a rota é recalculada
      mostrar([parseFloat(campoLat.value), parseFloat(campoLon.value)], 17, !mapa);
      dizer("Ponto confirmado. O entregador vai direto para ele.");
      botaoOk.disabled = true;
      return;
    }
    botaoOk.disabled = false;
    if (local.destino) {
      const exato = local.precisao === "endereco";
      mostrar([local.destino.lat, local.destino.lon], exato ? 18 : 16, true);
      dizer(exato
        ? "Achamos o endereço no mapa. Se o pino estiver na sua porta, toque em “Confirmar este ponto”."
        : "Só achamos a região do seu endereço. Arraste o pino até a sua porta ou use a sua localização.");
    } else if (local.origem) {
      mostrar([local.origem.lat, local.origem.lon], 14, true);
      dizer("Não achamos o ponto exato. Toque no mapa onde fica a sua porta ou use a sua localização.");
    }
  });

  botaoOk.addEventListener("click", () => {
    if (!pino) return;
    const p = pino.getLatLng();
    gravar(p.lat, p.lng, "pino");
    dizer("Ponto confirmado. O entregador vai direto para ele.");
  });

  botaoGps.addEventListener("click", async () => {
    if (!navigator.geolocation) { dizer("Este aparelho não permite localização. Marque o ponto no mapa."); return; }
    botaoGps.disabled = true;
    dizer("Procurando a sua localização…");
    try {
      await carregarLeaflet();
    } catch (erro) {
      botaoGps.disabled = false;
      dizer("Não foi possível carregar o mapa agora.");
      return;
    }
    navigator.geolocation.getCurrentPosition((pos) => {
      botaoGps.disabled = false;
      mapaEl.hidden = false;
      const { latitude, longitude, accuracy } = pos.coords;
      mostrar([latitude, longitude], 18, true);
      gravar(latitude, longitude, "gps");
      dizer(accuracy > 60
        ? `Localização com pouca precisão (cerca de ${Math.round(accuracy)} m). Ajuste o pino até a sua porta.`
        : "Localização marcada. Se não for onde você quer receber, arraste o pino.");
    }, (erro) => {
      botaoGps.disabled = false;
      dizer(erro.code === 1
        ? "Permissão negada. Libere a localização deste site no navegador ou marque o ponto no mapa."
        : "Não conseguimos a sua localização agora. Marque o ponto no mapa.");
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  });

  // outro CEP = outro lugar: descarta o ponto anterior
  cep.addEventListener("input", () => {
    const d = digitosCep();
    if (d !== cepDoPino) {
      cepDoPino = d;
      limpar();
      bloco.hidden = true;
    }
  });
})();