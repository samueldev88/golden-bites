from decimal import Decimal

from catalogo.models import Produto


class Carrinho:
    """Carrinho guardado na sessão.

    - itens pagos:   {id_do_produto: quantidade}
    - trocas de pontos (itens grátis): {id_do_produto: quantidade}
    """

    CHAVE = "carrinho"
    CHAVE_TROCAS = "trocas"
    MAXIMO = 99
    MAXIMO_TROCAS = 20

    def __init__(self, request):
        self.session = request.session
        self.dados = self.session.setdefault(self.CHAVE, {})
        self.trocas = self.session.setdefault(self.CHAVE_TROCAS, {})

    def _salvar(self):
        self.session.modified = True

    # ------------------------------------------------------------ itens pagos
    def definir(self, produto_id, quantidade):
        pid = str(produto_id)
        if quantidade <= 0:
            self.dados.pop(pid, None)
        else:
            self.dados[pid] = min(int(quantidade), self.MAXIMO)
        self._salvar()

    def adicionar(self, produto_id, quantidade=1):
        self.definir(produto_id, self.dados.get(str(produto_id), 0) + quantidade)

    def remover(self, produto_id):
        self.definir(produto_id, 0)

    def limpar(self):
        self.session[self.CHAVE] = {}
        self.session[self.CHAVE_TROCAS] = {}
        self.session.modified = True
        self.dados = self.session[self.CHAVE]
        self.trocas = self.session[self.CHAVE_TROCAS]

    @property
    def quantidade_total(self):
        return sum(self.dados.values()) + sum(self.trocas.values())

    @property
    def vazio(self):
        return not self.dados and not self.trocas

    def itens(self):
        """Lista de itens; descarta produtos removidos ou indisponíveis."""
        ids = [int(i) for i in self.dados]
        produtos = Produto.objects.filter(id__in=ids, disponivel=True)
        encontrados = {str(p.id): p for p in produtos}
        if len(encontrados) != len(self.dados):
            self.dados = {k: v for k, v in self.dados.items() if k in encontrados}
            self.session[self.CHAVE] = self.dados
            self._salvar()
        itens = []
        for pid, produto in encontrados.items():
            qtd = self.dados[pid]
            itens.append({
                "produto": produto,
                "quantidade": qtd,
                "subtotal": produto.preco_final * qtd,
            })
        itens.sort(key=lambda i: (i["produto"].ordem, i["produto"].nome))
        return itens

    def subtotal(self):
        return sum((i["subtotal"] for i in self.itens()), Decimal("0.00"))

    # ------------------------------------------------------ trocas de pontos
    def adicionar_troca(self, produto_id):
        pid = str(produto_id)
        self.trocas[pid] = min(self.trocas.get(pid, 0) + 1, self.MAXIMO_TROCAS)
        self._salvar()

    def remover_troca(self, produto_id):
        self.trocas.pop(str(produto_id), None)
        self._salvar()

    def itens_troca(self, config):
        """Itens do carrinho pagos com pontos; descarta os que deixaram de poder ser trocados."""
        ids = [int(i) for i in self.trocas]
        produtos = Produto.objects.filter(id__in=ids, disponivel=True, permite_troca=True, pontos__gt=0)
        encontrados = {str(p.id): p for p in produtos}
        if len(encontrados) != len(self.trocas):
            self.trocas = {k: v for k, v in self.trocas.items() if k in encontrados}
            self.session[self.CHAVE_TROCAS] = self.trocas
            self._salvar()
        lista = []
        for pid, produto in encontrados.items():
            qtd = self.trocas[pid]
            custo = produto.custo_troca(config)
            lista.append({"produto": produto, "quantidade": qtd, "custo_unitario": custo, "pontos": custo * qtd})
        lista.sort(key=lambda i: (i["produto"].ordem, i["produto"].nome))
        return lista

    def pontos_reservados(self, config):
        return sum(i["pontos"] for i in self.itens_troca(config))