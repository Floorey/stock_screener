import os
import pandas as pd
import numpy as np

def kmeans_clustering(X_scaled, k_values=[2, 3, 4, 5], max_iter=100, random_state=42):
    np.random.seed(random_state)
    n_samples, n_features = X_scaled.shape
    best_results = {}
    
    for k in k_values:
        if k >= n_samples:
            continue
        # Initialize centroids randomly from sample points
        init_indices = np.random.choice(n_samples, k, replace=False)
        centroids = X_scaled[init_indices]
        
        for iteration in range(max_iter):
            # Compute distances to centroids
            distances = np.linalg.norm(X_scaled[:, np.newaxis] - centroids, axis=2)
            labels = np.argmin(distances, axis=1)
            
            # Compute new centroids
            new_centroids = np.array([X_scaled[labels == i].mean(axis=0) if np.sum(labels == i) > 0 else centroids[i] for i in range(k)])
            
            if np.allclose(centroids, new_centroids):
                break
            centroids = new_centroids
            
        # Compute Silhouette score manually
        # a(i): average distance to points in same cluster
        # b(i): minimum average distance to points in other clusters
        silhouette_vals = []
        for i in range(n_samples):
            same_cluster_indices = np.where(labels == labels[i])[0]
            if len(same_cluster_indices) > 1:
                a_i = np.mean(np.linalg.norm(X_scaled[i] - X_scaled[same_cluster_indices], axis=1))
            else:
                a_i = 0
                
            other_clusters = [c for c in range(k) if c != labels[i]]
            b_i_list = []
            for c in other_clusters:
                c_indices = np.where(labels == c)[0]
                if len(c_indices) > 0:
                    b_i_list.append(np.mean(np.linalg.norm(X_scaled[i] - X_scaled[c_indices], axis=1)))
            b_i = min(b_i_list) if len(b_i_list) > 0 else 0
            
            sil_i = (b_i - a_i) / max(a_i, b_i) if max(a_i, b_i) > 0 else 0
            silhouette_vals.append(sil_i)
            
        avg_sil = np.mean(silhouette_vals)
        best_results[k] = {'labels': labels, 'centroids': centroids, 'silhouette': avg_sil}
        
    return best_results

def pca_2d(X_scaled):
    # Mean centered
    X_centered = X_scaled - np.mean(X_scaled, axis=0)
    # SVD
    U, S, Vt = np.linalg.svd(X_centered, full_matrices=False)
    explained_variance_ratio = (S ** 2) / np.sum(S ** 2)
    projection = np.dot(X_centered, Vt.T[:, :2])
    return projection, explained_variance_ratio[:2]

