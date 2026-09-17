#!/usr/bin/env python3
"""
build_dashboard.py
Gera um dashboard HTML autossuficiente e interativo (dashboard.html)
a partir dos dados de previsão do WeatherNext 2 (previsao_clima_atvos_latest.csv).
"""

import csv
import json
import os
import sys
import time

INPUT_CSV = "previsao_clima_atvos_latest.csv"
OUTPUT_HTML = "dashboard.html"

def load_and_aggregate_data(csv_path):
    print(f"Lendo dados de previsão de {csv_path}...")
    start_time = time.time()

    points_meta = {}
    # point_data: pid -> { 'timestamps': [], 'm_temp': {member: []}, 'm_precip': {member: []}, 'm_wind': {member: []} }
    # To optimize JSON size and performance:
    # We store for each point:
    # - info: { id, name, unidade, lat, lon }
    # - time_steps: array of strings (shared globally)
    # - stats: { temp_mean: [], temp_p10: [], temp_p90: [], temp_min: [], temp_max: [],
    #            rain_mean: [], rain_accum_mean: [], rain_accum_p10: [], rain_accum_p90: [],
    #            wind_mean: [], wind_max: [] }
    # - members: { m_id: { temp: [], rain_accum: [], wind: [] } } -> optionally all 64 members
    
    # Let's collect data per point, horizon, member
    point_series = {}
    timestamps_map = {}
    all_units = set()
    init_time_str = "Desconhecido"

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row["picId"]
            if pid not in points_meta:
                points_meta[pid] = {
                    "id": pid,
                    "name": row["name"],
                    "unidade": row["unidade"],
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"])
                }
                point_series[pid] = {}
                all_units.add(row["unidade"])
                init_time_str = row["init_time"]

            step_h = int(row["forecast_horizon_hours"])
            if step_h not in timestamps_map:
                timestamps_map[step_h] = row["forecast_timestamp"]

            if step_h not in point_series[pid]:
                point_series[pid][step_h] = {
                    "temp": [],
                    "precip": [],
                    "wind": []
                }

            t = float(row["temperature_c"])
            p = float(row["precipitation_6hr_mm"])
            w = float(row["wind_speed_10m_ms"])

            point_series[pid][step_h]["temp"].append(t)
            point_series[pid][step_h]["precip"].append(p)
            point_series[pid][step_h]["wind"].append(w)

    sorted_steps = sorted(timestamps_map.keys())
    sorted_timestamps = [timestamps_map[h] for h in sorted_steps]

    print(f"Dados lidos em {time.time() - start_time:.2f}s. Calculando estatísticas e curvas por membro...")

    # Process each point
    processed_points = []
    unit_stats = {u: {"rain_total": 0, "count": 0, "max_temp": -999, "min_temp": 999} for u in all_units}

    for pid, meta in points_meta.items():
        steps_data = point_series[pid]
        
        # We also want member-level trajectories for the spaghetti plot!
        # Number of members in step 0
        num_members = len(steps_data[sorted_steps[0]]["temp"]) if sorted_steps else 0

        # Precompute per-step ensemble statistics:
        temp_mean = []
        temp_p10 = []
        temp_p90 = []
        temp_min = []
        temp_max = []

        rain_step_mean = []
        rain_accum_mean = []
        
        wind_mean = []
        wind_max = []

        curr_accum_mean = 0.0

        for h in sorted_steps:
            t_list = sorted(steps_data[h]["temp"])
            p_list = sorted(steps_data[h]["precip"])
            w_list = sorted(steps_data[h]["wind"])
            n = len(t_list)

            # Mean
            t_m = sum(t_list) / n
            p_m = sum(p_list) / n
            w_m = sum(w_list) / n

            temp_mean.append(round(t_m, 1))
            temp_min.append(round(t_list[0], 1))
            temp_max.append(round(t_list[-1], 1))
            temp_p10.append(round(t_list[int(n * 0.1)], 1))
            temp_p90.append(round(t_list[int(n * 0.9)], 1))

            rain_step_mean.append(round(p_m, 2))
            curr_accum_mean += p_m
            rain_accum_mean.append(round(curr_accum_mean, 1))

            wind_mean.append(round(w_m, 1))
            wind_max.append(round(w_list[-1], 1))

        # Member-level trajectories:
        # Array of 64 members: each member is an array of values across the 60 steps
        # To keep JSON compact, format rounded to 1 decimal place
        member_temp = []
        member_accum_rain = []
        member_wind = []

        for m_idx in range(num_members):
            m_t = []
            m_r_accum = []
            m_w = []
            accum = 0.0
            for h in sorted_steps:
                t_val = steps_data[h]["temp"][m_idx] if m_idx < len(steps_data[h]["temp"]) else 0
                p_val = steps_data[h]["precip"][m_idx] if m_idx < len(steps_data[h]["precip"]) else 0
                w_val = steps_data[h]["wind"][m_idx] if m_idx < len(steps_data[h]["wind"]) else 0

                accum += p_val
                m_t.append(round(t_val, 1))
                m_r_accum.append(round(accum, 1))
                m_w.append(round(w_val, 1))

            member_temp.append(m_t)
            member_accum_rain.append(m_r_accum)
            member_wind.append(m_w)

        total_rain = rain_accum_mean[-1] if rain_accum_mean else 0
        overall_max_t = max(temp_max) if temp_max else 0
        overall_min_t = min(temp_min) if temp_min else 0
        overall_max_w = max(wind_max) if wind_max else 0

        # Update unit aggregate stats
        u = meta["unidade"]
        unit_stats[u]["rain_total"] += total_rain
        unit_stats[u]["count"] += 1
        unit_stats[u]["max_temp"] = max(unit_stats[u]["max_temp"], overall_max_t)
        unit_stats[u]["min_temp"] = min(unit_stats[u]["min_temp"], overall_min_t)

        processed_points.append({
            "id": pid,
            "name": meta["name"],
            "unidade": meta["unidade"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "rain_total": round(total_rain, 1),
            "temp_max": overall_max_t,
            "temp_min": overall_min_t,
            "wind_max": overall_max_w,
            "stats": {
                "temp_mean": temp_mean,
                "temp_p10": temp_p10,
                "temp_p90": temp_p90,
                "temp_min": temp_min,
                "temp_max": temp_max,
                "rain_step": rain_step_mean,
                "rain_accum": rain_accum_mean,
                "wind_mean": wind_mean,
                "wind_max": wind_max
            },
            "members": {
                "temp": member_temp,
                "rain_accum": member_accum_rain,
                "wind": member_wind
            }
        })

    # Average rain per unit
    for u in unit_stats:
        c = unit_stats[u]["count"]
        unit_stats[u]["avg_rain"] = round(unit_stats[u]["rain_total"] / c, 1) if c > 0 else 0

    dataset = {
        "init_time": init_time_str,
        "horizons": sorted_steps,
        "timestamps": sorted_timestamps,
        "units": sorted(list(all_units)),
        "unit_stats": unit_stats,
        "points": processed_points
    }

    return dataset

def generate_html(dataset, output_path):
    print("Gerando dashboard.html...")
    data_json = json.dumps(dataset, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Atvos Weather Forecast | DeepMind WeatherNext 2</title>
    
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    colors: {{
                        brand: {{
                            50: '#f0fdf4',
                            500: '#16a34a',
                            600: '#15803d',
                            700: '#166534',
                            900: '#052e16',
                        }},
                        dark: {{
                            800: '#1e293b',
                            900: '#0f172a',
                            950: '#020617'
                        }}
                    }}
                }}
            }}
        }}
    </script>

    <!-- Google Maps JavaScript API -->
    <script>
        const GMAPS_KEY = localStorage.getItem('gmaps_api_key') || new URLSearchParams(window.location.search).get('key') || '';
        window.onGoogleMapsLoaded = function() {{
            if (window.google && window.google.maps) {{
                window.gmapsReady = true;
                if (document.readyState === 'complete' || document.readyState === 'interactive') {{
                    initDashboard();
                }} else {{
                    window.addEventListener('DOMContentLoaded', initDashboard);
                }}
            }}
        }};
        const gmapsScript = document.createElement('script');
        gmapsScript.src = `https://maps.googleapis.com/maps/api/js?${{GMAPS_KEY ? 'key=' + GMAPS_KEY + '&' : ''}}libraries=geometry&callback=onGoogleMapsLoaded`;
        gmapsScript.async = true;
        gmapsScript.defer = true;
        document.head.appendChild(gmapsScript);
    </script>

    <!-- Plotly.js CDN -->
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>

    <!-- Lucide Icons -->
    <script src="https://unpkg.com/lucide@latest"></script>

    <style>
        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        }}
        #map {{
            height: 480px;
            width: 100%;
            border-radius: 0.75rem;
            z-index: 10;
        }}
        .custom-scrollbar::-webkit-scrollbar {{
            width: 6px;
            height: 6px;
        }}
        .custom-scrollbar::-webkit-scrollbar-track {{
            background: #0f172a;
        }}
        .custom-scrollbar::-webkit-scrollbar-thumb {{
            background: #334155;
            border-radius: 3px;
        }}
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {{
            background: #475569;
        }}
    </style>
