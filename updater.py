import pandas as pd
import json
import datetime
import requests
import io
import zipfile
import re

def fetch_and_process_cot():
    current_year = datetime.datetime.now().year

    url_zip = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{current_year}.zip"
    url_weekly = "https://www.cftc.gov/dea/new_fit/fin_com_txt.txt"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    df = None
    print(f"Buscando dados oficiais da CFTC ({current_year})...")

    try:
        res = requests.get(url_zip, headers=headers, timeout=30)
        if res.status_code == 200:
            z = zipfile.ZipFile(io.BytesIO(res.content))
            filename = z.namelist()[0]
            df = pd.read_csv(z.open(filename), low_memory=False)
            print("Dados anuais (ZIP) baixados com sucesso!")
    except Exception as e:
        print(f"Aviso no arquivo ZIP: {e}")

    if df is None:
        try:
            res = requests.get(url_weekly, headers=headers, timeout=30)
            if res.status_code == 200:
                df = pd.read_csv(io.StringIO(res.text), low_memory=False)
                print("Relatório semanal baixado com sucesso!")
        except Exception as e:
            print(f"Erro no download semanal: {e}")

    if df is None:
        raise Exception("Não foi possível obter dados da CFTC.")

    # Mapeamento das moedas para o(s) nome(s) do CONTRATO PRINCIPAL na CFTC.
    # Cada entrada é testada como prefixo exato "NOME - BOLSA...", nunca como
    # substring solta — isso evita casar contratos de câmbio cruzado
    # (ex.: "EURO FX/BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE"),
    # que antes eram somados junto com o contrato principal e geravam
    # múltiplos valores duplicados/conflitantes na mesma data.
    currency_map = {
        'AUD': ['AUSTRALIAN DOLLAR'],
        'CAD': ['CANADIAN DOLLAR'],
        'CHF': ['SWISS FRANC'],
        'EUR': ['EURO FX'],
        'GBP': ['BRITISH POUND STERLING', 'BRITISH POUND'],
        'JPY': ['JAPANESE YEN'],
        'NZD': ['NEW ZEALAND DOLLAR'],
        'USD': ['USD INDEX', 'U.S. DOLLAR INDEX', 'DOLLAR INDEX']
    }

    df.columns = df.columns.str.strip()
    df['Market_Name'] = df['Market_and_Exchange_Names'].astype(str).str.upper().str.strip()

    def find_primary_contract(source_df, prefixes):
        """Retorna apenas as linhas do CONTRATO PRINCIPAL de uma moeda.

        Exige que o nome comece exatamente por "<prefixo> -" e descarta
        qualquer nome que contenha "/", que é como a CFTC identifica pares
        de câmbio cruzado (ex.: NZD/CAD, EUR/GBP) — esses pares nunca devem
        entrar no cálculo da posição líquida da moeda principal.
        """
        for prefix in prefixes:
            pattern = r'^' + re.escape(prefix) + r'\s*-'
            mask = source_df['Market_Name'].str.match(pattern, na=False) & \
                   ~source_df['Market_Name'].str.contains('/', na=False)
            matched = source_df[mask]
            if not matched.empty:
                return matched
        return pd.DataFrame()

    parsed_data = {}

    for code, prefixes in currency_map.items():
        sub_df = find_primary_contract(df, prefixes)

        if not sub_df.empty:
            sub_df = sub_df.copy()
            date_col = 'Report_Date_as_MM_DD_YYYY' if 'Report_Date_as_MM_DD_YYYY' in sub_df.columns else sub_df.columns[2]
            sub_df[date_col] = pd.to_datetime(sub_df[date_col])
            sub_df = sub_df.sort_values(by=date_col, ascending=True)

            # Se ainda assim sobrar mais de uma linha por data (não deveria
            # acontecer com o contrato principal, mas por segurança),
            # mantém apenas a última ocorrência de cada data.
            sub_df = sub_df.drop_duplicates(subset=date_col, keep='last')

            # Posições Líquidas em milhares (Long - Short) / 1000
            if 'Lev_Money_Positions_Long_All' in sub_df.columns:
                sub_df['Net_Pos'] = (pd.to_numeric(sub_df['Lev_Money_Positions_Long_All'], errors='coerce') -
                                     pd.to_numeric(sub_df['Lev_Money_Positions_Short_All'], errors='coerce')) / 1000.0
            elif 'NonComm_Positions_Long_All' in sub_df.columns:
                sub_df['Net_Pos'] = (pd.to_numeric(sub_df['NonComm_Positions_Long_All'], errors='coerce') -
                                     pd.to_numeric(sub_df['NonComm_Positions_Short_All'], errors='coerce')) / 1000.0
            else:
                sub_df['Net_Pos'] = 0.0

            history = []
            for _, row in sub_df.iterrows():
                if pd.notnull(row['Net_Pos']):
                    date_str = row[date_col].strftime('%d/%m/%Y')
                    val = round(float(row['Net_Pos']), 1)
                    history.append({'date': date_str, 'val': val})

            parsed_data[code] = history
        else:
            print(f"Aviso: nenhum contrato principal encontrado para {code}.")

    latest_date = datetime.date.today().strftime('%d/%m/%Y')
    if parsed_data and len(list(parsed_data.values())[0]) > 0:
        latest_date = list(parsed_data.values())[0][-1]['date']

    current_summary = {}
    previous_summary = {}
    diff_summary = {}

    for code, history in parsed_data.items():
        if len(history) >= 2:
            curr = history[-1]['val']
            prev = history[-2]['val']
            diff = round(curr - prev, 1)
        elif len(history) == 1:
            curr = history[-1]['val']
            prev = 0.0
            diff = curr
        else:
            curr, prev, diff = 0.0, 0.0, 0.0

        current_summary[code] = curr
        previous_summary[code] = prev
        diff_summary[code] = diff

    json_output = {
        "period": f"Posições atualizadas até {latest_date}",
        "current": current_summary,
        "previous": previous_summary,
        "diff": diff_summary,
        "history": parsed_data
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)

    print(f"data.json atualizado com sucesso! Moedas encontradas: {', '.join(parsed_data.keys())}")

if __name__ == "__main__":
    fetch_and_process_cot()
