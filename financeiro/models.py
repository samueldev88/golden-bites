from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Lancamento(models.Model):
    """Entradas e saídas registradas à mão (as vendas do site entram sozinhas nos relatórios)."""

    ENTRADA = "entrada"
    SAIDA = "saida"
    TIPOS = [(ENTRADA, "Entrada"), (SAIDA, "Saída")]
    CATEGORIAS = [
        ("ingredientes", "Ingredientes"),
        ("embalagens", "Embalagens"),
        ("entrega", "Entrega e transporte"),
        ("marketing", "Marketing"),
        ("taxas", "Taxas (Mercado Pago, etc.)"),
        ("equipamentos", "Equipamentos"),
        ("venda_avulsa", "Venda avulsa (fora do site)"),
        ("outros", "Outros"),
    ]

    data = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=8, choices=TIPOS, default=SAIDA)
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, default="outros")
    descricao = models.CharField("Descrição", max_length=160)
    valor = models.DecimalField("Valor (R$)", max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])

    class Meta:
        ordering = ["-data", "-id"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.valor} - {self.descricao}"