"""Localiza o CEP, calcula a distância até a loja e decide o tipo de entrega.

1. Endereço do CEP (rua, bairro, cidade): BrasilAPI, AwesomeAPI e ViaCEP, consultadas ao mesmo tempo.
2. Coordenadas da rua retornada pelos serviços do CEP, ou as coordenadas do próprio CEP como último recurso.
3. Distância manual do bairro só é usada quando o serviço do CEP confirmou o nome do bairro.

Regra de segurança: só bloqueamos um cliente ("fora da área") quando a localização é confiável
(distância cadastrada, endereço ou rua). Com localização imprecisa, o pedido segue e a entrega é
confirmada pelo WhatsApp.
"""
import hashlib
import json
import logging
import math
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.core.cache import cache

from .models import Bairro
from .services import taxa_para_distancia

log = logging.getLogger(__name__)

TEMPO_LIMITE = 4  # segundos (as três consultas de CEP rodam juntas)
CABECALHO = {"User-Agent": "GoldenBites/1.0 (loja online)"}
FONTES = {
    "brasil": "https://brasilapi.com.br/api/cep/v2/{cep}",
    "awesome": "https://cep.awesomeapi.com.br/json/{cep}",
    "viacep": "https://viacep.com.br/ws/{cep}/json/",
}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
CATEGORIAS_ENDERECO = {"highway", "building", "amenity", "shop", "office", "tourism", "leisure",
                       "man_made", "place", "landuse", "craft", "healthcare", "historic"}
TIPOS_BAIRRO = {"suburb", "neighbourhood", "quarter", "city_district", "borough", "village", "hamlet"}
CONFIAVEIS = {"manual", "endereco", "rua"}


def _numero(valor):
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _normalizar(texto):
    texto = unicodedata.normalize("NFD", texto or "")
    return re.sub(r"[\u0300-\u036f]", "", texto).strip().lower()


def _buscar(url):
    """Devolve (dados, nao_encontrado). Falhas de rede devolvem (None, False)."""
    try:
        resposta = requests.get(url, timeout=TEMPO_LIMITE, headers=CABECALHO)
        if resposta.status_code == 200:
            return resposta.json(), False
        if resposta.status_code in (400, 404):
            return None, True
    except (requests.RequestException, ValueError):
        pass
    return None, False


def _de_brasilapi(d):
    coord = (d.get("location") or {}).get("coordinates") or {}
    return {"rua": d.get("street") or "", "bairro": d.get("neighborhood") or "",
            "cidade": d.get("city") or "", "uf": d.get("state") or "",
            "lat": _numero(coord.get("latitude")), "lon": _numero(coord.get("longitude"))}


def _de_awesome(d):
    return {"rua": d.get("address") or "", "bairro": d.get("district") or "",
            "cidade": d.get("city") or "", "uf": d.get("state") or "",
            "lat": _numero(d.get("lat")), "lon": _numero(d.get("lng"))}


def _de_viacep(d):
    return {"rua": d.get("logradouro") or "", "bairro": d.get("bairro") or "",
            "cidade": d.get("localidade") or "", "uf": d.get("uf") or "", "lat": None, "lon": None}


def consultar_cep(cep):
    """Endereço do CEP (8 dígitos).

    Retorna um dict com rua, bairro, cidade, uf, lat e lon (lat/lon do próprio CEP, pouco
    confiáveis); ou {"nao_encontrado": True}; ou {"indisponivel": True} se os serviços falharam.
    """
    chave = f"cep:{cep}"
    guardado = cache.get(chave)
    if guardado:
        return guardado

    with ThreadPoolExecutor(max_workers=len(FONTES)) as pool:
        futuros = {nome: pool.submit(_buscar, url.format(cep=cep)) for nome, url in FONTES.items()}
        respostas = {nome: futuro.result() for nome, futuro in futuros.items()}

    nao_encontrado = any(nf for _, nf in respostas.values())
    brasil = _de_brasilapi(respostas["brasil"][0]) if respostas["brasil"][0] else None
    awesome = _de_awesome(respostas["awesome"][0]) if respostas["awesome"][0] else None
    via = respostas["viacep"][0]
    if via and via.get("erro"):
        nao_encontrado, via = True, None
    viacep = _de_viacep(via) if via else None

    fontes = [f for f in (viacep, brasil, awesome) if f]
    if not fontes:
        return {"nao_encontrado": True} if nao_encontrado else {"indisponivel": True}

    achado = {campo: next((f[campo] for f in fontes if f[campo]), "") for campo in ("rua", "bairro", "cidade", "uf")}
    achado["lat"] = achado["lon"] = None
    for fonte in (brasil, awesome):
        if fonte and fonte["lat"] is not None and fonte["lon"] is not None:
            achado["lat"], achado["lon"] = fonte["lat"], fonte["lon"]
            break

    cache.set(chave, achado, 60 * 60 * 24)
    return achado


