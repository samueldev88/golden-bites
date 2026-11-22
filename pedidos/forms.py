import re
from datetime import timedelta

from django import forms
from django.utils import timezone

from entregas.cep import avaliar

from .models import AvaliacaoProduto, Cupom, Pedido


class AvaliacaoProdutoForm(forms.ModelForm):
    nota = forms.TypedChoiceField(
        label="Sua nota",
        choices=AvaliacaoProduto.Nota.choices,
        coerce=int,
        widget=forms.RadioSelect,
    )
    comentario = forms.CharField(
        label="Conte o que achou deste produto",
        min_length=5,
        max_length=1000,
        strip=True,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "Sua opinião ajuda a Golden Bites a melhorar.",
        }),
    )

    class Meta:
        model = AvaliacaoProduto
        fields = ("nota", "comentario")


class CheckoutForm(forms.Form):
    nome = forms.CharField(label="Nome", max_length=60)
    sobrenome = forms.CharField(label="Sobrenome", max_length=60)
    telefone = forms.CharField(label="WhatsApp", max_length=20)

    cep = forms.CharField(label="CEP", max_length=9)
    rua = forms.CharField(label="Rua", max_length=150)
    numero = forms.CharField(label="Número", max_length=20)
    complemento = forms.CharField(label="Complemento", max_length=80, required=False)
    bairro = forms.CharField(label="Bairro", max_length=100)
    referencia = forms.CharField(label="Ponto de referência", max_length=120, required=False)
    pin_lat = forms.FloatField(required=False, widget=forms.HiddenInput)
    pin_lon = forms.FloatField(required=False, widget=forms.HiddenInput)

    modalidade = forms.ChoiceField(
        choices=Pedido.Modalidade.choices, initial=Pedido.Modalidade.RAPIDA,
        widget=forms.RadioSelect,
    )
    data_agendada = forms.DateField(
        label="Data da entrega", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    horario_combinado = forms.CharField(
        label="Horário desejado", max_length=80, required=False,
        help_text="Combinamos o horário final pelo WhatsApp.",
    )

    forma_pagamento = forms.ChoiceField(
        choices=Pedido.Pagamento.choices, initial=Pedido.Pagamento.PIX, widget=forms.RadioSelect,
    )
    cupom = forms.CharField(label="Cupom de desconto", max_length=30, required=False)
    observacoes = forms.CharField(
        label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, config=None, subtotal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.subtotal = subtotal
        self.cupom_obj = None
        self.avaliacao = None
        self.fields["nome"].widget.attrs["autocomplete"] = "given-name"
        self.fields["sobrenome"].widget.attrs["autocomplete"] = "family-name"
        self.fields["telefone"].widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "placeholder": "(21) 99999-9999"}
        )
        self.fields["cep"].widget.attrs.update({"inputmode": "numeric", "placeholder": "00000-000"})

    def clean_telefone(self):
        digitos = re.sub(r"\D", "", self.cleaned_data["telefone"])
        if digitos.startswith("55") and len(digitos) > 11:
            digitos = digitos[2:]
        if len(digitos) not in (10, 11):
            raise forms.ValidationError("Informe o DDD e o número. Ex.: (21) 99999-9999")
        return digitos

    def clean_cep(self):
        digitos = re.sub(r"\D", "", self.cleaned_data["cep"])
        if len(digitos) != 8:
            raise forms.ValidationError("Informe os 8 números do CEP.")
        return f"{digitos[:5]}-{digitos[5:]}"

    def clean_cupom(self):
        codigo = self.cleaned_data.get("cupom", "").strip().upper()
        if not codigo:
            return ""
        try:
            cupom = Cupom.objects.get(codigo=codigo)
        except Cupom.DoesNotExist:
            raise forms.ValidationError("Cupom não encontrado.")
        if self.subtotal is not None:
            ok, mensagem = cupom.validar(self.subtotal)
            if not ok:
                raise forms.ValidationError(mensagem)
        self.cupom_obj = cupom
        return codigo

    def clean(self):
        dados = super().clean()
        modalidade = dados.get("modalidade")

        # a zona de entrega vem do CEP (distância até a loja), sempre conferida no servidor
        cep = dados.get("cep")
        if cep and self.config is not None:
            self.avaliacao = avaliar(re.sub(r"\D", "", cep), dados.get("bairro", ""), self.config,
                                     dados.get("numero", ""))
            zona = self.avaliacao["zona"]
            if zona in ("invalido", "fora"):
                self.add_error("cep", self.avaliacao["mensagem"])
            elif zona == "agendada" and modalidade == Pedido.Modalidade.RAPIDA:
                self.add_error(
                    "modalidade",
                    "Para o seu CEP a entrega é somente agendada. Escolha “Entrega agendada”.",
                )

        if modalidade == Pedido.Modalidade.AGENDADA:
            data = dados.get("data_agendada")
            dias = self.config.antecedencia_agendada_dias if self.config else 1
            primeira = timezone.localdate() + timedelta(days=dias)
            if not data:
                self.add_error("data_agendada", "Escolha a data da entrega.")
            elif data < primeira:
                self.add_error(
                    "data_agendada",
                    f"A entrega agendada precisa de {dias} dia(s) de antecedência.",
                )

        return dados