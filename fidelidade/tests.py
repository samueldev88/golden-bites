from datetime import timedelta

from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from pedidos.models import Cliente

from .models import CodigoVinculo, Dispositivo, LimiteTentativas
from .services import (
    COOKIE, emitir_dispositivo, gerar_codigo_vinculo, ip_do_cliente, limitar, usar_codigo_vinculo,
)


class ClienteIpTests(TestCase):
    @override_settings(TRUSTED_PROXY_IPS=["10.0.0.0/8"])
    def test_forwarded_ip_is_used_only_from_a_trusted_proxy(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="198.51.100.24")
        request.META["REMOTE_ADDR"] = "203.0.113.9"
        self.assertEqual(ip_do_cliente(request), "203.0.113.9")

        request.META["REMOTE_ADDR"] = "10.1.2.3"
        request.META["HTTP_X_FORWARDED_FOR"] = "198.51.100.24, 10.2.3.4"
        self.assertEqual(ip_do_cliente(request), "198.51.100.24")


class RateLimitTests(TestCase):
    def test_limit_is_shared_in_the_database_and_resets_after_expiry(self):
        self.assertTrue(limitar("test-key", 2, 60))
        self.assertTrue(limitar("test-key", 2, 60))
        self.assertFalse(limitar("test-key", 2, 60))

        LimiteTentativas.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
        self.assertTrue(limitar("test-key", 2, 60))


class CodigoVinculoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.cliente = Cliente.objects.create(nome="Ana Silva", telefone="21975913351")

    def _confiar_aparelho(self, cliente=None, client=None):
        cliente = cliente or self.cliente
        client = client or self.client
        client.cookies[COOKIE] = emitir_dispositivo(cliente)
        return client

    def test_only_trusted_device_can_generate_code(self):
        response = self.client.post(reverse("fidelidade:gerar_codigo_dispositivo"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(CodigoVinculo.objects.count(), 0)

    def test_trusted_card_shows_customer_details_and_points(self):
        self._confiar_aparelho()

        response = self.client.get(reverse("fidelidade:pagina"))

        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "Ana Silva")
        self.assertContains(response, "(21) 97591-3351")
        self.assertContains(response, "Gerar código temporário")
        self.assertContains(response, 'role="button" tabindex="0"')
        self.assertNotContains(response, "Junte 8 e troque por um item grátis.")
        self.assertNotContains(response, "cartao-bolinhas")

    def test_untrusted_card_does_not_expose_customer_details(self):
        response = self.client.get(reverse("fidelidade:pagina"))

        self.assertContains(response, "CONFIRME SEU APARELHO")
        self.assertNotContains(response, "Ana Silva")
        self.assertNotContains(response, "(21) 97591-3351")

    def test_trusted_device_generates_short_lived_code_that_can_be_used_once(self):
        self._confiar_aparelho()
        response = self.client.post(reverse("fidelidade:gerar_codigo_dispositivo"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        codigo = response.json()["codigo"]
        self.assertRegex(codigo, r"^[0-9]{6}$")
        registro = CodigoVinculo.objects.get(cliente=self.cliente)
        self.assertGreater(registro.expira_em, timezone.now())
        self.assertLessEqual(registro.expira_em, timezone.now() + timedelta(minutes=15))

        vinculo = self.client.post(
            reverse("fidelidade:vincular"),
            {"telefone": self.cliente.telefone, "codigo": codigo},
        )
        self.assertEqual(vinculo.status_code, 302)
        self.assertEqual(Dispositivo.objects.filter(cliente=self.cliente).count(), 2)

        repetido = self.client.post(
            reverse("fidelidade:vincular"),
            {"telefone": self.cliente.telefone, "codigo": codigo},
        )
        self.assertEqual(repetido.status_code, 302)
        self.assertEqual(Dispositivo.objects.filter(cliente=self.cliente).count(), 2)

    def test_code_expires_and_locks_after_five_attempts(self):
        codigo = gerar_codigo_vinculo(self.cliente)
        registro = CodigoVinculo.objects.get(cliente=self.cliente)

        for _ in range(5):
            self.assertIsNone(usar_codigo_vinculo(self.cliente, "not-a-code"))
        self.assertIsNone(usar_codigo_vinculo(self.cliente, codigo))
        registro.refresh_from_db()
        self.assertEqual(registro.tentativas, 5)

        codigo_expirado = gerar_codigo_vinculo(self.cliente)
        CodigoVinculo.objects.filter(cliente=self.cliente, usado=False).update(
            expira_em=timezone.now() - timedelta(seconds=1),
        )
        self.assertIsNone(usar_codigo_vinculo(self.cliente, codigo_expirado))

    def test_code_generation_requires_csrf(self):
        cliente = Cliente.objects.create(nome="João Souza", telefone="21988887777")
        client = self._confiar_aparelho(cliente=cliente, client=Client(enforce_csrf_checks=True))

        response = client.post(reverse("fidelidade:gerar_codigo_dispositivo"))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(CodigoVinculo.objects.filter(cliente=cliente).exists())

    def test_code_generation_is_limited_per_customer(self):
        self._confiar_aparelho()
        url = reverse("fidelidade:gerar_codigo_dispositivo")

        respostas = [self.client.post(url) for _ in range(4)]

        self.assertEqual([resposta.status_code for resposta in respostas], [200, 200, 200, 429])
        self.assertEqual(CodigoVinculo.objects.filter(cliente=self.cliente).count(), 3)