def distancia_km(lat1, lon1, lat2, lon2):
    """Distância em linha reta entre dois pontos (fórmula de haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nominatim(params):
    """Primeiro resultado do Nominatim (ou None). Respostas ficam em cache por 30 dias."""
    chave = "geo:" + hashlib.md5(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    guardado = cache.get(chave)
    if guardado is not None:
        return guardado or None
    try:
        resposta = requests.get(
            NOMINATIM, headers=CABECALHO, timeout=5,
            params={**params, "format": "jsonv2", "limit": 1, "countrycodes": "br"},
        )
        if resposta.status_code != 200:
            return None
        dados = resposta.json()
    except (requests.RequestException, ValueError):
        return None  # falha de rede não vai para o cache
    if not isinstance(dados, list):
        return None
    item = dados[0] if dados else {}
    cache.set(chave, item, 60 * 60 * 24 * 30)
    return item or None


def geocodificar(info, bairro, numero="", prazo=None):
    """Coordenadas no nível do endereço, da rua ou do bairro: (lat, lon, precisao) ou None."""
    rua, cidade = info.get("rua", ""), info.get("cidade", "")
    if not cidade:
        return None

    tentativas = []
    if rua:
        digitos = re.match(r"\d+", (numero or "").strip())
        if digitos:
            tentativas.append(("endereco", f"{digitos.group()} {rua}"))
        tentativas.append(("rua", rua))
    for precisao, rua_consulta in tentativas:
        if prazo and time.monotonic() > prazo:
            return None
        item = _nominatim({"street": rua_consulta, "city": cidade})
        if item and (item.get("category") or item.get("class")) in CATEGORIAS_ENDERECO:
            return float(item["lat"]), float(item["lon"]), precisao

    if bairro and not (prazo and time.monotonic() > prazo):
        item = _nominatim({"q": f"{bairro}, {cidade}, {info.get('uf', '')}, Brasil"})
        if item and (item.get("addresstype") in TIPOS_BAIRRO or item.get("type") in TIPOS_BAIRRO):
            return float(item["lat"]), float(item["lon"]), "bairro"
    return None


def _distancia_do_bairro_cadastrado(bairro):
    alvo = _normalizar(bairro)
    if not alvo:
        return None
    for b in Bairro.objects.filter(ativo=True, distancia_km__isnull=False):
        if _normalizar(b.nome) == alvo:
            return float(b.distancia_km)
    return None


def _km_texto(valor):
    return f"{valor:.1f}".replace(".", ",")


FATOR_ROTA_APROXIMADA = 1.3  # quando o serviço de rotas não responde: linha reta x 1,3
URL_ROTA = ("https://routing.openstreetmap.de/{perfil}/route/v1/driving/"
            "{lon1},{lat1};{lon2},{lat2}?overview={detalhe}&geometries=geojson")
PERFIS_ROTA = {"moto": "routed-car", "bicicleta": "routed-bike"}  # a moto usa as mesmas ruas do carro


def perfil_da_loja(config):
    return PERFIS_ROTA.get(getattr(config, "veiculo", "moto"), "routed-car")


def calcular_rota(origem, destino, perfil="routed-car", completa=False, usar_cache=True):
    """Rota pelas ruas (OpenStreetMap). Retorna {"km", "geometria"} ou None.

    completa=True devolve o desenho fiel das ruas (para o mapa ao vivo); senão uma versão simplificada.
    """
    chave = "rota:{}:{}:{:.5f},{:.5f}:{:.5f},{:.5f}".format(
        perfil, int(completa), origem["lat"], origem["lon"], destino["lat"], destino["lon"])
    if usar_cache:
        guardada = cache.get(chave)
        if guardada:
            return guardada
    try:
        resposta = requests.get(
            URL_ROTA.format(perfil=perfil, lon1=origem["lon"], lat1=origem["lat"], lon2=destino["lon"],
                            lat2=destino["lat"], detalhe="full" if completa else "simplified"),
            timeout=6, headers=CABECALHO,
        )
        rota = resposta.json()["routes"][0]
        pontos = [[lat, lon] for lon, lat in rota["geometry"]["coordinates"]]
        passo = max(1, len(pontos) // (700 if completa else 400))
        resultado = {"km": rota["distance"] / 1000, "geometria": pontos[::passo] + [pontos[-1]]}
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None
    if usar_cache:
        cache.set(chave, resultado, 60 * 60 * 24 * 7)
    return resultado


def rota_ao_vivo(codigo, origem, destino, perfil="routed-car"):
    """Rota do entregador até o cliente, recalculada só quando ele andou ~40 m ou passaram 45 s.

    Assim cada cliente que acompanha o mapa não gera uma consulta nova a cada atualização.
    """
    chave = f"rotaviva:{codigo}"
    guardada = cache.get(chave)
    agora = time.time()
    if guardada:
        andou = distancia_km(origem["lat"], origem["lon"], guardada["origem"]["lat"], guardada["origem"]["lon"])
        if andou < 0.04 and agora - guardada["em"] < 45:
            return guardada
    rota = calcular_rota(origem, destino, perfil, completa=True, usar_cache=False)
    if rota:
        guardada = {"origem": dict(origem), "em": agora, "km": rota["km"], "geometria": rota["geometria"]}
        cache.set(chave, guardada, 60 * 30)
    return guardada  # se o serviço falhar, usa a última rota calculada (ou None)


MSG_NAO_CONFIRMADA = (
    "Não conseguimos confirmar a distância até o seu endereço. Pode enviar o pedido: "
    "confirmamos a entrega e a taxa pelo WhatsApp."
)


def endereco_por_coordenadas(lat, lon):
    """Endereço aproximado de um ponto do GPS (rua, número, bairro, CEP), via OpenStreetMap."""
    chave = f"rev:{lat:.4f},{lon:.4f}"
    guardado = cache.get(chave)
    if guardado is not None:
        return guardado
    try:
        resposta = requests.get(
            "https://nominatim.openstreetmap.org/reverse", headers=CABECALHO, timeout=5,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18, "addressdetails": 1},
        )
        if resposta.status_code != 200:
            return {}
        endereco = (resposta.json() or {}).get("address") or {}
    except (requests.RequestException, ValueError, AttributeError):
        return {}
    resultado = {
        "rua": next((endereco[c] for c in ("road", "pedestrian", "residential", "footway", "path") if endereco.get(c)), ""),
        "numero": endereco.get("house_number", ""),
        "bairro": next((endereco[c] for c in ("suburb", "neighbourhood", "quarter", "city_district") if endereco.get(c)), ""),
        "cep": re.sub(r"\D", "", endereco.get("postcode", ""))[:8],
        "cidade": next((endereco[c] for c in ("city", "town", "municipality", "village") if endereco.get(c)), ""),
    }
    cache.set(chave, resultado, 60 * 60 * 24)
    return resultado


def avaliar(cep, bairro_digitado, config, numero=""):
    """Versão segura de _avaliar: qualquer falha inesperada vira "não deu para confirmar"
    (o cliente não é bloqueado e o erro fica registrado no terminal)."""
    try:
        return _avaliar(cep, bairro_digitado, config, numero)
    except Exception as erro:  # noqa: BLE001
        log.exception("Falha ao avaliar a entrega do CEP %s", cep)
        resultado = {
            "cep": cep, "encontrado": False, "rua": "", "bairro": bairro_digitado or "", "cidade": "", "uf": "",
            "distancia_km": None, "taxa": None, "origem": None, "destino": None, "geometria": None,
            "linha_reta_km": None, "rota_km": None, "rota_minutos": None, "rota_aproximada": False,
            "precisao": None, "zona": "desconhecida", "mensagem": MSG_NAO_CONFIRMADA,
        }
        if settings.DEBUG:
            resultado["detalhe"] = f"{type(erro).__name__}: {erro}"
        return resultado


def _avaliar(cep, bairro_digitado, config, numero=""):
    """Decide a zona de entrega do CEP e calcula a rota.

    A zona (raio) usa a distância em linha reta; a taxa usa a distância da rota de bicicleta.
    zona: "rapida", "agendada", "fora", "desconhecida" (não deu para medir com segurança) ou "invalido".
    """
    prazo = time.monotonic() + 10  # tempo máximo para localizar o endereço
    info = consultar_cep(cep)
    origem = {"lat": config.latitude, "lon": config.longitude}
    vazio = {"cep": cep, "encontrado": False, "rua": "", "bairro": "", "cidade": "", "uf": "",
             "distancia_km": None, "taxa": None, "origem": origem, "destino": None, "geometria": None,
             "linha_reta_km": None, "rota_km": None, "rota_minutos": None, "rota_aproximada": False,
             "precisao": None}
    if info.get("nao_encontrado"):
        return {**vazio, "zona": "invalido", "mensagem": "Não encontramos esse CEP. Confira os números."}
    if info.get("indisponivel"):
        info = {}

    bairro_confirmado = info.get("bairro") or ""
    bairro = bairro_confirmado or bairro_digitado or ""

    # Distância manual e geocodificação usam apenas endereço retornado pelo serviço do CEP.
    reta = _distancia_do_bairro_cadastrado(bairro_confirmado)
    manual = reta is not None
    destino, precisao = None, "manual" if manual else None
    if not manual:
        geo = geocodificar(info, "", "", prazo) if info else None
        if geo:
            destino, precisao = {"lat": geo[0], "lon": geo[1]}, geo[2]
        elif info.get("lat") is not None and info.get("lon") is not None:
            destino, precisao = {"lat": info["lat"], "lon": info["lon"]}, "cep"
        if destino:
            reta = distancia_km(origem["lat"], origem["lon"], destino["lat"], destino["lon"])
    log.info("CEP %s bairro=%r precisao=%s linha_reta=%s", cep, bairro, precisao, reta)

    base = {
        **vazio, "encontrado": bool(info), "rua": info.get("rua", ""), "bairro": bairro,
        "cidade": info.get("cidade", ""), "uf": info.get("uf", ""), "destino": destino, "precisao": precisao,
        "numero_nao_encontrado": bool((numero or "").strip()) and precisao == "rua",
    }
    if reta is None:
        return {**base, "zona": "desconhecida", "mensagem": MSG_NAO_CONFIRMADA}

    onde = ", ".join(p for p in (info.get("rua", ""), bairro) if p)
    local = f"{onde}: " if onde else ""

    if reta > config.raio_maximo_km:
        if precisao not in CONFIAVEIS:
            # localização imprecisa (pode ser o centro da cidade): não bloqueia o cliente
            return {**base, "zona": "desconhecida", "mensagem": MSG_NAO_CONFIRMADA}
        return {**base, "linha_reta_km": round(reta, 1), "zona": "fora", "mensagem": (
            f"{local}a cerca de {_km_texto(reta)} km da loja. No momento ainda não levamos até a sua região. "
            "Estamos ampliando a nossa área de entrega!")}

    # rota de bicicleta (ou estimativa, se o serviço de rotas não responder)
    km, geometria, aproximada = reta, None, False
    if not manual and destino:
        rota = calcular_rota(origem, destino, perfil_da_loja(config)) if time.monotonic() < prazo + 4 else None
        if rota:
            km, geometria = rota["km"], rota["geometria"]
        else:
            km, aproximada = reta * FATOR_ROTA_APROXIMADA, True
            geometria = [[origem["lat"], origem["lon"]], [destino["lat"], destino["lon"]]]
    km = round(km, 1)
    minutos = max(1, round(km / max(config.velocidade_bike_kmh, 1) * 60))
    detalhes = {
        "linha_reta_km": round(reta, 1), "distancia_km": km, "rota_km": km, "rota_minutos": minutos,
        "rota_aproximada": aproximada, "geometria": geometria, "taxa": taxa_para_distancia(km),
    }

    if reta <= config.raio_rapida_km:
        mensagem = (f"Entrega rápida disponível para {onde}." if onde else "Entrega rápida disponível.")
        return {**base, **detalhes, "zona": "rapida", "mensagem": mensagem}
    return {**base, **detalhes, "zona": "agendada", "mensagem": (
        f"{local}ainda não entregamos até a sua região no mesmo dia. "
        "Agende a entrega para outro dia: escolha a data abaixo e combinamos o horário pelo WhatsApp.")}