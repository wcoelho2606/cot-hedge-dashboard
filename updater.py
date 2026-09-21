import pandas as pd
import json
import datetime
import requests
import io
import zipfile

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

    # Mapeamento expandido para encontrar todas as 8 moedas no arquivo da CFTC
    currency_map = {
        'AUD': ['AUSTRALIAN DOLLAR', 'AUSTRALIAN'],
        'CAD': ['CANADIAN DOLLAR', 'CANADIAN'],
        'CHF': ['SWISS FRANC', 'SWISS'],
        'EUR': ['EURO FX', 'EURO'],
        'GBP': ['POUND STERLING', 'BRITISH POUND', 'POUND'],
        'JPY': ['JAPANESE YEN', 'YEN'],
        'NZD': ['NEW ZEALAND DOLLAR', 'NEW ZEALAND'],
        'USD': ['U.S. DOLLAR INDEX', 'USD INDEX', 'DOLLAR INDEX']
    }

    df.columns = df.columns.str.strip()
    df['Market_Name'] = df['Market_and_Exchange_Names'].astype(str).str.upper()
    
    parsed_data = {}

    for code, patterns in currency_map.items():
        sub_df = pd.DataFrame()
        for pattern in patterns:
            matched = df[df['Market_Name'].str.contains(pattern, na=False)].copy()
            if not matched.empty:
                sub_df = matched
                break
        
        if not sub_df.empty:
            date_col = 'Report_Date_as_MM_DD_YYYY' if 'Report_Date_as_MM_DD_YYYY' in sub_df.columns else sub_df.columns[2]
            sub_df[date_col] = pd.to_datetime(sub_df[date_col])
            sub_df = sub_df.sort_values(by=date_col, ascending=True)
            
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
        
    print("data.json atualizado com todas as 8 moedas!")

if __name__ == "__main__":
    fetch_and_process_cot()
