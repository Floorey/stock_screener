import pandas as pd
import os

def clean_and_profile_csv(file_path):
    print("=" * 60)
    print(f"PROFILING & CLEANING FILE: {os.path.basename(file_path)}")
    print("=" * 60)
    
    if not os.path.exists(file_path):
        print(f"Fehler: Datei {file_path} existiert nicht.")
        return
        
    # Step 1: Ingestion & Inital Profile
    df = pd.read_csv(file_path)
    print(f"Ursprüngliche Zeilenanzahl: {len(df)}")
    print(f"Spalten und Datentypen:\n{df.dtypes}\n")
    
    # Check for missing values
    null_counts = df.isnull().sum()
    print("Fehlende Werte pro Spalte:")
    for col, count in null_counts.items():
        if count > 0:
            print(f"  - {col}: {count} ({count/len(df)*100:.1f}%)")
        else:
            print(f"  - {col}: 0")
            
    # Check for duplicates
    dup_count = df.duplicated().sum()
    print(f"\nDuplikate gefunden: {dup_count}")
    
    # Step 2: Transformations / Data Cleaning
    print("\nWende Bereinigungen an...")
    
    # 1. Deduplication
    if dup_count > 0:
        df = df.drop_duplicates()
        print(f"  - Duplikate entfernt. Neue Zeilenanzahl: {len(df)}")
        
    # 2. Text Normalization: trim whitespace and preserve case
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].astype(str).str.strip()
        
    # 3. Handle specific dataset columns
    filename = os.path.basename(file_path)
    
    if filename == "cashflow_ledger.csv":
        # Ensure Date column is parsed as datetime and formatted consistently
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
            # Fill missing dates with current date
            df["Date"] = df["Date"].fillna(pd.Timestamp.now().normalize())
            df["Date"] = df["Date"].dt.strftime('%Y-%m-%d')
            
        # Amount formatting
        if "Amount" in df.columns:
            df["Amount"] = pd.to_numeric(df["Amount"], errors='coerce').fillna(0.0)
            
    elif filename == "screener_test_results.csv":
        # Numeric columns conversion and default imputation
        numeric_cols = [
            "Price", "LongScore", "ShortScore", "PE", "ForwardPE", "PB", 
            "DebtToEquity", "CurrentRatio", "QuickRatio", "FCF", 
            "OperatingCashflow", "NetMargin", "OperatingMargin", "ROE", "ROA", 
            "RevenueGrowth", "EPSGrowth", "ShortInterestPercent", "Beta", 
            "EV", "EVToRevenue", "EVToEbitda"
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        # Fill missing values for scores and critical metrics with standard defaults
        if "LongScore" in df.columns:
            df["LongScore"] = df["LongScore"].fillna(0).astype(int)
        if "ShortScore" in df.columns:
            df["ShortScore"] = df["ShortScore"].fillna(0).astype(int)
            
        # Standardize Booleans
        bool_cols = ["Tradable", "Shortable", "EasyToBorrow"]
        for col in bool_cols:
            if col in df.columns:
                df[col] = df[col].map({'True': True, 'False': False, True: True, False: False}).fillna(False)

    # Save cleaned file
    cleaned_path = file_path.replace(".csv", "_cleaned.csv")
    df.to_csv(cleaned_path, index=False)
    print(f"\nBereinigte Datei gespeichert unter: {os.path.basename(cleaned_path)}")
    
    # Step 3: Post-transformation verification profile
    print("\n" + "-"*40)
    print("Post-Transformation Profil:")
    print(f"Finale Zeilenanzahl: {len(df)}")
    new_null_counts = df.isnull().sum()
    print("Verbleibende fehlende Werte:")
    for col, count in new_null_counts.items():
        if count > 0:
            print(f"  - {col}: {count}")
    print("-"*40 + "\n")

if __name__ == "__main__":
    workspace_dir = r"C:\Users\lukas\stock_screener"
    files = ["cashflow_ledger.csv", "screener_test_results.csv"]
    for f in files:
        clean_and_profile_csv(os.path.join(workspace_dir, f))
