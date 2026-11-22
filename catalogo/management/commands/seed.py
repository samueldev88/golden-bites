from decimal import Decimal

from django.core.management.base import BaseCommand

from catalogo.models import Categoria, ConfiguracaoLoja, Produto
from entregas.models import Bairro, FaixaTaxa
from pedidos.models import Cupom


class Command(BaseCommand):
    help = "Cria dados de exemplo (categorias, produtos, faixas de taxa, bairros e um cupom)."

    def handle(self, *args, **opts):
        ConfiguracaoLoja.obter()

        trufas, _ = Categoria.objects.get_or_create(nome="Trufas", defaults={"ordem": 1})
        Categoria.objects.get_or_create(nome="Sacolés", defaults={"ordem": 2})

        produtos = [
            (trufas, "Trufa Tradicional", "Ganache cremosa de chocolate ao leite com cobertura crocante.", "7.50", None, True),
            (trufas, "Trufa de Chocolate Meio Amargo", "Ganache intensa de cacau, para quem ama chocolate de verdade.", "7.50", None, True),
            (trufas, "Trufa de Brigadeiro", "Recheio de brigadeiro cremoso envolto em chocolate ao leite.", "7.00", None, False),
            (trufas, "Trufa de Maracujá", "Ganache de chocolate branco com a acidez delicada do maracujá.", "8.50", None, True),
            (trufas, "Trufa de Pistache", "Creme de pistache sobre chocolate branco, finalizado com dourado.", "9.50", None, True),
            (trufas, "Trufa de Café", "Ganache aveludada com café especial e toque de cacau.", "8.50", "7.90", False),
            (trufas, "Trufa de Caramelo Salgado", "Caramelo com flor de sal dentro de chocolate meio amargo.", "9.00", None, False),
            (trufas, "Caixa Presente com 6 trufas", "Seleção de sabores em caixa elegante, pronta para presentear.", "52.00", "47.00", True),
        ]
        for i, (cat, nome, desc, preco, promo, destaque) in enumerate(produtos, start=1):
            Produto.objects.get_or_create(nome=nome, defaults={
                "categoria": cat, "descricao": desc, "preco": Decimal(preco),
                "preco_promocional": Decimal(promo) if promo else None,
                "destaque": destaque, "ordem": i,
            })

        Produto.objects.filter(nome__startswith="Caixa Presente").update(pontos=6)

        faixas = [("0", "2", "2.00"), ("2", "4", "3.00"), ("4", "6", "5.00"),
                  ("6", "9", "8.00"), ("9", "12", "11.00")]
        for km_min, km_max, taxa in faixas:
            FaixaTaxa.objects.get_or_create(
                km_min=Decimal(km_min), km_max=Decimal(km_max), defaults={"taxa": Decimal(taxa)}
            )

        Cupom.objects.get_or_create(codigo="BEMVINDO10", defaults={
            "tipo": Cupom.PERCENTUAL, "valor": Decimal("10")})

        self.stdout.write(self.style.SUCCESS("Dados de exemplo criados."))