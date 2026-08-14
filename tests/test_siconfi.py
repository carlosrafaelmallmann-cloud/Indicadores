"""Testes do parser de linhas do SICONFI (coletores/siconfi.py).

Usa amostras sintéticas no formato retornado pela API, sem acessar a rede.
"""
import unittest

from coletores.siconfi import _linha


class TestLinha(unittest.TestCase):
    def setUp(self):
        self.itens = [
            {"conta": "Receitas Correntes", "coluna": "Receitas Brutas Realizadas",
             "valor": "100"},
            {"conta": "Receitas de Capital", "coluna": "Receitas Brutas Realizadas",
             "valor": "50"},
            {"conta": "Despesas Correntes", "coluna": "Despesas Empenhadas",
             "valor": "80"},
        ]

    def test_localiza_por_conta_e_coluna(self):
        linha = _linha(self.itens, "Receitas Correntes", "Receitas Brutas Realizadas")
        self.assertIsNotNone(linha)
        self.assertEqual(linha["valor"], "100")

    def test_tolera_variacao_de_acentuacao_e_caixa(self):
        linha = _linha(self.itens, "receitas correntes", "receitas brutas realizadas")
        self.assertIsNotNone(linha)
        self.assertEqual(linha["valor"], "100")

    def test_retorna_none_quando_conta_nao_existe(self):
        self.assertIsNone(_linha(self.itens, "Conta inexistente"))

    def test_coluna_opcional(self):
        linha = _linha(self.itens, "Despesas Correntes")
        self.assertIsNotNone(linha)
        self.assertEqual(linha["valor"], "80")


if __name__ == "__main__":
    unittest.main()
