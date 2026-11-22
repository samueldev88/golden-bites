import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from requests import Timeout

from catalogo.models import ConfiguracaoLoja, Produto

from . import mercadopago as mp
from .forms import CheckoutForm
from .models import AvaliacaoProduto, Cliente, Cupom, ItemPedido, Pedido
from .services import criar_pedido


class PedidoAccessTests(TestCase):
    def setUp(self):
        cliente = Cliente.objects.create(nome="Ana Silva", telefone="21975913351")
        self.pedido = Pedido.objects.create(
            cliente=cliente,
            modalidade=Pedido.Modalidade.RAPIDA,
            bairro_nome="Centro",
            rua="Rua das Flores",
            numero="10",
            status=Pedido.Status.AGUARDANDO_CONFIRMACAO,
        )
        self.produto = Produto.objects.create(nome="Trufa teste", preco="8.00")
        ItemPedido.objects.create(
            pedido=self.pedido,
            produto=self.produto,
            nome=self.produto.nome,
            preco_unitario=self.produto.preco,
            quantidade=1,
        )

    def test_private_order_routes_hide_orders_not_in_the_session(self):
        rotas = (
            ("pedidos:detalhe", "get"),
            ("pedidos:pagar", "get"),
            ("pedidos:status", "get"),
            ("pedidos:rastreio", "get"),
            ("pedidos:chat", "get"),
            ("pedidos:chat_enviar", "post"),
            ("pedidos:verificar", "get"),
            ("pedidos:retorno", "get"),
        )
        for nome, metodo in rotas:
            with self.subTest(rota=nome):
                resposta = getattr(self.client, metodo)(reverse(nome, args=[self.pedido.codigo]))
                self.assertEqual(resposta.status_code, 404)
        resposta = self.client.post(reverse(
            "pedidos:avaliar_produto", args=[self.pedido.codigo, self.produto.pk],
        ))
        self.assertEqual(resposta.status_code, 404)

    def test_session_owner_can_open_the_order(self):
        sessao = self.client.session
        sessao["pedidos_sessao"] = [self.pedido.codigo]
        sessao.save()

        resposta = self.client.get(reverse("pedidos:detalhe", args=[self.pedido.codigo]))

        self.assertEqual(resposta.status_code, 200)


class PaymentConfirmationDialogTests(TestCase):
    def setUp(self):
        cliente = Cliente.objects.create(nome="Ana Silva", telefone="21975913351")
        self.pedido = Pedido.objects.create(
            cliente=cliente,
            modalidade=Pedido.Modalidade.AGENDADA,
            bairro_nome="Centro",
            rua="Rua das Flores",
            numero="10",
            status=Pedido.Status.AGUARDANDO_PAGAMENTO,
            mp_preference_id="preference-123",
        )
        sessao = self.client.session
        sessao["pedidos_sessao"] = [self.pedido.codigo]
        sessao.save()

    def test_paid_order_shows_confirmation_dialog_only_when_payment_was_approved(self):
        self.pedido.status = Pedido.Status.PAGO
        self.pedido.save()
        with (
            patch("pedidos.views.mp.conferir_pagamento"),
            patch("pedidos.views.aparelho_novo_para_pedido", return_value=None),
        ):
            resposta = self.client.get(
                reverse("pedidos:detalhe", args=[self.pedido.codigo]),
                {"pagamento": "aprovado"},
            )

        self.assertContains(resposta, 'id="modal-pagamento-aprovado"')
        self.assertContains(resposta, "Pagamento aprovado")
        self.assertContains(resposta, "Acompanhar pedido")

    def test_unpaid_order_cannot_show_confirmation_dialog_with_query_parameter(self):
        with (
            patch("pedidos.views.mp.conferir_pagamento"),
            patch("pedidos.views.aparelho_novo_para_pedido", return_value=None),
        ):
            resposta = self.client.get(
                reverse("pedidos:detalhe", args=[self.pedido.codigo]),
                {"pagamento": "aprovado"},
            )

        self.assertNotContains(resposta, 'id="modal-pagamento-aprovado"')

    @override_settings(MP_ACCESS_TOKEN="test-token")
    def test_provider_return_redirects_to_confirmation_after_payment_is_approved(self):
        def aprovar(pedido):
            pedido.status = Pedido.Status.PAGO
            pedido.save()
            return pedido

        with (
            patch("pedidos.views.mp.sincronizar"),
            patch("pedidos.views.mp.sincronizar_pedido", side_effect=aprovar),
        ):
            resposta = self.client.get(
                reverse("pedidos:retorno", args=[self.pedido.codigo]),
                {"payment_id": "payment-123"},
            )

        url = f"{reverse('pedidos:detalhe', args=[self.pedido.codigo])}?pagamento=aprovado"
        self.assertRedirects(resposta, url, fetch_redirect_response=False)


