import urllib.request
import zipfile
import io
import pandas as pd
import json
import datetime

def fetch_and_process_cot():
    # URL do relatório oficial da CFTC para dados financeiros (Traders in Financial Futures)
    url = "https://www.cftc.gov/files/dea/history/fut_fin_txt_2026.zip" # Atualizado dinamicamente
    
    print("Baixando dados oficiais da CFTC...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            zip_file = zipfile.ZipFile(io.BytesIO(response.read()))
            filename = zip_file.namelist()[0]
            df = pd.read_csv(zip_file.open(filename), low_memory=False)
    except Exception as e:
        print(f"Erro ao baixar dados do ano corrente, tentando relatório semanal padrão: {e}")
        url = "https://www.cftc.gov/dea/new_fit/fin_com_txt.txt"
        df = pd.read_csv(url, low_memory=False)

    # Mapeamento dos contratos para as moedas do Dashboard
    currency_map = {
        'CANADIAN DOLLAR': 'CAD',
        'SWISS FRANC': 'CHF',
        'BRITISH POUND STERLING': 'GBP',
        'JAPANESE YEN': 'JPY',
        'EURO FX': 'EUR',
        'AUSTRALIAN DOLLAR': 'AUD',
        'NEW ZEALAND DOLLAR': 'NZD',
        'U.S. DOLLAR INDEX': 'USD'
    }

    # Limpeza de colunas
    df.columns = df.columns.str.strip()
    
    # Filtrar apenas ativos de interesse
    df['Market_Name'] = df['Market_and_Exchange_Names'].str.upper()
    
    parsed_data = {}
    
    # Processar cada moeda
    for name_pattern, code in currency_map.items():
        sub_df = df[df['Market_Name'].str.contains(name_pattern, na=False)].copy()
        
        if not sub_df.empty:
            # Ordenar por data
            sub_df['Report_Date_as_MM_DD_YYYY'] = pd.to_datetime(sub_df['Report_Date_as_MM_DD_YYYY'])
            sub_df = sub_df.sort_values(by='Report_Date_as_MM_DD_YYYY', ascending=True)
            
            # Posições de Fundos Hedge (Leveraged Funds / Non-Commercial)
            # Calculando Posição Líquida (Comprados - Vendidos) em milhares/contratos
            if 'Lev_Money_Positions_Long_All' in sub_df.columns:
                sub_df['Net_Pos'] = (sub_df['Lev_Money_Positions_Long_All'] - sub_df['Lev_Money_Positions_Short_All']) / 1000.0
            else:
                # Fallback para relatórios Legacy
                sub_df['Net_Pos'] = (sub_df['NonComm_Positions_Long_All'] - sub_df['NonComm_Positions_Short_All']) / 1000.0
            
            history = []
            for _, row in sub_df.iterrows():
                date_str = row['Report_Date_as_MM_DD_YYYY'].strftime('%d/%m/%Y')
                val = round(float(row['Net_Pos']), 1)
                history.append({'date': date_str, 'val': val})
            
            parsed_data[code] = history

    # Gerar estrutura final do JSON
    latest_date = list(parsed_data.values())[0][-1]['date'] if parsed_data else datetime.date.today().strftime('%d/%m/%Y')
    
    # Calcular resumo atual e anterior
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

    # Salvar data.json
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
        
    print("data.json atualizado com sucesso!")

if __name__ == "__main__":
    fetch_and_process_cot()
