import math
from decimal import Decimal

from .models import FaixaTaxa


def taxa_para_distancia(km, faixas=None):
    """Taxa (Decimal) para a distância, ou None quando é 'consultar disponibilidade'.

    Os limites são inclusivos: 2 km cai na faixa 'até 2 km'.
    """
    if km is None:
        return None
    if faixas is None:
        faixas = FaixaTaxa.objects.filter(ativa=True).order_by("km_min")
    km = Decimal(km)
    for faixa in faixas:
        if faixa.km_min <= km <= faixa.km_max:
            return faixa.taxa
    return None


def taxa_do_bairro(bairro, faixas=None):
    if bairro is None:
        return None
    return taxa_para_distancia(bairro.distancia_km, faixas)


def minutos_previstos(km, config):
    """Previsão de entrega em minutos: preparo + trajeto, arredondada para cima de 5 em 5.

    Ex.: 2 km, 25 km/h, 20 min de preparo -> 20 + 5 = 25 min (pedido às 22:15, previsão 22:40).
    """
    km = 5.0 if km is None else float(km)
    trajeto = math.ceil(km / max(config.velocidade_bike_kmh, 1) * 60)
    return int(math.ceil((config.tempo_preparo_min + trajeto) / 5) * 5)