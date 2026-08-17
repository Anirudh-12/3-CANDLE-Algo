import os
import requests
import zipfile
import csv
from datetime import datetime
from collections import defaultdict
from typing import Iterable, List, Dict
import pandas as pd
# Constants
ZIP_URL = "https://api.shoonya.com/NFO_symbols.txt.zip"
ZIP_URL_SENSEX = "https://api.shoonya.com/BFO_symbols.txt.zip"
ZIP_FILE = "symbols.zip"
TXT_FILE = "symbols.txt"
DOWNLOAD_DATE_FILE = "last_download_date.txt"
FILTERED_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}

# Function to download and merge ZIP files
def download_and_merge_files():
    responses = [requests.get(ZIP_URL), requests.get(ZIP_URL_SENSEX)]
    txt_data = []

    for response in responses:
        zip_path = ZIP_FILE
        with open(zip_path, 'wb') as f:
            f.write(response.content)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                with zip_ref.open(file) as f:
                    lines = f.read().decode().splitlines()
                    for line in lines:
                        parts = line.split(',')
                        if parts[3] == "BSXOPT":
                            parts[3] = "SENSEX"
                            line = ",".join(parts)
                        txt_data.append(line)

    # Write merged and filtered data
    header = txt_data[0]
    rows = [line for line in txt_data[1:] if line.split(",")[3] in FILTERED_SYMBOLS]
    with open(TXT_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header.split(","))
        for row in rows:
            writer.writerow(row.split(","))

# Function to check if the file was downloaded today
def is_download_required():
    if not os.path.exists(DOWNLOAD_DATE_FILE):
        return True
    if not os.path.exists(TXT_FILE):
        return True
    with open(DOWNLOAD_DATE_FILE, 'r') as f:
        last_download_date = f.read().strip()
    return last_download_date != str(datetime.now().date())

# Function to update the last download date
def update_download_date():
    with open(DOWNLOAD_DATE_FILE, 'w') as f:
        f.write(str(datetime.now().date()))

# Main logic
if is_download_required():
    download_and_merge_files()
    update_download_date()
else:
    pass
    
# Instrument Helper Class
class InstrumentHelper:
    def __init__(self, filepath=TXT_FILE):
        self.filepath = filepath
        self.instruments = self._load_instruments()
        self.step_size = self.get_step_size("NIFTY")  # Default step size for NIFTY

    def _load_instruments(self) -> List[Dict[str, str]]:
        with open(self.filepath, newline='') as f:
            reader = csv.DictReader(f)
            return list(reader)

    

    def get_step_size(self, symbol: str) -> float:
        strike_prices = sorted(set(
            float(row['StrikePrice']) for row in self.instruments if row['Symbol'] == symbol
        ))
        diffs = [j - i for i, j in zip(strike_prices, strike_prices[1:]) if j - i > 0]
        
        return min(diffs) if diffs else 0.0

    def get_expirys_dict(self, symbols: Iterable[str]) -> Dict[str, List[str]]:
        expirys_dict = defaultdict(set)
        for row in self.instruments:
            symbol = row['Symbol']
            if symbol in symbols:
                expirys_dict[symbol].add(row['Expiry'])
        return {sym: sorted(exp_list, key=lambda d: datetime.strptime(d, "%d-%b-%Y")) for sym, exp_list in expirys_dict.items()}

    def ce_strike_to_token(self, symbol: str, expiry: str) -> Dict[float, str]:
        return {
            float(row['StrikePrice']): row['Token']
            for row in self.instruments
            if row['Symbol'] == symbol and row['Expiry'] == expiry and row['OptionType'] == 'CE'
        }

    def pe_strike_to_token(self, symbol: str, expiry: str) -> Dict[float, str]:
        return {
            float(row['StrikePrice']): row['Token']
            for row in self.instruments
            if row['Symbol'] == symbol and row['Expiry'] == expiry and row['OptionType'] == 'PE'
        }

    def ce_strike_to_symbol(self, symbol: str, expiry: str) -> Dict[float, str]:
        return {
            float(row['StrikePrice']): row['TradingSymbol']
            for row in self.instruments
            if row['Symbol'] == symbol and row['Expiry'] == expiry and row['OptionType'] == 'CE'
        }

    def pe_strike_to_symbol(self, symbol: str, expiry: str) -> Dict[float, str]:
        return {
            float(row['StrikePrice']): row['TradingSymbol']
            for row in self.instruments
            if row['Symbol'] == symbol and row['Expiry'] == expiry and row['OptionType'] == 'PE'
        }

    def get_option_strikes(self, symbol: str, expiry: str, atm_strike: int, count: int) -> List[Dict[str, str]]:
        lower = atm_strike - count * self.step_size
        upper = atm_strike + count * self.step_size
        return [
            row for row in self.instruments
            if row['Symbol'] == symbol and row['Expiry'] == expiry and
               lower <= float(row['StrikePrice']) <= upper
        ]

    def get_lot_size(self, symbol: str) -> int:
        for row in self.instruments:
            if row['Symbol'] == symbol:
                return int(row['LotSize'])
        raise ValueError(f"Lot size not found for symbol: {symbol}")
    def get_nifty_fut_token(self):
        df = pd.DataFrame(self.instruments)
        df_filtered = df[
            (df["Symbol"].str.upper() == "NIFTY") &
            (df["Instrument"].str.upper() == "FUTIDX")
        ]

        df_filtered = df_filtered.assign(
    Expiry_dt = pd.to_datetime(df_filtered["Expiry"], format="%d-%b-%Y")
)
        row_with_lowest_expiry = df_filtered.loc[df_filtered["Expiry_dt"].idxmin()]

        Token = row_with_lowest_expiry["Token"]
        return Token
    
    def get_token_symbol_dict(self,selected_expiry):
        if os.path.exists(TXT_FILE):
            df = pd.read_csv(TXT_FILE, delimiter=",")  # Assuming ',' is the delimiter
            #             df['StrikePrice'] = pd.to_numeric(df['StrikePrice'], errors='coerce').fillna(0).astype(int)
            # df["StrikePrice"] = df["StrikePrice"].astype(str)
            df['Token'] = df['Token'].astype(str)
            df["Expiry"] = df["Expiry"].astype(str)
            # Filtering for PE and CE conditions and creating dictionaries
           
            self.token_symbol_dict = df[
                (df['OptionType'].isin(['PE', 'CE'])) & (df['Symbol'] == 'NIFTY') & (df['Expiry'] == selected_expiry)
                ].set_index('Token')['TradingSymbol'].to_dict()
            return self.token_symbol_dict




if __name__ == "__main__":
    instrument_helper = InstrumentHelper(filepath=TXT_FILE)
    expirys_dict = instrument_helper.get_expirys_dict(("NIFTY",))
    nifty_expirys = expirys_dict["NIFTY"]
    strikes = instrument_helper.get_option_strikes("NIFTY", nifty_expirys[0], 19000, 100)
    
    step_size = instrument_helper.get_step_size("SENSEX")
    instrument_helper
   
   