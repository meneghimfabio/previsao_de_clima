#!/usr/bin/env python3
"""
Script de extração de previsão meteorológica (WeatherNext 2) para coordenadas da Atvos.
Gera um arquivo CSV com as previsões detalhadas por membro do ensemble.
"""

import csv
import json
import os
import subprocess
import sys
import time

INPUT_CSV = "job_XJcmzX1bWl2iKTVPZI4vrmerGPmG.csv"
OUTPUT_CSV = "previsao_clima_atvos_latest.csv"
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
                "quantidade_linhas_unidade": r["quantidade_linhas_unidade"]
            })
    return points

def get_latest_init_time():
    query = f"""
    SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(init_time)) as latest_init
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
    WHERE DATE(init_time) = CURRENT_DATE() OR DATE(init_time) = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    """
    cmd = [
        "bq", "query",
        "--use_legacy_sql=false",
        "--format=csv",
        query
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    # header is 'latest_init', second line is timestamp
    if len(lines) >= 2:
        return lines[1]
    raise RuntimeError(f"Não foi possível obter init_time recente: {res.stdout}")

def build_query(points, latest_init_time):
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
      w.forecast
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` w
    JOIN distinct_cells dc 
      ON ST_DWITHIN(w.geography, ST_GEOGPOINT(dc.grid_lon, dc.grid_lat), 500)
    WHERE w.init_time = '{latest_init_time}';

    SELECT 
      p.picId,
      p.clientId,
      p.name,
      p.unidade,
      p.quantidade_linhas_unidade,
      p.lat,
      p.lon,
      w.init_time,
      f.hours as forecast_horizon_hours,
      f.time as forecast_timestamp,
      e.ensemble_member,
      ROUND(e.`2m_temperature` - 273.15, 2) as temperature_c,
      GREATEST(0.0, ROUND(e.total_precipitation_6hr * 1000, 3)) as precipitation_6hr_mm,
      ROUND(SQRT(POW(e.`10m_u_component_of_wind`, 2) + POW(e.`10m_v_component_of_wind`, 2)), 2) as wind_speed_10m_ms,
      ROUND(e.mean_sea_level_pressure, 1) as sea_level_pressure_pa
    FROM weather_extracted w
    JOIN points p 
      ON w.grid_lon = p.grid_lon AND w.grid_lat = p.grid_lat
    CROSS JOIN UNNEST(w.forecast) as f
    CROSS JOIN UNNEST(f.ensemble) as e
    ORDER BY p.unidade, p.name, f.hours, CAST(e.ensemble_member AS INT64);
    """
    return sql

def main():
    print(f"Lendo coordenadas de {INPUT_CSV}...")
    points = load_coordinates(INPUT_CSV)
    print(f"Total de {len(points)} pontos carregados.")

    print("Buscando última rodada (init_time) disponível no BigQuery...")
    latest_init = get_latest_init_time()
    print(f"Última rodada detectada: {latest_init}")

    query = build_query(points, latest_init)
    query_file = "temp_query.sql"
    with open(query_file, "w", encoding="utf-8") as f:
        f.write(query)

    print("Executando consulta otimizada no BigQuery e gerando CSV...")
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

    print("Filtrando e gravando resultado no CSV de destino...")
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
    with open(OUTPUT_CSV, "w", encoding="utf-8") as out_f:
        out_f.write("\n".join(data_lines) + "\n")

    total_records = len(data_lines) - 1
    print(f"Sucesso! {total_records:,} linhas exportadas para '{OUTPUT_CSV}' em {elapsed:.1f}s.")

    if os.path.exists(query_file):
        os.remove(query_file)

if __name__ == "__main__":
    main()
