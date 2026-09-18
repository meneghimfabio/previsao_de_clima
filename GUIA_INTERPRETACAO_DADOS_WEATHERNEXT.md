# 🌦️ Guia de Interpretação dos Dados de Previsão de Clima (WeatherNext 2)

Este guia documenta a estrutura, o significado e as práticas recomendadas para interpretar os dados gerados pelo modelo de inteligência artificial **Google DeepMind WeatherNext 2** contidos no arquivo [`previsao_clima_atvos_latest.csv`](previsao_clima_atvos_latest.csv) e tabelas associadas no Google Cloud BigQuery.

---

## 1. O que é um Ensemble Meteorológico?

Na meteorologia tradicional (modelos determinísticos como GFS ou ECMWF convencional), o supercomputador processa **apenas uma simulação atmosférica**. Contudo, como a atmosfera é um sistema dinâmico não-linear altamente sensível às condições iniciais (o famoso *"efeito borboleta"*), uma mínima incerteza na medição de temperatura ou pressão pode fazer com que uma previsão determinística falhe significativamente após o 4º ou 5º dia, sem dar pistas do grau de confiança.

Um **Ensemble (Conjunto de Previsão)** resolve essa limitação rodando **dezenas de simulações paralelas** a partir da mesma rodada de análise, introduzindo pequenas e realistas perturbações nas condições iniciais e nos parâmetros físicos:

* **O Modelo WeatherNext 2** gera **64 membros simultâneos** (`ensemble_member` indexados de `0` a `63`).
  * O membro `0` geralmente representa o cenário de controle operacional (sem perturbação).
  * Os membros `1` a `63` representam cenários atmosféricos alternativos fisicamente coerentes.

### Por que o Ensemble é Estratégico para a Atvos?
1. **Quantificação da Incerteza e Confiabilidade:**  
   Se todos os 64 membros indicam chuva em um polo no 4º dia, a **probabilidade e confiança são altíssimas**. Por outro lado, se apenas 15 dos 64 membros apontam chuva, a operação sabe que existe um risco de chuva isolada, mas não um evento generalizado.
2. **Tomada de Decisão Baseada em Riscos (Matriz Operacional):**  
   Permite balancear decisões para colheita mecânica, queima controlada de cana-de-açúcar, aplicação aérea/terrestre de defensivos, transporte e manutenção preventiva de estradas de terra antes de precipitações volumosas.

---

## 2. Dicionário de Dados do CSV

Cada linha do arquivo [`previsao_clima_atvos_latest.csv`](previsao_clima_atvos_latest.csv) representa a projeção de **um único membro do ensemble** para **um talhão específico** em **um horizonte temporal específico**:

| Coluna | Tipo | Descrição | Aplicação Prática no Agronegócio |
| :--- | :---: | :--- | :--- |
| **`picId`** | Inteiro | Identificador PIC do talhão | Chave primária de integração com os sistemas GIS/ERP agrícolas da Atvos. |
| **`clientId`** | Inteiro | Identificador do cliente Atvos | Identificador cadastral da conta/empresa. |
| **`name`** | String | Código/Nome do ponto ou talhão | Ex: `UAE_440010`. Identifica a localização geográfica exata monitorada. |
| **`unidade`** | String | Polo operacional / Unidade Atvos | Um dos 8 polos industriais: `UAE`, `UAT`, `UCP`, `UCR`, `UEL`, `UMV`, `URC`, `USL`. |
| **`quantidade_linhas_unidade`** | Inteiro | Total de pontos daquela unidade | Informa a densidade de monitoramento do polo no conjunto de dados. |
| **`lat` / `lon`** | Float | Coordenadas Geográficas (Graus Decimais) | Coordenadas WGS84 para renderização em mapas e cruzamento geoespacial. |
| **`init_time`** | Timestamp | Rodada de Inicialização do Modelo | Horário em que o modelo DeepMind foi rodado com dados globais observados (ex: `2026-09-17 06:00:00`). |
| **`forecast_horizon_hours`** | Inteiro | Horizonte da Previsão (+h) | Quantidade de horas à frente a partir de `init_time` (passos de **6 em 6 horas**, de `6h` a `360h` = **15 dias**). |
| **`forecast_timestamp`** | Timestamp | Data e Hora Válida da Previsão | Momento exato em que o clima previsto irá ocorrer (`forecast_timestamp = init_time + forecast_horizon_hours`). |
| **`ensemble_member`** | Inteiro | Membro do Ensemble (`0` a `63`) | Identificador do membro entre as 64 trajetórias simuladas em paralelo. |
| **`temperature_c`** | Float | Temperatura do Ar a 2m (°C) | Temperatura estimada a 2 metros de altura do solo. |
| **`precipitation_6hr_mm`** | Float | Chuva Acumulada em 6 horas (mm) | Volume total de precipitação esperado **no intervalo das 6 horas anteriores** àquele timestamp. |
| **`wind_speed_10m_ms`** | Float | Velocidade do Vento a 10m (m/s) | Módulo do vento a 10m de altura. **Para converter em km/h:** multiplique por `3.6` (ex: `5.0 m/s = 18.0 km/h`). |
| **`sea_level_pressure_pa`** | Float | Pressão ao Nível do Mar (Pa) | Pressão atmosférica em Pascal (`101325 Pa = 1 atm = 1013.25 hPa`). Quedas bruscas sinalizam aproximação de tempestades. |