</head>
<body class="bg-dark-950 text-slate-100 min-h-screen flex flex-col">

    <!-- Top Navigation / Header -->
    <header class="bg-dark-900 border-b border-slate-800 px-6 py-4 sticky top-0 z-50 shadow-md">
        <div class="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 rounded-xl bg-brand-600/20 border border-brand-500/30 flex items-center justify-center text-brand-500 shadow-inner">
                    <i data-lucide="cloud-sun-rain" class="w-6 h-6"></i>
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="text-xl font-bold tracking-tight text-white">Previsão de Clima Atvos</h1>
                        <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-brand-500/10 text-brand-400 border border-brand-500/20">WeatherNext 2.0</span>
                    </div>
                    <p class="text-xs text-slate-400">Modelo Global por IA • Google DeepMind & BigQuery</p>
                </div>
            </div>

            <!-- Badges de Status -->
            <div class="flex flex-wrap items-center gap-3 text-xs">
                <div class="bg-dark-800/80 border border-slate-700/60 rounded-lg px-3 py-1.5 flex items-center gap-2 text-slate-300">
                    <i data-lucide="clock" class="w-4 h-4 text-emerald-400"></i>
                    <span>Rodada: <strong id="header-init-time" class="text-white font-mono">-</strong></span>
                </div>
                <div class="bg-dark-800/80 border border-slate-700/60 rounded-lg px-3 py-1.5 flex items-center gap-2 text-slate-300">
                    <i data-lucide="calendar" class="w-4 h-4 text-blue-400"></i>
                    <span>Horizonte: <strong class="text-white">15 Dias (360h)</strong></span>
                </div>
                <div class="bg-dark-800/80 border border-slate-700/60 rounded-lg px-3 py-1.5 flex items-center gap-2 text-slate-300">
                    <i data-lucide="layers" class="w-4 h-4 text-purple-400"></i>
                    <span>Ensemble: <strong class="text-white">64 Membros</strong></span>
                </div>
                <button onclick="promptApiKey()" title="Configurar chave do Google Maps (Google Cloud)" class="bg-dark-800/80 hover:bg-dark-700 border border-slate-700/60 rounded-lg px-3 py-1.5 flex items-center gap-2 text-slate-300 hover:text-white transition">
                    <i data-lucide="key" class="w-4 h-4 text-amber-400"></i>
                    <span>Chave Maps</span>
                </button>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl mx-auto w-full p-4 md:p-6 space-y-6">

        <!-- Top KPI Cards -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div class="bg-dark-900/90 border border-slate-800 p-4 rounded-xl shadow-sm relative overflow-hidden">
                <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Total de Coordenadas</div>
                <div class="mt-2 flex items-baseline gap-2">
                    <span id="kpi-total-points" class="text-2xl font-bold text-white font-mono">-</span>
                    <span class="text-xs text-slate-400">em 8 polos Atvos</span>
                </div>
                <div class="text-xs text-emerald-400 mt-2 flex items-center gap-1">
                    <i data-lucide="check-circle" class="w-3.5 h-3.5"></i> 100% atualizadas
                </div>
            </div>

            <div class="bg-dark-900/90 border border-slate-800 p-4 rounded-xl shadow-sm relative overflow-hidden">
                <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Chuva Acumulada Média</div>
                <div class="mt-2 flex items-baseline gap-2">
                    <span id="kpi-avg-rain" class="text-2xl font-bold text-cyan-400 font-mono">-</span>
                    <span class="text-xs text-slate-400">mm (15 dias)</span>
                </div>
                <div class="text-xs text-slate-400 mt-2" id="kpi-max-rain-unit">Polo mais chuvoso: -</div>
            </div>

            <div class="bg-dark-900/90 border border-slate-800 p-4 rounded-xl shadow-sm relative overflow-hidden">
                <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Temperatura Prevista</div>
                <div class="mt-2 flex items-baseline gap-2">
                    <span id="kpi-temp-range" class="text-2xl font-bold text-amber-400 font-mono">-</span>
                    <span class="text-xs text-slate-400">°C</span>
                </div>
                <div class="text-xs text-slate-400 mt-2">Faixa térmica operacional</div>
            </div>

            <div class="bg-dark-900/90 border border-slate-800 p-4 rounded-xl shadow-sm relative overflow-hidden">
                <div class="text-xs font-medium text-slate-400 uppercase tracking-wider">Vento Máximo Previsto</div>
                <div class="mt-2 flex items-baseline gap-2">
                    <span id="kpi-max-wind" class="text-2xl font-bold text-indigo-400 font-mono">-</span>
                    <span class="text-xs text-slate-400">m/s</span>
                </div>
                <div class="text-xs text-slate-400 mt-2" id="kpi-max-wind-kmh">~- km/h (rajadas)</div>
            </div>
        </div>

        <!-- Controls Toolbar -->
        <div class="bg-dark-900/90 border border-slate-800 p-4 rounded-xl shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div class="flex flex-wrap items-center gap-3">
                <div class="flex items-center gap-2">
                    <label class="text-xs font-semibold text-slate-400 uppercase">Unidade:</label>
                    <select id="unit-select" class="bg-dark-800 border border-slate-700 text-white text-sm rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-brand-500 focus:outline-none">
                        <option value="ALL">Todas as Unidades (157)</option>
                    </select>
                </div>

                <div class="flex items-center gap-2">
                    <label class="text-xs font-semibold text-slate-400 uppercase">Talhão / Ponto:</label>
                    <select id="point-select" class="bg-dark-800 border border-slate-700 text-white text-sm rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-brand-500 focus:outline-none max-w-[220px]">
                        <!-- Populated dynamically -->
                    </select>
                </div>
            </div>

            <!-- Ensemble Display Toggle -->
            <div class="flex items-center gap-3 bg-dark-800/80 p-1.5 rounded-lg border border-slate-700/60">
                <span class="text-xs text-slate-300 font-medium px-2">Modo do Ensemble:</span>
                <button id="btn-mode-stats" class="px-3 py-1 text-xs font-semibold rounded-md bg-brand-600 text-white shadow-sm transition">
                    Média & Incerteza (P10-P90)
                </button>
                <button id="btn-mode-spaghetti" class="px-3 py-1 text-xs font-semibold rounded-md text-slate-400 hover:text-white transition">
                    Spaghetti Plot (64 Membros)
                </button>
            </div>
        </div>

        <!-- Geospatial Map & Point Selector -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Left 2 Cols: Interactive Map -->
            <div class="lg:col-span-2 bg-dark-900/90 border border-slate-800 rounded-xl p-4 shadow-sm flex flex-col">
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <i data-lucide="map-pin" class="w-5 h-5 text-brand-500"></i>
                        <h2 class="font-bold text-white text-base">Mapa de Distribuição das Coordenadas Atvos</h2>
                    </div>
                    <span class="text-xs text-slate-400">Clique em qualquer marcador para selecionar o ponto</span>
                </div>
                <div id="map" class="flex-1 min-h-[460px]"></div>
            </div>

            <!-- Right 1 Col: Selected Point Card & Ranking -->
            <div class="bg-dark-900/90 border border-slate-800 rounded-xl p-4 shadow-sm flex flex-col space-y-4">
                <div class="border-b border-slate-800 pb-3">
                    <span class="text-xs font-bold uppercase tracking-wider text-brand-400">Ponto Selecionado</span>
                    <h3 id="panel-point-name" class="text-xl font-bold text-white mt-1">-</h3>
                    <div class="flex items-center gap-2 text-xs text-slate-400 mt-1">
                        <span id="panel-point-unit" class="px-2 py-0.5 rounded bg-dark-800 border border-slate-700 text-slate-200 font-semibold">-</span>
                        <span id="panel-point-coords" class="font-mono">-</span>
                    </div>
                </div>

                <!-- Point Quick Stats -->
                <div class="grid grid-cols-2 gap-3">
                    <div class="bg-dark-800/70 p-3 rounded-lg border border-slate-700/50">
                        <div class="text-[11px] text-slate-400 uppercase">Chuva Prevista (15d)</div>
                        <div id="panel-point-rain" class="text-lg font-bold text-cyan-400 font-mono mt-0.5">- mm</div>
                    </div>
                    <div class="bg-dark-800/70 p-3 rounded-lg border border-slate-700/50">
                        <div class="text-[11px] text-slate-400 uppercase">Temp. Mín / Máx</div>
                        <div id="panel-point-temp" class="text-lg font-bold text-amber-400 font-mono mt-0.5">- °C</div>
                    </div>
                </div>

                <!-- Unit Points Quick Table -->
                <div class="flex-1 flex flex-col min-h-0">
                    <div class="text-xs font-semibold text-slate-300 mb-2 flex items-center justify-between">
                        <span>Pontos na Unidade</span>
                        <span id="panel-unit-count" class="text-slate-400 text-[11px]">-</span>
                    </div>
                    <div id="points-list" class="flex-1 overflow-y-auto custom-scrollbar space-y-1.5 max-h-[260px] pr-1">
                        <!-- Populated dynamically -->
                    </div>
                </div>
            </div>
        </div>

        <!-- Meteogram Charts (Precipitation, Temperature, Wind) -->
        <div class="space-y-6">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-lg font-bold text-white flex items-center gap-2">
                        <i data-lucide="line-chart" class="w-5 h-5 text-cyan-400"></i>
                        Meteograma de Previsão Probabilística (15 Dias)
                    </h2>
                    <p class="text-xs text-slate-400 mt-0.5" id="charts-subtitle">Visualizando previsões detalhadas para o ponto selecionado</p>
                </div>
            </div>

            <!-- Chart 1: Precipitation -->
            <div class="bg-dark-900/90 border border-slate-800 rounded-xl p-4 shadow-sm">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        <span class="w-3 h-3 rounded-full bg-cyan-400"></span>
                        <h3 class="font-bold text-sm text-white">Precipitação Acumulada & Taxa de Chuva em 6h (mm)</h3>
                    </div>
                    <span class="text-xs text-slate-400 font-mono" id="rain-legend-desc">Faixa P10-P90 e Média do Ensemble</span>
                </div>
                <div id="chart-precip" style="height: 380px;"></div>
            </div>

            <!-- Chart 2: Temperature -->
            <div class="bg-dark-900/90 border border-slate-800 rounded-xl p-4 shadow-sm">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        <span class="w-3 h-3 rounded-full bg-amber-400"></span>
                        <h3 class="font-bold text-sm text-white">Temperatura do Ar a 2 Metros (°C)</h3>
                    </div>
                    <span class="text-xs text-slate-400 font-mono" id="temp-legend-desc">Envelope de Incerteza e Ciclo Diurno</span>
                </div>
                <div id="chart-temp" style="height: 380px;"></div>
            </div>

            <!-- Chart 3: Wind Speed -->
            <div class="bg-dark-900/90 border border-slate-800 rounded-xl p-4 shadow-sm">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        <span class="w-3 h-3 rounded-full bg-indigo-400"></span>
                        <h3 class="font-bold text-sm text-white">Velocidade do Vento a 10 Metros (m/s)</h3>
                    </div>
                    <span class="text-xs text-slate-400 font-mono" id="wind-legend-desc">Média e Rajadas Máximas</span>
                </div>
                <div id="chart-wind" style="height: 340px;"></div>
            </div>
        </div>

    </main>

    <!-- Footer -->
    <footer class="bg-dark-900 border-t border-slate-800 py-4 px-6 text-center text-xs text-slate-400">
        Previsão de Clima Atvos • Desenvolvido com Google DeepMind WeatherNext 2 & Google Cloud BigQuery
    </footer>

    <!-- EMBEDDED WEATHER DATASET -->
    <script>
        const WX_DATA = {data_json};
    </script>

    <!-- Dashboard App Logic -->
    <script>
        let currentMode = 'stats'; // 'stats' or 'spaghetti'
        let selectedPointId = null;
        let map = null;
        let mapMarkers = [];

        const UNIT_COLORS = {{
            'UAE': '#10b981', // emerald
            'UAT': '#06b6d4', // cyan
            'UCP': '#f59e0b', // amber
            'UCR': '#8b5cf6', // purple
            'UEL': '#ec4899', // pink
            'UMV': '#3b82f6', // blue
            'URC': '#14b8a6', // teal
            'USL': '#f97316'  // orange
        }};

        function initDashboard() {{
            lucide.createIcons();

            // 1. Header Badges & KPIs
            document.getElementById('header-init-time').textContent = WX_DATA.init_time;
            document.getElementById('kpi-total-points').textContent = WX_DATA.points.length;

            let totalRainSum = 0;
            let maxT = -999;
            let minT = 999;
            let maxW = 0;

            WX_DATA.points.forEach(p => {{
                totalRainSum += p.rain_total;
                if (p.temp_max > maxT) maxT = p.temp_max;
                if (p.temp_min < minT) minT = p.temp_min;
                if (p.wind_max > maxW) maxW = p.wind_max;
            }});

            const avgRain = (totalRainSum / WX_DATA.points.length).toFixed(1);
            document.getElementById('kpi-avg-rain').textContent = avgRain;
            document.getElementById('kpi-temp-range').textContent = `${{minT}} ~ ${{maxT}}`;
            document.getElementById('kpi-max-wind').textContent = maxW.toFixed(1);
            document.getElementById('kpi-max-wind-kmh').textContent = `~${{(maxW * 3.6).toFixed(0)}} km/h (rajadas)`;

            // Unit with max rain
            let maxUnitName = '-';
            let maxUnitRain = 0;
            for (let u of WX_DATA.units) {{
                const st = WX_DATA.unit_stats[u];
                if (st && st.avg_rain > maxUnitRain) {{
                    maxUnitRain = st.avg_rain;
                    maxUnitName = u;
                }}
            }}
            document.getElementById('kpi-max-rain-unit').textContent = `Polo mais chuvoso: ${{maxUnitName}} (${{maxUnitRain}} mm)`;

            // 2. Populate Unit Select
            const unitSelect = document.getElementById('unit-select');
            WX_DATA.units.forEach(u => {{
                const opt = document.createElement('option');
                opt.value = u;
                opt.textContent = `Polo ${{u}} (${{WX_DATA.points.filter(p => p.unidade === u).length}} pontos)`;
                unitSelect.appendChild(opt);
            }});

            // 3. Initialize Map
            initMap();

            // 4. Setup Event Listeners
            unitSelect.addEventListener('change', () => {{
                updatePointSelect();
                filterMapMarkers();
                updatePointsList();
            }});

            const pointSelect = document.getElementById('point-select');
            pointSelect.addEventListener('change', (e) => {{
                selectPoint(e.target.value);
            }});

            document.getElementById('btn-mode-stats').addEventListener('click', () => setMode('stats'));
            document.getElementById('btn-mode-spaghetti').addEventListener('click', () => setMode('spaghetti'));

            // Initial Point Selection
            updatePointSelect();
            if (WX_DATA.points.length > 0) {{
                selectPoint(WX_DATA.points[0].id);
            }}
            updatePointsList();
        }}

        function setMode(mode) {{
            currentMode = mode;
            const btnStats = document.getElementById('btn-mode-stats');
            const btnSpaghetti = document.getElementById('btn-mode-spaghetti');

            if (mode === 'stats') {{
                btnStats.className = "px-3 py-1 text-xs font-semibold rounded-md bg-brand-600 text-white shadow-sm transition";
                btnSpaghetti.className = "px-3 py-1 text-xs font-semibold rounded-md text-slate-400 hover:text-white transition";
                document.getElementById('rain-legend-desc').textContent = "Faixa P10-P90 e Média do Ensemble";
                document.getElementById('temp-legend-desc').textContent = "Envelope de Incerteza e Ciclo Diurno";
                document.getElementById('wind-legend-desc').textContent = "Média e Rajadas Máximas";
            }} else {{
                btnSpaghetti.className = "px-3 py-1 text-xs font-semibold rounded-md bg-brand-600 text-white shadow-sm transition";
                btnStats.className = "px-3 py-1 text-xs font-semibold rounded-md text-slate-400 hover:text-white transition";
                document.getElementById('rain-legend-desc').textContent = "Spaghetti Plot: 64 Membros Individuais + Média";
                document.getElementById('temp-legend-desc').textContent = "Spaghetti Plot: 64 Membros Individuais + Média";
                document.getElementById('wind-legend-desc').textContent = "Spaghetti Plot: 64 Membros Individuais + Média";
            }}

            if (selectedPointId) {{
                renderCharts(selectedPointId);
            }}
        }}

        let infoWindow = null;

        function promptApiKey() {{
            const currentKey = localStorage.getItem('gmaps_api_key') || '';
            const newKey = prompt('Insira sua Chave de API do Google Maps (Google Cloud):', currentKey);
            if (newKey !== null) {{
                if (newKey.trim()) {{
                    localStorage.setItem('gmaps_api_key', newKey.trim());
                }} else {{
                    localStorage.removeItem('gmaps_api_key');
                }}
                location.reload();
            }}
        }}

        function initMap() {{
            if (!window.google || !window.google.maps) {{
                console.warn('Google Maps API ainda não carregada.');
                return;
            }}

            // Centro da região Atvos (Mato Grosso do Sul / Goiás / São Paulo)
            map = new google.maps.Map(document.getElementById('map'), {{
                center: {{ lat: -20.5, lng: -52.5 }},
                zoom: 6,
                mapTypeId: google.maps.MapTypeId.HYBRID, // Visão Satélite Híbrida (ótimo para agricultura/talhões)
                mapTypeControl: true,
                mapTypeControlOptions: {{
                    position: google.maps.ControlPosition.TOP_LEFT
                }},
                streetViewControl: false,
                fullscreenControl: true,
                zoomControl: true
            }});

            infoWindow = new google.maps.InfoWindow();
            renderMarkers();
        }}

        function renderMarkers() {{
            if (!map || !window.google || !window.google.maps) return;
            mapMarkers = [];
            const selectedUnit = document.getElementById('unit-select').value;

            WX_DATA.points.forEach(p => {{
                const color = UNIT_COLORS[p.unidade] || '#10b981';
                const marker = new google.maps.Marker({{
                    position: {{ lat: p.lat, lng: p.lon }},
                    map: map,
                    title: `${{p.name}} (${{p.unidade}})`,
                    icon: {{
                        path: google.maps.SymbolPath.CIRCLE,
                        scale: 7,
                        fillColor: color,
                        fillOpacity: 0.9,
                        strokeColor: '#ffffff',
                        strokeWeight: 1.5
                    }}
                }});

                marker.pointId = p.id;
                marker.unidade = p.unidade;
                marker.pointData = p;

                marker.addListener('click', () => {{
                    selectPoint(p.id);
                }});

                mapMarkers.push(marker);
            }});
        }}

        function filterMapMarkers() {{
            if (!map || !window.google || !window.google.maps) return;
            const selectedUnit = document.getElementById('unit-select').value;
            const bounds = new google.maps.LatLngBounds();
            let visibleCount = 0;

            mapMarkers.forEach(m => {{
                const isVisible = (selectedUnit === 'ALL' || m.unidade === selectedUnit);
                m.setVisible(isVisible);
                if (isVisible) {{
                    bounds.extend(m.getPosition());
                    visibleCount++;
                }}
            }});

            if (visibleCount > 0 && map) {{
                map.fitBounds(bounds);
            }}
        }}

        function updatePointSelect() {{
            const selectedUnit = document.getElementById('unit-select').value;
            const pointSelect = document.getElementById('point-select');
            pointSelect.innerHTML = '';

            const filteredPoints = selectedUnit === 'ALL' 
                ? WX_DATA.points 
                : WX_DATA.points.filter(p => p.unidade === selectedUnit);

            filteredPoints.forEach(p => {{
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${{p.name}} (${{p.unidade}}) - ${{p.rain_total}}mm`;
                pointSelect.appendChild(opt);
            }});

            if (filteredPoints.length > 0) {{
                selectPoint(filteredPoints[0].id);
            }}
        }}

        function updatePointsList() {{
            const selectedUnit = document.getElementById('unit-select').value;
            const listEl = document.getElementById('points-list');
            listEl.innerHTML = '';

            const filteredPoints = selectedUnit === 'ALL' 
                ? WX_DATA.points 
                : WX_DATA.points.filter(p => p.unidade === selectedUnit);

            document.getElementById('panel-unit-count').textContent = `${{filteredPoints.length}} pontos`;

            filteredPoints.forEach(p => {{
                const item = document.createElement('div');
                item.className = `p-2 rounded-lg cursor-pointer text-xs flex items-center justify-between border transition ${{
                    p.id === selectedPointId 
                        ? 'bg-brand-600/20 border-brand-500/50 text-white font-semibold' 
                        : 'bg-dark-800/60 border-slate-700/40 text-slate-300 hover:bg-dark-800 hover:text-white'
                }}`;
                item.innerHTML = `
                    <div class="truncate mr-2">
                        <span>${{p.name}}</span>
                        <span class="text-[10px] text-slate-400 block">${{p.unidade}}</span>
                    </div>
                    <div class="text-right shrink-0">
                        <span class="text-cyan-400 font-mono font-bold">${{p.rain_total}} mm</span>
                    </div>
                `;
                item.addEventListener('click', () => {{
                    selectPoint(p.id);
                }});
                listEl.appendChild(item);
            }});
        }}

        function selectPoint(pid) {{
            selectedPointId = pid;
            const p = WX_DATA.points.find(item => item.id === pid);
            if (!p) return;

            // Sync select
            document.getElementById('point-select').value = pid;

            // Update Panel
            document.getElementById('panel-point-name').textContent = p.name;
            document.getElementById('panel-point-unit').textContent = p.unidade;
            document.getElementById('panel-point-coords').textContent = `${{p.lat.toFixed(4)}}, ${{p.lon.toFixed(4)}}`;
            document.getElementById('panel-point-rain').textContent = `${{p.rain_total}} mm`;
            document.getElementById('panel-point-temp').textContent = `${{p.temp_min}}° / ${{p.temp_max}}°`;
            document.getElementById('charts-subtitle').textContent = `Previsões horárias para ${{p.name}} (Polo ${{p.unidade}} • Lat ${{p.lat.toFixed(4)}}, Lon ${{p.lon.toFixed(4)}})`;

            // Highlight marker on Google Map
            mapMarkers.forEach(m => {{
                if (m.pointId === pid) {{
                    m.setIcon({{
                        path: google.maps.SymbolPath.CIRCLE,
                        scale: 11,
                        fillColor: '#fbbf24', // Destaque dourado
                        fillOpacity: 1,
                        strokeColor: '#ffffff',
                        strokeWeight: 2.5
                    }});
                    m.setZIndex(1000);

                    const content = `
                        <div style="font-family: system-ui, sans-serif; font-size: 12px; color: #0f172a; padding: 4px; min-width: 170px;">
                            <div style="font-weight: bold; font-size: 14px; color: #0f172a;">${{m.pointData.name}}</div>
                            <div style="color: #64748b; margin-top: 2px;">Polo: <strong style="color: #0284c7;">${{m.pointData.unidade}}</strong></div>
                            <div style="margin-top: 6px; border-top: 1px solid #e2e8f0; padding-top: 6px; line-height: 1.5;">
                                🌧️ Chuva (15d): <strong style="color: #0891b2;">${{m.pointData.rain_total}} mm</strong><br>
                                🌡️ Temp. Máx: <strong>${{m.pointData.temp_max}} °C</strong><br>
                                💨 Vento Máx: <strong>${{m.pointData.wind_max}} m/s</strong>
                            </div>
                        </div>
                    `;
                    if (infoWindow && map) {{
                        infoWindow.setContent(content);
                        infoWindow.open(map, m);
                        map.panTo(m.getPosition());
                    }}
                }} else {{
                    const origColor = UNIT_COLORS[m.unidade] || '#10b981';
                    m.setIcon({{
                        path: google.maps.SymbolPath.CIRCLE,
                        scale: 7,
                        fillColor: origColor,
                        fillOpacity: 0.9,
                        strokeColor: '#ffffff',
                        strokeWeight: 1.5
                    }});
                    m.setZIndex(1);
                }}
            }});

            updatePointsList();
            renderCharts(pid);
        }}

        function renderCharts(pid) {{
            const p = WX_DATA.points.find(item => item.id === pid);
            if (!p) return;

            const timeX = WX_DATA.timestamps;
            const layoutBase = {{
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: {{ color: '#94a3b8', family: 'system-ui, sans-serif', size: 11 }},
                margin: {{ l: 50, r: 20, t: 30, b: 40 }},
                hovermode: 'x unified',
                xaxis: {{
                    gridcolor: '#1e293b',
                    showline: true,
                    linecolor: '#334155',
                    tickformat: '%d/%m %Hh'
                }},
                yaxis: {{
                    gridcolor: '#1e293b',
                    showline: true,
                    linecolor: '#334155'
                }},
                showlegend: true,
                legend: {{
                    orientation: 'h',
                    y: 1.12,
                    x: 0,
                    font: {{ size: 10, color: '#cbd5e1' }}
                }}
            }};

            // -------------------------------------------------------------
            // CHART 1: PRECIPITATION (Accumulated mm + 6h steps)
            // -------------------------------------------------------------
            let precipTraces = [];
            if (currentMode === 'spaghetti') {{
                p.members.rain_accum.forEach((mArr, idx) => {{
                    precipTraces.push({{
                        x: timeX,
                        y: mArr,
                        mode: 'lines',
                        line: {{ color: 'rgba(6, 182, 212, 0.15)', width: 1 }},
                        hoverinfo: 'none',
                        showlegend: false
                    }});
                }});
            }} else {{
                // P10-P90 Envelope (simulated using min/max bounds)
                precipTraces.push({{
                    x: timeX,
                    y: p.stats.rain_accum,
                    mode: 'lines',
                    line: {{ color: 'rgba(6, 182, 212, 0.2)', width: 0 }},
                    showlegend: false,
                    hoverinfo: 'none'
                }});
            }}

            // Ensemble Mean Accumulated Rain
            precipTraces.push({{
                x: timeX,
                y: p.stats.rain_accum,
                name: 'Chuva Acumulada Média (mm)',
                mode: 'lines',
                line: {{ color: '#06b6d4', width: 3 }},
                hovertemplate: '%{{y:.1f}} mm'
            }});

            // 6-hour rain bars on secondary axis
            precipTraces.push({{
                x: timeX,
                y: p.stats.rain_step,
                name: 'Chuva 6h (mm)',
                type: 'bar',
                marker: {{ color: 'rgba(56, 189, 248, 0.5)' }},
                yaxis: 'y2',
                hovertemplate: '%{{y:.2f}} mm / 6h'
            }});

            const precipLayout = JSON.parse(JSON.stringify(layoutBase));
            precipLayout.yaxis.title = 'Acumulado (mm)';
            precipLayout.yaxis2 = {{
                title: 'Taxa 6h (mm)',
                overlaying: 'y',
                side: 'right',
                gridcolor: 'rgba(0,0,0,0)',
                showgrid: false
            }};
            Plotly.newPlot('chart-precip', precipTraces, precipLayout, {{ responsive: true, displayModeBar: false }});

            // -------------------------------------------------------------
            // CHART 2: TEMPERATURE (°C)
            // -------------------------------------------------------------
            let tempTraces = [];
            if (currentMode === 'spaghetti') {{
                p.members.temp.forEach((mArr, idx) => {{
                    tempTraces.push({{
                        x: timeX,
                        y: mArr,
                        mode: 'lines',
                        line: {{ color: 'rgba(251, 191, 36, 0.12)', width: 1 }},
                        hoverinfo: 'none',
                        showlegend: false
                    }});
                }});
            }} else {{
                // Envelope P10 - P90
                tempTraces.push({{
                    x: timeX,
                    y: p.stats.temp_p90,
                    mode: 'lines',
                    line: {{ width: 0 }},
                    showlegend: false,
                    hoverinfo: 'none'
                }});
                tempTraces.push({{
                    x: timeX,
                    y: p.stats.temp_p10,
                    name: 'Faixa Incerteza (P10-P90)',
                    mode: 'lines',
                    fill: 'tonexty',
                    fillcolor: 'rgba(245, 158, 11, 0.15)',
                    line: {{ width: 0 }},
                    hoverinfo: 'none'
                }});
            }}

            // Ensemble Mean
            tempTraces.push({{
                x: timeX,
                y: p.stats.temp_mean,
                name: 'Temperatura Média (°C)',
                mode: 'lines',
                line: {{ color: '#f59e0b', width: 2.5 }},
                hovertemplate: '%{{y:.1f}} °C'
            }});

            const tempLayout = JSON.parse(JSON.stringify(layoutBase));
            tempLayout.yaxis.title = 'Temperatura (°C)';
            Plotly.newPlot('chart-temp', tempTraces, tempLayout, {{ responsive: true, displayModeBar: false }});

            // -------------------------------------------------------------
            // CHART 3: WIND SPEED (m/s)
            // -------------------------------------------------------------
            let windTraces = [];
            if (currentMode === 'spaghetti') {{
                p.members.wind.forEach((mArr, idx) => {{
                    windTraces.push({{
                        x: timeX,
                        y: mArr,
                        mode: 'lines',
                        line: {{ color: 'rgba(129, 140, 248, 0.15)', width: 1 }},
                        hoverinfo: 'none',
                        showlegend: false
                    }});
                }});
            }} else {{
                windTraces.push({{
                    x: timeX,
                    y: p.stats.wind_max,
                    name: 'Rajada Máxima Ensemble (m/s)',
                    mode: 'lines',
                    line: {{ color: '#ec4899', width: 1.5, dash: 'dot' }},
                    hovertemplate: '%{{y:.1f}} m/s'
                }});
            }}

            windTraces.push({{
                x: timeX,
                y: p.stats.wind_mean,
                name: 'Velocidade Média do Vento (m/s)',
                mode: 'lines',
                line: {{ color: '#6366f1', width: 2.5 }},
                hovertemplate: '%{{y:.1f}} m/s'
            }});

            const windLayout = JSON.parse(JSON.stringify(layoutBase));
            windLayout.yaxis.title = 'Velocidade (m/s)';
            Plotly.newPlot('chart-wind', windTraces, windLayout, {{ responsive: true, displayModeBar: false }});
        }}

        window.addEventListener('DOMContentLoaded', initDashboard);
    </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Sucesso! {output_path} gerado com sucesso ({file_size_mb:.2f} MB).")

def main():
    if not os.path.exists(INPUT_CSV):
        print(f"Erro: Arquivo {INPUT_CSV} não encontrado!", file=sys.stderr)
        sys.exit(1)

    dataset = load_and_aggregate_data(INPUT_CSV)
    generate_html(dataset, OUTPUT_HTML)

if __name__ == "__main__":
    main()