def analyze_screener_data(filepath):
    print("=" * 80)
    print(f"ML EVALUATION & EDA: {os.path.basename(filepath)}")
    print("=" * 80)
    
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        return
        
    df = pd.read_csv(filepath)
    print(f"Dataset Shape: {df.shape[0]} rows, {df.shape[1]} columns")
    print(f"Columns: {list(df.columns)}\n")
    
    # 1. Missing Values & Data Hygiene
    print("-" * 50)
    print("1. DATA HYGIENE & MISSING VALUE ANALYSIS")
    print("-" * 50)
    null_summary = df.isnull().sum()
    null_perc = (null_summary / len(df)) * 100
    missing_df = pd.DataFrame({'Missing_Count': null_summary, 'Missing_Percent': null_perc})
    missing_df = missing_df[missing_df['Missing_Count'] > 0]
    if len(missing_df) > 0:
        print(missing_df.to_string())
    else:
        print("No missing values found in columns.")
        
    print(f"\nDuplicate Rows Count: {df.duplicated().sum()}")
    
    # 2. Descriptive Statistics & Outlier Detection
    print("\n" + "-" * 50)
    print("2. DESCRIPTIVE STATISTICS & OUTLIER DETECTION")
    print("-" * 50)
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    
    key_features = ['Price', 'PE', 'ForwardPE', 'PB', 'DebtToEquity', 'CurrentRatio', 
                    'QuickRatio', 'FCF', 'OperatingCashflow', 'NetMargin', 'OperatingMargin', 
                    'ROE', 'ROA', 'RevenueGrowth', 'EPSGrowth', 'Beta', 'EVToRevenue', 'EVToEbitda', 'LongScore', 'ShortScore']
    available_key_features = [f for f in key_features if f in numeric_cols]
    
    stats_df = df[available_key_features].describe().T[['mean', 'std', 'min', '50%', 'max']]
    stats_df.rename(columns={'50%': 'median'}, inplace=True)
    
    outlier_counts = {}
    skewness = {}
    for col in available_key_features:
        series = df[col].dropna()
        skewness[col] = series.skew()
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outliers = series[(series < lower) | (series > upper)]
        outlier_counts[col] = len(outliers)
        
    stats_df['skewness'] = pd.Series(skewness)
    stats_df['iqr_outliers'] = pd.Series(outlier_counts)
    print(stats_df.round(3).to_string())
    
    # 3. Unsupervised ML: Feature Scaling, K-Means & PCA
    print("\n" + "-" * 50)
    print("3. UNSUPERVISED ML: STOCK CLUSTERING & PCA SEGMENTATION")
    print("-" * 50)
    
    cluster_features = ['PE', 'ForwardPE', 'PB', 'DebtToEquity', 'CurrentRatio', 
                        'NetMargin', 'OperatingMargin', 'ROE', 'ROA', 'RevenueGrowth', 'Beta', 'EVToRevenue']
    cluster_features = [f for f in cluster_features if f in df.columns]
    
    X = df[cluster_features].copy()
    # Impute numeric missing values with median for ML safety (Strict Featurization Practice)
    for col in X.columns:
        X[col] = X[col].fillna(X[col].median())
        
    # Standardize Features (Z-Score Scaling)
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0).replace(0, 1.0)
    X_scaled = ((X - X_mean) / X_std).values
    
    clustering_results = kmeans_clustering(X_scaled, k_values=[2, 3, 4, 5])
    for k, res in clustering_results.items():
        print(f"K = {k}: Silhouette Score = {res['silhouette']:.4f}")
        
    optimal_k = max(clustering_results, key=lambda k: clustering_results[k]['silhouette'])
    print(f"\nOptimal Cluster Count (max silhouette score): K = {optimal_k}")
    
    df['Cluster'] = clustering_results[optimal_k]['labels']
    
    print("\nCluster Distribution:")
    print(df['Cluster'].value_counts().to_string())
    
    print("\nCluster Profiles (Mean values per Cluster):")
    profile_cols = [f for f in available_key_features if f in df.columns]
    cluster_profile = df.groupby('Cluster')[profile_cols].mean().round(2)
    print(cluster_profile.to_string())
    
    # PCA Projection
    pca_coords, exp_var = pca_2d(X_scaled)
    df['PCA1'] = pca_coords[:, 0]
    df['PCA2'] = pca_coords[:, 1]
    print(f"\nPCA Explained Variance Ratio: PC1={exp_var[0]:.2%}, PC2={exp_var[1]:.2%} (Cumulative={sum(exp_var):.2%})")
    
    # 4. Feature Correlations & Target Analysis for LongScore
    print("\n" + "-" * 50)
    print("4. TARGET ANALYSIS: CORRELATIONS WITH LONGSCORE & SHORTSCORE")
    print("-" * 50)
    if 'LongScore' in df.columns:
        corrs_long = df[numeric_cols].corr()['LongScore'].drop(['LongScore', 'ShortScore'], errors='ignore').sort_values(ascending=False)
        print("Feature Correlations with LongScore:")
        print(corrs_long.round(4).to_string())
        
    if 'ShortScore' in df.columns:
        corrs_short = df[numeric_cols].corr()['ShortScore'].drop(['LongScore', 'ShortScore'], errors='ignore').sort_values(ascending=False)
        print("\nFeature Correlations with ShortScore:")
        print(corrs_short.round(4).to_string())

def analyze_cashflow_data(filepath):
    print("\n" + "=" * 80)
    print(f"ML EVALUATION & EDA: {os.path.basename(filepath)}")
    print("=" * 80)
    
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        return
        
    df = pd.read_csv(filepath)
    print(f"Dataset Shape: {df.shape[0]} rows, {df.shape[1]} columns")
    print(f"Columns: {list(df.columns)}\n")
    
    print("-" * 50)
    print("CASHFLOW LEDGER BREAKDOWN")
    print("-" * 50)
    
    if 'Amount' in df.columns:
        print(f"Total Cashflow Amount: ${df['Amount'].sum():,.2f}")
        print(f"Average Entry Amount: ${df['Amount'].mean():,.2f}")
        print(f"Min / Max Amount: ${df['Amount'].min():,.2f} / ${df['Amount'].max():,.2f}")
        
    if 'Type' in df.columns and 'Amount' in df.columns:
        print("\nBreakdown by Transaction Type:")
        type_summary = df.groupby('Type')['Amount'].agg(['count', 'sum', 'mean']).round(2)
        print(type_summary.to_string())
        
    if 'Ticker' in df.columns and 'Amount' in df.columns:
        print("\nBreakdown by Ticker:")
        ticker_summary = df.groupby('Ticker')['Amount'].agg(['count', 'sum', 'mean']).round(2)
        print(ticker_summary.to_string())

if __name__ == "__main__":
    screener_path = r"c:\Users\lukas\stock_screener\screener_test_results_cleaned.csv"
    cashflow_path = r"c:\Users\lukas\stock_screener\cashflow_ledger_cleaned.csv"
    
    analyze_screener_data(screener_path)
    analyze_cashflow_data(cashflow_path)
