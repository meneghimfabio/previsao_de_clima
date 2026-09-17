#!/usr/bin/env python3
"""
Script de extração do histórico meteorológico consolidado (WeatherNext 2) para coordenadas da Atvos.
Intervalo: 01/julho/2026 a 17/setembro/2026.
Consolidação do passo de curto prazo (+6h) de cada rodada do modelo (análise/reanálise operacional).
Calcula média do ensemble, min, max e percentis (P10/P90) de temperatura, chuva e vento.
"""

import argparse
import csv
import os
import subprocess
import sys
import time

INPUT_CSV = "job_XJcmzX1bWl2iKTVPZI4vrmerGPmG.csv"
DEFAULT_OUTPUT_CSV = "dados_clima_atvos_historico_20260701_20260917.csv"
PROJECT_ID = "demonstracoes-fabio"
DATASET_ID = "weathernext_2"
TABLE_ID = "weathernext_2_0_0"

def load_coordinates(csv_path):
    points = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            points.append({
                "picId": r["picId"],
                "clientId": r["clientId"],
                "name": r["name"],
                "unidade": r["unidade"],
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "quantidade_linhas_unidade": r.get("quantidade_linhas_unidade", "")
            })
    return points

def build_query(points, start_date="2026-07-01", end_date="2026-09-17"):
    struct_literals = []
    for p in points:
        glat = round(p["lat"] * 4) / 4.0
        glon = round(p["lon"] * 4) / 4.0
        struct_literals.append(
            f"STRUCT('{p['picId']}' as picId, '{p['clientId']}' as clientId, '{p['name']}' as name, "
            f"'{p['unidade']}' as unidade, {p['lat']} as lat, {p['lon']} as lon, "
            f"'{p['quantidade_linhas_unidade']}' as quantidade_linhas_unidade, "
            f"{glon} as grid_lon, {glat} as grid_lat)"
        )
    unnest_sql = ",\n    ".join(struct_literals)

    sql = f"""
    CREATE TEMP TABLE points AS
    SELECT * FROM UNNEST([
        {unnest_sql}
    ]);

    CREATE TEMP TABLE distinct_cells AS
    SELECT DISTINCT grid_lon, grid_lat
    FROM points;

    CREATE TEMP TABLE weather_extracted AS
    SELECT 
      w.init_time,
      dc.grid_lon,
      dc.grid_lat,
      f.hours,
      f.time as valid_time,
      e.ensemble_member,
      (e.`2m_temperature` - 273.15) as temp_c,
      GREATEST(0.0, e.total_precipitation_6hr * 1000) as rain_mm,
      SQRT(POW(e.`10m_u_component_of_wind`, 2) + POW(e.`10m_v_component_of_wind`, 2)) as wind_ms,
      e.mean_sea_level_pressure as pressure_pa
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` w
    JOIN distinct_cells dc 
      ON ST_DWITHIN(w.geography, ST_GEOGPOINT(dc.grid_lon, dc.grid_lat), 500)
    CROSS JOIN UNNEST(w.forecast) as f
    CROSS JOIN UNNEST(f.ensemble) as e
    WHERE w.init_time >= '{start_date} 00:00:00' 
      AND w.init_time <= '{end_date} 23:59:59'
      AND f.hours = 6;

    SELECT 
      p.picId,
      p.clientId,
      p.name,
      p.unidade,
      p.lat,
      p.lon,
      w.init_time as rodada_init_time,
      w.valid_time as data_hora_observacao,
      ROUND(AVG(w.temp_c), 2) as temp_media_c,
      ROUND(MIN(w.temp_c), 2) as temp_min_c,
      ROUND(MAX(w.temp_c), 2) as temp_max_c,
      ROUND(AVG(w.rain_mm), 3) as precipitacao_6h_media_mm,
      ROUND(MAX(w.rain_mm), 3) as precipitacao_6h_max_mm,
      ROUND(AVG(w.wind_ms), 2) as vento_medio_ms,
      ROUND(MAX(w.wind_ms), 2) as vento_rajada_max_ms,
      ROUND(AVG(w.pressure_pa), 1) as pressao_mar_pa
    FROM weather_extracted w
    JOIN points p 
      ON w.grid_lon = p.grid_lon AND w.grid_lat = p.grid_lat
    GROUP BY 
      p.picId, p.clientId, p.name, p.unidade, p.lat, p.lon, 
      w.init_time, w.valid_time
    ORDER BY 
      w.valid_time, p.unidade, p.name;
    """
    return sql

def main():
    parser = argparse.ArgumentParser(description="Extração de histórico meteorológico WeatherNext 2")
    parser.add_argument("--start", type=str, default="2026-07-01", help="Data de início (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2026-09-17", help="Data de término (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT_CSV, help="Caminho do CSV de saída")
    args = parser.parse_args()

    print(f"Lendo coordenadas de {INPUT_CSV}...")
    points = load_coordinates(INPUT_CSV)
    print(f"Total de {len(points)} pontos carregados.")

    query = build_query(points, args.start, args.end)
    query_file = "temp_hist_query.sql"
    with open(query_file, "w", encoding="utf-8") as f:
        f.write(query)

    print(f"Executando extração no BigQuery para o intervalo {args.start} a {args.end}...")
    cmd = [
        "bq", "query",
        "--use_legacy_sql=false",
        "--max_rows=1000000",
        "--format=csv"
    ]

    start_time = time.time()
    with open(query_file, "r", encoding="utf-8") as in_f:
        res = subprocess.run(cmd, stdin=in_f, capture_output=True, text=True)
    
    elapsed = time.time() - start_time
    if res.returncode != 0:
        print("Erro ao executar consulta BigQuery:", file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        sys.exit(1)

    lines = res.stdout.splitlines()
    header_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("picId,clientId,"):
            header_idx = idx
            break

    if header_idx == -1:
        print("Aviso: cabeçalho não encontrado nos dados retornados!", file=sys.stderr)
        print("\n".join(lines[:20]), file=sys.stderr)
        sys.exit(1)

    data_lines = lines[header_idx:]
    with open(args.output, "w", encoding="utf-8") as out_f:
        out_f.write("\n".join(data_lines) + "\n")

    total_records = len(data_lines) - 1
    file_size_mb = os.path.getsize(args.output) / (1024 * 1024)
    print(f"Sucesso! {total_records:,} registros gravados em '{args.output}' ({file_size_mb:.2f} MB) em {elapsed:.1f}s.")

    if os.path.exists(query_file):
        os.remove(query_file)

if __name__ == "__main__":
    main()