---

## 3. Como Agregar e Extrair Métricas de Negócio

Como cada instante de tempo possui 64 projeções simultâneas para cada ponto, você pode calcular métricas probabilísticas fundamentais:

### A. Previsão Mais Provável (Média do Ensemble)
Para obter o cenário central esperado para cada talhão ao longo do tempo:
$$\text{Chuva Média} = \frac{1}{64} \sum_{i=0}^{63} \text{precipitation\_6hr\_mm}_i$$
$$\text{Temperatura Média} = \frac{1}{64} \sum_{i=0}^{63} \text{temperature\_c}_i$$

### B. Faixa de Incerteza (Percentis P10 e P90)
* **P10 (Cenário Conservador / Mínimo Plausível):** 10% dos membros previram valores abaixo deste patamar.
* **P90 (Cenário Crítico / Máximo Plausível):** 90% dos membros previram valores abaixo deste patamar (ou 10% previram acima).
* **Interpretação:** A área delimitada entre P10 e P90 compreende **80% de todas as simulações possíveis**. Se a faixa for estreita, a confiança na previsão é alta; se for larga, há alta divergência entre os cenários.

### C. Probabilidade de Ocorrência de Chuva (PoP)
A probabilidade estatística de que ocorra chuva perceptível (ex: $\ge 1.0\text{ mm}$ ou $\ge 5.0\text{ mm}$) em 6 horas é calculada pela fração dos 64 membros:
$$\text{PoP (\%)} = \left( \frac{\text{Contagem de membros com } \text{precipitation\_6hr\_mm} \ge 1.0}{64} \right) \times 100$$

*Exemplo:* Se 48 dos 64 membros projetam mais de 1 mm de chuva no talhão, a **probabilidade de chuva é de 75%**.

### D. Cenário de Pior Caso (Rajadas e Chuva Extrema)
Para operações sensíveis a vento e temporais (ex: pulverização aérea e segurança de máquinas pesadas), analisa-se:
* $\max(\text{wind\_speed\_10m\_ms})$ entre os 64 membros (rajada máxima potencial).
* $\max(\text{precipitation\_6hr\_mm})$ entre os 64 membros (pico máximo de chuva acumulada).

---

## 4. Comparativo: Arquivo de Previsão vs Arquivo de Histórico

| Atributo | [`previsao_clima_atvos_latest.csv`](previsao_clima_atvos_latest.csv) | [`dados_clima_atvos_historico_20260701_20260917.csv`](dados_clima_atvos_historico_20260701_20260917.csv) |
| :--- | :--- | :--- |
| **Finalidade** | Projeção futura (15 dias à frente) | Série temporal histórica observada / reanálise |
| **Estrutura** | Granular por membro individual (64 linhas por timestamp) | Consolidada (Média, Mín, Máx já agregadas por timestamp) |
| **Passo Temporal** | Horizontes de +6h até +360h | Passo de análise operacional (+6h de cada rodada diária) |
| **Horizonte** | Rodada de 17/09/2026 projetando até 02/10/2026 | 01/07/2026 a 17/09/2026 (79 dias contínuos) |
| **Total de Linhas** | ~600.000 linhas | 49.455 linhas |
