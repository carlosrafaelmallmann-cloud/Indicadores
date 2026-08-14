# Planilhas do IDEB

Deposite aqui os arquivos de divulgação do INEP (xlsx ou zip), obtidos em
https://www.gov.br/inep/pt-br/areas-de-atuacao/pesquisas-estatisticas-e-indicadores/ideb/resultados

O nome do arquivo precisa conter a etapa e o âmbito, como o INEP já publica:

    divulgacao_anos_iniciais_municipios_2025.xlsx
    divulgacao_anos_finais_municipios_2025.xlsx
    divulgacao_ensino_medio_municipios_2025.xlsx
    divulgacao_anos_iniciais_escolas_2025.xlsx
    divulgacao_anos_finais_escolas_2025.xlsx
    divulgacao_ensino_medio_escolas_2025.xlsx
    divulgacao_anos_iniciais_brasil_estados_2025.xlsx
    divulgacao_anos_finais_brasil_estados_2025.xlsx
    divulgacao_ensino_medio_brasil_estados_2025.xlsx

Cada planilha traz a série completa desde 2005 em colunas, de modo que basta a
edição mais recente. Na coleta seguinte, o conversor extrai as linhas de
Estrela, do Rio Grande do Sul e do Brasil para `dados/ideb.csv`, e as planilhas
podem então ser removidas daqui — o CSV é a fonte canônica.

Como o IDEB é bienal, esta operação se repete a cada dois anos.
