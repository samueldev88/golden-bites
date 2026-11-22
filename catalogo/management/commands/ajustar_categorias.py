from django.core.management.base import BaseCommand

from catalogo.models import Categoria, Produto, slug_unico

ANTIGAS = ["Clássicas", "Gourmet", "Caixas presente"]


class Command(BaseCommand):
    help = "Deixa as categorias Trufas e Sacolés e move os produtos das categorias antigas para Trufas."

    def handle(self, *args, **opts):
        trufas = Categoria.objects.filter(nome="Trufas").first()
        if trufas is None:
            trufas = Categoria.objects.filter(nome="Clássicas").first()  # reaproveita a primeira
            if trufas is None:
                trufas = Categoria(nome="Trufas")
            trufas.nome = "Trufas"
            trufas.slug = slug_unico(Categoria, "Trufas", trufas.pk)
        trufas.ordem = 1
        trufas.ativa = True
        trufas.save()

        sacoles, _ = Categoria.objects.get_or_create(nome="Sacolés", defaults={"ordem": 2})
        sacoles.ordem = 2
        sacoles.ativa = True
        sacoles.save()

        movidos = 0
        for antiga in Categoria.objects.filter(nome__in=ANTIGAS).exclude(pk__in=[trufas.pk, sacoles.pk]):
            movidos += Produto.objects.filter(categoria=antiga).update(categoria=trufas)
            antiga.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Categorias: Trufas e Sacolés. {movidos} produto(s) movido(s) para Trufas."
        ))