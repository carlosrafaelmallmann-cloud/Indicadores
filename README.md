# Painel de indicadores — Estrela/RS

Painel público de indicadores do município de Estrela, Rio Grande do Sul
(código IBGE **4307807**), construído sem servidor: os dados são coletados por
rotinas em Python executadas pelo GitHub Actions, gravados em um arquivo JSON
versionado e exibidos por uma página estática.

Não há banco de dados, chave de API no navegador nem serviço que possa ficar
indisponível por inatividade. O histórico de cada indicador fica registrado no
próprio histórico de commits do repositório.

---

## Como funciona

```
GitHub Actions (dias 5 e 20)
        │
        ├─ coletores/ibge.py      → IBGE, API de Dados Agregados v3
        ├─ coletores/siconfi.py   → Tesouro Nacional, API do SICONFI
        ├─ coletores/caged.py     → PDET/MTE, microdados do Novo CAGED
        ├─ coletores/inep.py      → INEP, planilhas do IDEB
        └─ coletores/manuais.py   → dados/manuais.csv
                    │
                    ▼
        dados/indicadores.json  (commit automático)
                    │
                    ▼
              index.html  (GitHub Pages)
```

Se uma fonte estiver fora do ar, a execução continua e o último valor válido é
preservado, sinalizado no painel como **não atualizado**. A coleta só termina
em erro quando nenhuma fonte responde.

---

## Publicação

1. Crie um repositório e envie estes arquivos.
2. Em **Settings → Actions → General → Workflow permissions**, marque
   *Read and write permissions* (o workflow precisa gravar o JSON coletado).
3. Em **Settings → Pages**, escolha *Deploy from a branch*, branch `main`,
   pasta `/ (root)`.
4. Em **Actions → Coleta de indicadores → Run workflow**, dispare a primeira
   execução manualmente. A partir daí ela roda sozinha.

Para rodar na sua máquina:

```bash
pip install -r requirements.txt
python -m coletores.executar            # todas as fontes
python -m coletores.executar ibge       # apenas uma
python -m http.server 8000              # abrir http://localhost:8000
```

---

## Indicadores sem API

`dados/manuais.csv` cobre o que nenhuma fonte publica de forma consultável —
IDEB, cobertura da atenção básica, dados da própria Prefeitura. Basta editar o
arquivo pela interface web do GitHub: a alteração vira um commit datado e a
coleta seguinte incorpora o novo valor.

Para montar série histórica, repita o mesmo `id` com períodos diferentes. O
período mais recente vira o valor em destaque; os anteriores alimentam o
gráfico.

Coluna `formato`: `moeda`, `percentual`, `inteiro` ou `numero`.

---

## Acrescentar uma fonte automatizada

1. Crie `coletores/nova_fonte.py` com uma função `coletar()` que devolva um
   `ResultadoColeta`.
2. Registre-a no dicionário `FONTES` em `coletores/executar.py`.

Os coletores existentes servem de modelo — em especial `ibge.py`, que localiza
as variáveis pelo nome em vez de fixar identificadores numéricos, e por isso
sobrevive às revisões periódicas das pesquisas.

---

## Cadência das fontes

| Fonte | O que traz | Publicação |
|---|---|---|
| IBGE (agregados 6579 e 5938) | População estimada, PIB, PIB per capita, valor adicionado bruto | Anual |
| SICONFI — DCA | Receita e despesa orçamentárias do exercício | Anual, homologada no ano seguinte |
| SICONFI — RGF Anexo 01 | Despesa com pessoal sobre a Receita Corrente Líquida | Quadrimestral |
| Novo CAGED | Saldo, admissões e desligamentos por setor produtivo, desde 2021 | Mensal, com defasagem de 30 a 45 dias |
| `estoque_base.csv` | Âncora do estoque de vínculos ativos | Uma vez, ao instalar |
| INEP / IDEB | Anos iniciais, anos finais e ensino médio: Estrela, RS e Brasil, além do resultado de cada escola | Bienal |
| `manuais.csv` | Saúde e indicadores próprios da Prefeitura | Quando você editar |

---

## IDEB

Não há API. As planilhas de divulgação do INEP trazem, cada uma, a série
completa desde 2005 em colunas — a edição mais recente basta.

A cada divulgação (agosto dos anos ímpares; a vigente é a de 2025):

1. Baixe as planilhas em [Ideb — Resultados](https://www.gov.br/inep/pt-br/areas-de-atuacao/pesquisas-estatisticas-e-indicadores/ideb/resultados),
   nas três etapas e nos três âmbitos (municípios, escolas, Brasil e estados).
2. Deposite os arquivos em `dados/inep/` sem renomear.
3. Dispare o fluxo com `inep` no campo de fontes.

O conversor extrai as linhas de Estrela (redes municipal, estadual e pública),
do Rio Grande do Sul e do Brasil, além do resultado de cada escola do
município, e grava tudo em `dados/ideb.csv`. Feito isso, as planilhas podem ser
apagadas: o CSV é a fonte canônica e também pode ser editado à mão.

## Limitações conhecidas

- **CAGED.** Não existe API REST; o coletor lê os microdados em `.7z`
  publicados por FTP em `ftp.mtps.gov.br`. O arquivo mensal é nacional e a série
  começa em janeiro de 2021, de modo que a primeira execução é longa — o limite
  do fluxo está em 350 minutos. O cache é gravado a cada competência e o commit
  ocorre mesmo se a execução falhar, então basta disparar o fluxo de novo para
  retomar de onde parou. Depois da carga inicial, cada execução baixa apenas a
  competência nova. Se o Ministério alterar o layout, o log registra o cabeçalho
  encontrado.
- **Estoque de vínculos.** O CAGED registra movimentações, não estoque. A série
  é obtida ancorando-se numa data-base da RAIS e somando os saldos mensais
  seguintes — metodologia do próprio PDET. Preencha `dados/estoque_base.csv` com
  o número de vínculos ativos em 31/12 do ano anterior ao início da série
  (por padrão, 31/12/2020), total e por setor. Enquanto os valores forem zero, o
  painel simplesmente omite o estoque, sem quebrar.
- **SICONFI.** Os nomes das contas variam entre exercícios. Quando uma conta não
  é localizada, o log lista as contas disponíveis naquele ano — a correção é
  ajustar o trecho procurado em `siconfi.py`.
- **INEP.** O layout das planilhas muda entre edições. O conversor localiza o
  cabeçalho pela linha que contém os anos e classifica as colunas pelo bloco
  (Ideb ou projeções); se não reconhecer a estrutura, registra no log as
  primeiras linhas do arquivo, o que basta para o ajuste.
- **Validação em produção.** Os coletores foram escritos a partir da
  documentação oficial das APIs, mas ainda não foram executados contra os
  servidores dos órgãos. A primeira execução do workflow é o teste real; o log
  do Actions aponta com precisão qualquer ajuste necessário.

---

## Licença dos dados

Todos os indicadores provêm de bases públicas federais. As fontes são citadas
em cada cartão do painel, com o período de referência e a data da coleta.
