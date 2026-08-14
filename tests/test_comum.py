"""Testes das utilidades compartilhadas (coletores/comum.py).

Cobrem apenas lógica pura, sem acesso à rede — pensados para rodar em
segundos, a qualquer momento, sem depender das APIs externas.
"""
import unittest

from coletores.comum import normalizar, para_numero


class TestNormalizar(unittest.TestCase):
    def test_remove_acentos_e_baixa_caixa(self):
        self.assertEqual(normalizar("População Residente"), "populacao residente")

    def test_colapsa_espacos(self):
        self.assertEqual(normalizar("  a   b  "), "a b")

    def test_none_vira_string_vazia(self):
        self.assertEqual(normalizar(None), "")


class TestParaNumero(unittest.TestCase):
    def test_inteiro(self):
        self.assertEqual(para_numero(42), 42.0)

    def test_string_com_separador_brasileiro(self):
        self.assertEqual(para_numero("1.234,56"), 1234.56)

    def test_marcadores_do_ibge_viram_none(self):
        for marcador in ["-", "..", "...", "X", "x", ""]:
            with self.subTest(marcador=marcador):
                self.assertIsNone(para_numero(marcador))

    def test_none_vira_none(self):
        self.assertIsNone(para_numero(None))

    def test_texto_invalido_vira_none(self):
        self.assertIsNone(para_numero("não é número"))


if __name__ == "__main__":
    unittest.main()
