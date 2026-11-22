import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from golden.security import ip_do_cliente

from .models import CodigoVinculo, Dispositivo, LimiteTentativas
from .models import MovimentoPontos as M

COOKIE = "mt_fid"
VALIDADE_COOKIE = 60 * 60 * 24 * 365
VALIDADE_VINCULO_MINUTOS = 15
TENTATIVAS_MAX_VINCULO = 5


def saldo(cliente):
    return M.objects.filter(cliente=cliente).aggregate(t=Sum("pontos"))["t"] or 0


def normalizar_telefone(texto):
    digitos = re.sub(r"\D", "", texto or "")
    if digitos.startswith("55") and len(digitos) > 11:
        digitos = digitos[2:]
    return digitos


def saldo_por_telefone(telefone):
    from pedidos.models import Cliente  # import tardio: evita ciclo entre os apps

    digitos = normalizar_telefone(telefone)
    if len(digitos) not in (10, 11):
        return 0
    cliente = Cliente.objects.filter(telefone=digitos).first()
    return saldo(cliente) if cliente else 0


def resumo(pontos, meta):
    """Dados prontos para a página de fidelidade."""
    meta = max(meta, 1)
    resgates = pontos // meta
    resto = pontos % meta
    preenchidas = meta if (pontos > 0 and resto == 0) else resto
    return {
        "saldo": pontos,
        "meta": meta,
        "resgates": resgates,
        "faltam": 0 if resgates and resto == 0 else meta - resto,
        "bolinhas": [i < preenchidas for i in range(meta)],
    }


def sincronizar_pedido(pedido):
    """Credita pontos quando o pedido é pago e estorna se for cancelado.

    Idempotente: pode ser chamada a cada save() sem duplicar movimentos.
    """
    if not pedido.pk:
        return
    tipos = {m.tipo: m for m in M.objects.filter(pedido=pedido)}

    if pedido.status in pedido.STATUS_PAGOS:
        if M.GANHO not in tipos:
            pontos = pedido.pontos_ganhos
            if pontos > 0:
                M.objects.create(
                    cliente=pedido.cliente, pedido=pedido, tipo=M.GANHO, pontos=pontos,
                    observacao=f"Pedido {pedido.codigo}",
                )
        if pedido.status == "entregue" and M.BONUS_ATRASO not in tipos:
            _bonus_por_atraso(pedido)
    elif pedido.status == "cancelado":
        if M.GANHO in tipos and M.ESTORNO_GANHO not in tipos:
            M.objects.create(
                cliente=pedido.cliente, pedido=pedido, tipo=M.ESTORNO_GANHO,
                pontos=-tipos[M.GANHO].pontos, observacao=f"Pedido {pedido.codigo} cancelado",
            )
        if M.RESGATE in tipos and M.ESTORNO_RESGATE not in tipos:
            M.objects.create(
                cliente=pedido.cliente, pedido=pedido, tipo=M.ESTORNO_RESGATE,
                pontos=-tipos[M.RESGATE].pontos, observacao=f"Pedido {pedido.codigo} cancelado",
            )


def _bonus_por_atraso(pedido):
    """Entrega rápida fora da previsão: 1 ponto a cada 5 minutos completos de atraso."""
    from catalogo.models import ConfiguracaoLoja  # import tardio: evita ciclo entre os apps

    if not ConfiguracaoLoja.obter().fidelidade_ativa or not pedido.prazo_entrega or not pedido.entregue_em:
        return
    pontos = pedido.pontos_atraso
    if pontos > 0:
        M.objects.create(
            cliente=pedido.cliente, pedido=pedido, tipo=M.BONUS_ATRASO, pontos=pontos,
            observacao=f"Pedido {pedido.codigo}: {pedido.atraso_min} min de atraso",
        )


# ------------------------------------------------ segurança: aparelhos de confiança
def _hash(valor):
    return hashlib.sha256(f"{settings.SECRET_KEY}:{valor}".encode()).hexdigest()


def limitar(chave, maximo, janela_segundos):
    """True enquanto não passou de `maximo` tentativas na janela."""
    if maximo < 1 or janela_segundos < 1:
        return False

    chave_hash = hashlib.sha256(str(chave).encode()).hexdigest()
    agora = timezone.now()
    expira_em = agora + timedelta(seconds=janela_segundos)
    registro, criado = LimiteTentativas.objects.get_or_create(
        chave=chave_hash,
        defaults={"tentativas": 1, "expira_em": expira_em},
    )
    permitida = criado
    if not criado:
        reiniciado = LimiteTentativas.objects.filter(
            pk=registro.pk, expira_em__lte=agora,
        ).update(tentativas=1, expira_em=expira_em)
        if reiniciado:
            permitida = True
        else:
            permitida = LimiteTentativas.objects.filter(
                pk=registro.pk,
                expira_em__gt=agora,
                tentativas__lt=maximo,
            ).update(tentativas=F("tentativas") + 1) == 1

    if cache.add("limite:limpeza", 1, 60 * 60):
        LimiteTentativas.objects.filter(expira_em__lte=agora).delete()
    return permitida