class CheckoutCoordinateTests(TestCase):
    def test_form_does_not_use_submitted_gps_coordinates_for_delivery_pricing(self):
        dados = {
            "nome": "Ana",
            "sobrenome": "Silva",
            "telefone": "21975913351",
            "cep": "22790-000",
            "rua": "Rua das Flores",
            "numero": "10",
            "bairro": "Centro",
            "pin_lat": "-23.0200",
            "pin_lon": "-43.4650",
            "modalidade": Pedido.Modalidade.RAPIDA,
            "forma_pagamento": Pedido.Pagamento.PIX,
            "cupom": "",
        }
        with patch("pedidos.forms.avaliar", return_value={"zona": "rapida", "taxa": Decimal("5.00")}) as avaliar:
            form = CheckoutForm(
                dados,
                config=ConfiguracaoLoja.obter(),
                subtotal=Decimal("10.00"),
            )
            valido = form.is_valid()

        self.assertTrue(valido, form.errors)
        self.assertEqual(len(avaliar.call_args.args), 4)

    def test_delivery_quote_ignores_client_supplied_coordinates(self):
        with (
            patch("pedidos.views.limitar", return_value=True),
            patch("pedidos.views.avaliar", return_value={"zona": "desconhecida", "taxa": None}) as avaliar,
        ):
            resposta = self.client.get(
                reverse("pedidos:cep"),
                {"cep": "22790000", "lat": "-23.0200", "lon": "-43.4650"},
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(avaliar.call_args.args), 4)


class CouponLimitTests(TestCase):
    def test_last_coupon_use_is_rechecked_when_creating_the_order(self):
        produto = Produto.objects.create(nome="Trufa teste", preco="10.00")
        cupom = Cupom.objects.create(
            codigo="ULTIMOUSO",
            tipo=Cupom.PERCENTUAL,
            valor=10,
            limite_usos=1,
        )
        cupom_obsoleto = Cupom.objects.get(pk=cupom.pk)
        dados = {
            "nome": "Ana",
            "sobrenome": "Silva",
            "telefone": "21975913351",
            "modalidade": Pedido.Modalidade.AGENDADA,
            "bairro": "Centro",
            "rua": "Rua das Flores",
            "numero": "10",
            "forma_pagamento": Pedido.Pagamento.PIX,
        }
        itens = [{"produto": produto, "quantidade": 1}]

        criar_pedido(
            dados, itens, Decimal("10.00"), cupom=cupom_obsoleto,
            avaliacao={"taxa": Decimal("0.00")},
        )
        with self.assertRaisesMessage(ValueError, "limite de usos"):
            criar_pedido(
                dados, itens, Decimal("10.00"), cupom=cupom_obsoleto,
                avaliacao={"taxa": Decimal("0.00")},
            )

        cupom.refresh_from_db()
        self.assertEqual(cupom.usos, 1)
        self.assertEqual(Pedido.objects.count(), 1)


