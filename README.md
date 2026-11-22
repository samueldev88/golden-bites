# Golden Bites · loja virtual (Django)

## Rodando no Windows

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py seed
python manage.py createsuperuser
python manage.py runserver
```

- Loja: http://127.0.0.1:8000/
- Painel: http://127.0.0.1:8000/painel/ (entre com o superusuário criado)
- `python manage.py seed` cria produtos, faixas de taxa e bairros de EXEMPLO. Troque tudo no painel.

## Mercado Pago (Pix e cartão)
1. No painel do desenvolvedor do Mercado Pago, crie uma aplicação e copie o Access Token.
2. Cole em `MP_ACCESS_TOKEN` no `.env` (use o de TESTE enquanto testa).
3. Configure a chave secreta de Webhooks do Mercado Pago em `MP_WEBHOOK_SECRET`.
4. Em produção, defina `SITE_URL=https://seudominio.com.br`. O retorno automático é ativado
   com HTTPS e o webhook (`/pedido/webhook/`) somente quando a chave secreta estiver configurada.
   Em localhost o pedido é confirmado quando o cliente volta do Mercado Pago.

## Segurança em produção
- Defina `DEBUG=0`, uma `SECRET_KEY` exclusiva, `ALLOWED_HOSTS`, `SITE_URL` HTTPS e
  `CSRF_TRUSTED_ORIGINS` com a origem HTTPS pública. O HTTPS é obrigatório fora do modo de
  desenvolvimento; cookies seguros e HSTS também são ativados.
- Configure `DATABASE_URL` para um PostgreSQL gerenciado com armazenamento persistente; a
  aplicação recusa SQLite quando `DEBUG=0`. Faça backups automáticos e teste periodicamente
  a restauração. O cache e os limites de tentativas usam o banco configurado.
- Antes de publicar uma versão, aplique as migrações e gere os arquivos estáticos com
  `python manage.py migrate` e `python manage.py collectstatic --noinput`.
- Se houver proxy reverso, configure `TRUSTED_PROXY_IPS` com os IPs/CIDRs exatos dos proxies.
  Só use `TRUST_PROXY_SSL=1` se o proxy confiável remover/substituir os cabeçalhos encaminhados.
- Os limites de tentativas são contadores atômicos compartilhados no banco; o cache de pagamentos
  usa a tabela `django_cache`, criada pelas migrações.
- Fotos de produtos aceitam JPG, PNG e WEBP, até 8 MB e 30 megapixels. Páginas e APIs de pedido
  são vinculadas à sessão que fez o pedido.

## Entregas
- Faixas: `/painel/faixas/` (continuas: 0-2, 2-4, 4-6, 6-9, 9-12 km; acima disso, consultar).
- Bairros: `/painel/bairros/`. Entrega rápida usa a distância cadastrada para calcular a taxa.
- Entrega agendada ou bairro sem distância: o pedido fica "Aguardando confirmação"; você
  define a taxa em Pedidos, e o pagamento é liberado para o cliente.

## Estrutura
- `catalogo` produtos, categorias, configuração da loja
- `carrinho` carrinho por sessão
- `entregas` faixas de taxa e bairros
- `pedidos` clientes, pedidos, cupons, Mercado Pago
- `painel` administração em /painel/ (produtos, pedidos, clientes, entregas, cupons)

Cupons (percentual, valor fixo e frete grátis) e preço promocional já estão prontos no painel.
