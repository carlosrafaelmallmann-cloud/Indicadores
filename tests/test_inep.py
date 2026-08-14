"""Testes do parser de planilhas do INEP (coletores/inep.py).

`_mapear_cabecalho` recebe linhas já extraídas de uma planilha (listas de
células) — aqui simuladas à mão, no mesmo formato que as divulgações do IDEB
costumam trazer: uma linha de blocos ("IDEB" / "Projeção"), seguida da linha
de anos.
"""
import unittest

from coletores.inep import (_identificar_ambito, _identificar_etapa,
                            _mapear_cabecalho, _preencher)


class TestIdentificarEtapaEAmbito(unittest.TestCase):
    def test_identifica_etapa_pelo_nome_do_arquivo(self):
        self.assertEqual(_identificar_etapa("divulgacao_anos_iniciais_municipios_2025.xlsx"),
                         "Anos iniciais")
        self.assertEqual(_identificar_etapa("divulgacao_ensino_medio_escolas_2025.xlsx"),
                         "Ensino médio")

    def test_etapa_desconhecida_retorna_none(self):
        self.assertIsNone(_identificar_etapa("planilha_qualquer.xlsx"))

    def test_identifica_ambito(self):
        self.assertEqual(_identificar_ambito("divulgacao_anos_iniciais_escolas_2025.xlsx"),
                         "escola")
        self.assertEqual(_identificar_ambito("divulgacao_anos_iniciais_municipios_2025.xlsx"),
                         "municipio")
        self.assertEqual(_identificar_ambito("divulgacao_anos_iniciais_brasil_estados_2025.xlsx"),
                         "uf")


class TestPreencher(unittest.TestCase):
    def test_repete_ultimo_rotulo_em_celulas_mescladas(self):
        entrada = ["Rede", None, None, "Município"]
        self.assertEqual(_preencher(entrada), ["Rede", "Rede", "Rede", "Município"])


class TestMapearCabecalho(unittest.TestCase):
    def test_localiza_linha_de_anos_e_classifica_blocos(self):
        linhas = [
            ["Código do Município", "Nome do Município", "Rede",
             "IDEB", None, None, "Projeção", None],
            [None, None, None, 2019, 2021, 2023, 2021, 2023],
        ]
        mapa = _mapear_cabecalho(linhas)
        self.assertIsNotNone(mapa)
        self.assertEqual(mapa["linha_anos"], 1)
        self.assertIn(2019, mapa["ideb"])
        self.assertIn(2021, mapa["metas"])
        self.assertEqual(mapa["identificacao"].get("codigo_municipio"), 0)
        self.assertEqual(mapa["identificacao"].get("nome_municipio"), 1)
        self.assertEqual(mapa["identificacao"].get("rede"), 2)

    def test_retorna_none_sem_linha_de_anos_reconhecivel(self):
        linhas = [["nada", "aqui", "parece", "um", "cabecalho"]]
        self.assertIsNone(_mapear_cabecalho(linhas))


if __name__ == "__main__":
    unittest.main()