class AvaliacaoProdutoTests(TestCase):
    def setUp(self):
        cliente = Cliente.objects.create(nome="Ana Silva", telefone="21975913351")
        self.pedido = Pedido.objects.create(
            cliente=cliente,
            modalidade=Pedido.Modalidade.AGENDADA,
            bairro_nome="Centro",
            rua="Rua das Flores",
            numero="10",
            status=Pedido.Status.ENTREGUE,
        )
        self.produto = Produto.objects.create(nome="Brownie teste", preco="10.00")
        ItemPedido.objects.create(
            pedido=self.pedido,
            produto=self.produto,
            nome=self.produto.nome,
            preco_unitario=self.produto.preco,
            quantidade=1,
        )
        sessao = self.client.session
        sessao["pedidos_sessao"] = [self.pedido.codigo]
        sessao.save()

    def test_delivered_order_shows_centered_review_dialog(self):
        with (
            patch("pedidos.views.mp.conferir_pagamento"),
            patch("pedidos.views.aparelho_novo_para_pedido", return_value=None),
        ):
            resposta = self.client.get(reverse("pedidos:detalhe", args=[self.pedido.codigo]))

        self.assertContains(resposta, "<dialog")
        self.assertContains(resposta, "Como foi Brownie teste?")
        self.assertContains(resposta, "Enviar avaliação")

    def test_customer_can_review_purchased_product_only_once(self):
        url = reverse(
            "pedidos:avaliar_produto", args=[self.pedido.codigo, self.produto.pk],
        )
        dados = {"nota": "5", "comentario": "Produto excelente!"}

        resposta = self.client.post(url, dados)

        self.assertRedirects(resposta, reverse("pedidos:detalhe", args=[self.pedido.codigo]))
        avaliacao = AvaliacaoProduto.objects.get(pedido=self.pedido, produto=self.produto)
        self.assertEqual(avaliacao.nota, 5)

        resposta = self.client.post(url, {"nota": "1", "comentario": "Ruim."})

        self.assertRedirects(resposta, reverse("pedidos:detalhe", args=[self.pedido.codigo]))
        avaliacao.refresh_from_db()
        self.assertEqual(avaliacao.nota, 5)

    def test_order_must_be_delivered_before_review(self):
        self.pedido.status = Pedido.Status.EM_PREPARO
        self.pedido.save(update_fields=["status"])

        resposta = self.client.post(
            reverse("pedidos:avaliar_produto", args=[self.pedido.codigo, self.produto.pk]),
            {"nota": "5", "comentario": "Produto excelente!"},
        )

        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(AvaliacaoProduto.objects.filter(pedido=self.pedido).exists())

    def test_product_page_shows_public_review_without_full_name(self):
        AvaliacaoProduto.objects.create(
            pedido=self.pedido,
            produto=self.produto,
            nota=5,
            comentario="Muito gostoso!",
        )

        resposta = self.client.get(reverse("catalogo:produto", args=[self.produto.slug]))

        self.assertContains(resposta, "Ana S.")
        self.assertContains(resposta, "Muito gostoso!")
        self.assertNotContains(resposta, "Ana Silva")
        self.assertContains(resposta, "Compra verificada")

    def test_reviews_are_not_offered_before_delivery(self):
        self.pedido.status = Pedido.Status.PAGO
        self.pedido.save(update_fields=["status"])
        with (
            patch("pedidos.views.mp.conferir_pagamento"),
            patch("pedidos.views.aparelho_novo_para_pedido", return_value=None),
        ):
            resposta = self.client.get(reverse("pedidos:detalhe", args=[self.pedido.codigo]))

        self.assertNotContains(resposta, "<dialog")

    def test_next_unreviewed_product_is_offered_after_submission(self):
        outro_produto = Produto.objects.create(nome="Trufa teste", preco="8.00")
        ItemPedido.objects.create(
            pedido=self.pedido,
            produto=outro_produto,
            nome=outro_produto.nome,
            preco_unitario=outro_produto.preco,
            quantidade=1,
        )
        self.client.post(
            reverse("pedidos:avaliar_produto", args=[self.pedido.codigo, self.produto.pk]),
            {"nota": "4", "comentario": "Muito bom!"},
        )

        with (
            patch("pedidos.views.mp.conferir_pagamento"),
            patch("pedidos.views.aparelho_novo_para_pedido", return_value=None),
        ):
            resposta = self.client.get(reverse("pedidos:detalhe", args=[self.pedido.codigo]))

        self.assertContains(resposta, "Como foi Trufa teste?")

    def test_reviews_panel_requires_staff_login(self):
        resposta = self.client.get(reverse("painel:avaliacoes"))

        self.assertEqual(resposta.status_code, 302)

    def test_staff_reviews_page_lists_product_reviews(self):
        AvaliacaoProduto.objects.create(
            pedido=self.pedido,
            produto=self.produto,
            nota=5,
            comentario="Muito gostoso!",
        )
        usuario = get_user_model().objects.create_user(
            username="staff-review", password="test-password", is_staff=True,
        )
        self.client.force_login(usuario)

        resposta = self.client.get(reverse("painel:avaliacoes"))

        self.assertContains(resposta, self.produto.nome)
        self.assertContains(resposta, "Muito gostoso!")


class MercadoPagoWebhookTests(TestCase):
    @override_settings(MP_ACCESS_TOKEN="test-token", SITE_URL="https://golden.example")
    def test_preference_timeout_is_reported_as_retryable_without_hanging(self):
        cliente = Cliente.objects.create(nome="Ana Silva", telefone="21975913351")
        pedido = Pedido.objects.create(
            cliente=cliente,
            modalidade=Pedido.Modalidade.AGENDADA,
            bairro_nome="Centro",
            rua="Rua das Flores",
            numero="10",
            status=Pedido.Status.AGUARDANDO_PAGAMENTO,
        )
        with patch("pedidos.mercadopago.requests.post", side_effect=Timeout) as requisicao:
            with self.assertRaisesMessage(mp.ErroMercadoPago, "temporariamente indisponível"):
                mp.criar_preferencia(pedido)

        self.assertEqual(requisicao.call_args.kwargs["timeout"], mp.API_TIMEOUT)

    @override_settings(MP_WEBHOOK_SECRET="webhook-secret")
    def test_webhook_rejects_missing_signature(self):
        resposta = self.client.post(
            reverse("pedidos:webhook"),
            data=json.dumps({"type": "payment", "data": {"id": "123"}}),
            content_type="application/json",
        )

        self.assertEqual(resposta.status_code, 401)

    @override_settings(MP_WEBHOOK_SECRET="webhook-secret")
    def test_webhook_synchronizes_only_a_valid_signature(self):
        payment_id = "123"
        request_id = "request-1"
        timestamp = "1700000000"
        manifesto = f"id:{payment_id};request-id:{request_id};ts:{timestamp};"
        assinatura = hmac.new(
            b"webhook-secret", manifesto.encode(), hashlib.sha256,
        ).hexdigest()

        with patch("pedidos.views.mp.sincronizar") as sincronizar:
            resposta = self.client.post(
                reverse("pedidos:webhook"),
                data=json.dumps({"type": "payment", "data": {"id": payment_id}}),
                content_type="application/json",
                HTTP_X_REQUEST_ID=request_id,
                HTTP_X_SIGNATURE=f"ts={timestamp},v1={assinatura}",
            )

        self.assertEqual(resposta.status_code, 200)
        sincronizar.assert_called_once_with(payment_id)
