import ipaddress

from django.conf import settings


def _ip(valor):
    try:
        return ipaddress.ip_address(valor)
    except (TypeError, ValueError):
        return None


def proxy_confiavel(valor):
    endereco = _ip(valor)
    if endereco is None:
        return False
    for rede_texto in getattr(settings, "TRUSTED_PROXY_IPS", ()):
        try:
            if endereco in ipaddress.ip_network(rede_texto, strict=False):
                return True
        except ValueError:
            continue
    return False


def ip_do_cliente(request):
    remoto = _ip(request.META.get("REMOTE_ADDR"))
    if remoto is None:
        return "?"
    if not proxy_confiavel(str(remoto)):
        return str(remoto)

    encaminhados = request.META.get("HTTP_X_FORWARDED_FOR", "")
    for valor in reversed(encaminhados.split(",")):
        endereco = _ip(valor.strip())
        if endereco is not None and not proxy_confiavel(str(endereco)):
            return str(endereco)
    return str(remoto)
