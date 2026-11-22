import re

from django.contrib import messages
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from carrinho.cart import Carrinho
from catalogo.models import ConfiguracaoLoja, Produto
from pedidos.models import Cliente

from .services import (
    VALIDADE_VINCULO_MINUTOS, cliente_do_dispositivo, codigo_recuperacao, definir_cookie,
    esquecer_dispositivo, formatar_recuperacao, formatar_telefone, gerar_codigo_vinculo,
    ip_do_cliente, limitar, normalizar_telefone, resumo, saldo, usar_codigo_vinculo, usar_recuperacao,
)


def _produtos_para_troca(config, cliente, livres):
    """Todos os itens que valem pontos, com o estado do botão "Trocar pontos" para este cliente."""
    itens = []
    for produto in Produto.objects.filter(disponivel=True, pontos__gt=0):
        custo = produto.custo_troca(config)
        if not produto.permite_troca:
            estado, rotulo = "indisponivel", "Não disponível para troca"
        elif cliente is None:
            estado, rotulo = "verificar", "Confirme seu aparelho"
        elif livres < custo:
            falta = custo - livres
            estado, rotulo = "faltam", f"Faltam {falta} ponto{'s' if falta != 1 else ''}"
        else:
            estado, rotulo = "ok", "Trocar pontos"
        itens.append({"produto": produto, "custo": custo, "estado": estado, "rotulo": rotulo})
    return itens


@never_cache
def pagina(request):
    config = ConfiguracaoLoja.obter()
    contexto = {
        "config": config, "meta": config.pontos_resgate,
        "validade_vinculo_minutos": VALIDADE_VINCULO_MINUTOS,
    }
    if not config.fidelidade_ativa:
        return render(request, "fidelidade/fidelidade.html", contexto)

    # o saldo só aparece em aparelho de confiança (cookie): digitar o WhatsApp de alguém não mostra nada
    cliente = cliente_do_dispositivo(request)
    livres = 0
    if cliente:
        pontos = saldo(cliente)
        livres = pontos - Carrinho(request).pontos_reservados(config)
        contexto.update(
            cliente=cliente, final_telefone=cliente.telefone[-4:],
            telefone_cartao=formatar_telefone(cliente.telefone),
            codigo_recuperacao=formatar_recuperacao(codigo_recuperacao(cliente)),
            resultado=resumo(pontos, config.pontos_resgate), livres=livres, reservados=pontos - livres,
        )
    contexto["produtos"] = _produtos_para_troca(config, cliente, livres)
    return render(request, "fidelidade/fidelidade.html", contexto)


@require_POST
def vincular(request):
    """Liga este aparelho usando um código temporário ou o código de recuperação."""
    telefone = normalizar_telefone(request.POST.get("telefone"))
    if not limitar(f"vinc-ip:{ip_do_cliente(request)}", 10, 900) or not limitar(f"vinc-tel:{telefone}", 5, 900):
        messages.error(request, "Muitas tentativas. Aguarde 15 minutos e tente de novo.")
        return redirect("fidelidade:pagina")
    cliente = Cliente.objects.filter(telefone=telefone).first() if len(telefone) in (10, 11) else None
    valor = None
    if cliente:
        codigo = re.sub(r"[^A-Za-z0-9]", "", request.POST.get("codigo", ""))
        # 10 letras/números = código de recuperação do cliente; 6 dígitos = código enviado pela loja
        valor = usar_recuperacao(cliente, codigo) if len(codigo) == 10 else usar_codigo_vinculo(cliente, codigo)
    if not valor:  # mesma mensagem para qualquer falha: não revela se o WhatsApp tem cadastro
        messages.error(request, "Código inválido. Confira o WhatsApp e o código do seu cartão.")
        return redirect("fidelidade:pagina")
    resposta = redirect("fidelidade:pagina")
    definir_cookie(resposta, valor)
    messages.success(request, "Aparelho confirmado! Seus pontos já estão aqui.")
    return resposta


@require_POST
def gerar_codigo_dispositivo(request):
    """Gera um código temporário apenas no aparelho confiável do cliente."""
    cliente = cliente_do_dispositivo(request)
    if cliente is None:
        resposta = JsonResponse({"erro": "Confirme este aparelho antes de gerar um código."}, status=401)
        resposta["Cache-Control"] = "no-store, private"
        return resposta

    ip = ip_do_cliente(request)
    if (not limitar(f"gerar-vinculo-ip:{ip}", 10, 900)
            or not limitar(f"gerar-vinculo-cliente:{cliente.pk}", 3, 900)):
        resposta = JsonResponse(
            {"erro": "Muitas solicitações. Aguarde 15 minutos e tente novamente."}, status=429,
        )
        resposta["Cache-Control"] = "no-store, private"
        return resposta

    codigo = gerar_codigo_vinculo(cliente)
    resposta = JsonResponse({"codigo": codigo, "validade_minutos": VALIDADE_VINCULO_MINUTOS})
    resposta["Cache-Control"] = "no-store, private"
    return resposta


@require_POST
def novo_codigo(request):
    """Gera um novo código de recuperação (o anterior deixa de valer)."""
    cliente = cliente_do_dispositivo(request)
    if cliente is None:
        return redirect("fidelidade:pagina")
    Cliente.objects.filter(pk=cliente.pk).update(versao_recuperacao=F("versao_recuperacao") + 1)
    messages.success(request, "Novo código de recuperação gerado. O anterior deixou de valer.")
    return redirect("fidelidade:pagina")


@require_POST
def sair(request):
    """Tira este aparelho da lista de confiança (útil em celular emprestado)."""
    resposta = redirect("fidelidade:pagina")
    esquecer_dispositivo(request, resposta)
    messages.info(request, "Este aparelho não está mais ligado aos seus pontos.")
    return resposta