def emitir_dispositivo(cliente):
    """Cria um aparelho de confiança e devolve o valor que vai no cookie."""
    token = secrets.token_urlsafe(32)
    aparelho = Dispositivo.objects.create(cliente=cliente, token_hash=_hash(token))
    return f"{aparelho.id}.{token}"


def cliente_do_dispositivo(request):
    """Cliente dono do aparelho (cookie válido) ou None."""
    id_texto, _, token = request.COOKIES.get(COOKIE, "").partition(".")
    if not id_texto.isdigit() or not token:
        return None
    aparelho = Dispositivo.objects.select_related("cliente").filter(pk=int(id_texto)).first()
    if aparelho and secrets.compare_digest(aparelho.token_hash, _hash(token)):
        return aparelho.cliente
    return None


def definir_cookie(resposta, valor):
    resposta.set_cookie(COOKIE, valor, max_age=VALIDADE_COOKIE, httponly=True, samesite="Lax",
                        secure=not settings.DEBUG)


def esquecer_dispositivo(request, resposta):
    """Remove este aparelho (cookie e registro)."""
    id_texto, _, _ = request.COOKIES.get(COOKIE, "").partition(".")
    if id_texto.isdigit():
        Dispositivo.objects.filter(pk=int(id_texto)).delete()
    resposta.delete_cookie(COOKIE)


def aparelho_novo_para_pedido(request, pedido):
    """Valor do cookie se este aparelho deve virar o de confiança do cliente, ou None.

    O primeiro aparelho que abre um pedido PAGO do cliente vira o aparelho de confiança dele.
    Outros aparelhos entram com o código de recuperação (que o próprio cliente vê no verso do
    cartão) ou, se ele perdeu tudo, com um código de vínculo gerado pela loja.
    """
    if pedido.status not in pedido.STATUS_PAGOS:
        return None
    if cliente_do_dispositivo(request) == pedido.cliente:
        return None
    if pedido.cliente.dispositivos.exists():
        return None
    return emitir_dispositivo(pedido.cliente)


def codigo_recuperacao(cliente):
    """Código de recuperação do cliente (10 letras/números), sempre o mesmo até ele pedir um novo.

    É calculado a partir da chave secreta do site (HMAC), então não fica guardado em lugar nenhum
    e pode ser mostrado de novo no verso do cartão, em aparelho de confiança.
    """
    base = hmac.new(
        settings.SECRET_KEY.encode(), f"recuperacao:{cliente.pk}:{cliente.versao_recuperacao}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.b32encode(base).decode().rstrip("=")[:10]


def formatar_recuperacao(codigo):
    return f"{codigo[:5]}-{codigo[5:]}"


def usar_recuperacao(cliente, texto):
    """Confere o código de recuperação; devolve o cookie do novo aparelho ou None."""
    digitado = re.sub(r"[^A-Za-z0-9]", "", texto or "").upper()
    if len(digitado) != 10 or not secrets.compare_digest(digitado, codigo_recuperacao(cliente)):
        return None
    return emitir_dispositivo(cliente)


def gerar_codigo_vinculo(cliente):
    """Cria código de vínculo de uso único, válido por 15 minutos."""
    codigo = "".join(secrets.choice("0123456789") for _ in range(6))
    with transaction.atomic():
        CodigoVinculo.objects.filter(cliente=cliente, usado=False).update(usado=True)
        CodigoVinculo.objects.create(
            cliente=cliente, codigo_hash=_hash(f"{cliente.pk}:{codigo}"),
            expira_em=timezone.now() + timedelta(minutes=VALIDADE_VINCULO_MINUTOS),
        )
    return codigo


def usar_codigo_vinculo(cliente, codigo):
    """Valida o código; devolve o valor do cookie do novo aparelho ou None."""
    codigo = (codigo or "").strip()
    agora = timezone.now()
    pendente = (CodigoVinculo.objects.filter(cliente=cliente, usado=False, expira_em__gt=agora)
                .order_by("-id").first())
    if not pendente:
        return None

    tentativa_registrada = CodigoVinculo.objects.filter(
        pk=pendente.pk, usado=False, expira_em__gt=agora, tentativas__lt=TENTATIVAS_MAX_VINCULO,
    ).update(tentativas=F("tentativas") + 1)
    if not tentativa_registrada:
        return None
    if (not re.fullmatch(r"[0-9]{6}", codigo)
            or not secrets.compare_digest(pendente.codigo_hash, _hash(f"{cliente.pk}:{codigo}"))):
        return None
    with transaction.atomic():
        consumido = CodigoVinculo.objects.filter(
            pk=pendente.pk, usado=False, expira_em__gt=timezone.now(),
        ).update(usado=True)
        if not consumido:
            return None
        return emitir_dispositivo(cliente)


def formatar_telefone(digitos):
    d = re.sub(r"\D", "", digitos or "")
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return d