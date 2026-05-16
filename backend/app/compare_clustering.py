"""
compare_clustering.py
─────────────────────
KMeans vs DBSCAN performance comparison using the project's cleaning pipeline.

PREPROCESSING STRATEGY (fair comparison):
  - Steps 1-8 are shared: missing CID drop, monetary compute, log1p transform.
  - Step 9 splits by algorithm:
      KMeans → StandardScaler  (assumes spherical clusters, sensitive to scale)
      DBSCAN → RobustScaler    (uses median/IQR, robust to VIP outliers in RFM)

RUN:
    cd C:/Users/ACER/Desktop/clustering/backend
    python -m app.compare_clustering
"""

import datetime
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import polars as pl
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.cluster import KMeans, MiniBatchKMeans, DBSCAN
from sklearn.decomposition import PCA
from sklearn.metrics import (
    silhouette_score,
    calinski_harabasz_score,
    davies_bouldin_score,
)
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler, RobustScaler

from app.utils import read_file_fast, resolve_columns, to_float, parse_dates

DATASET_PATH = r"C:\Users\ACER\Desktop\dataset\Online Retail.xlsx"
OUTPUT_DIR   = r"C:\Users\ACER\Desktop\clustering\backend"
RANDOM_STATE = 42
np.random.seed(RANDOM_STATE)

sns.set_theme(style="whitegrid", palette="muted", font_scale=1.1)
PAL = sns.color_palette("tab10")


# ══════════════════════════════════════════════════════════════════════════════
#  STEPS 1-8  —  shared pipeline (no scaler yet)
# ══════════════════════════════════════════════════════════════════════════════

def build_rfm_log() -> tuple[pl.DataFrame, np.ndarray]:
    """
    Runs Steps 1-8 of the cleaning pipeline and returns:
        rfm     — Polars DataFrame (CustomerID, Recency, Frequency, Monetary)
        rfm_log — numpy array after log1p, NOT yet scaled
    Step 9 (scaling) is applied separately per algorithm below.
    """
    print("=" * 60)
    print("  LOADING DATASET")
    print("=" * 60)
    with open(DATASET_PATH, "rb") as f:
        raw_bytes = f.read()
    df      = read_file_fast(raw_bytes, "Online Retail.xlsx")
    col_map = resolve_columns(df)
    print(f"  Rows loaded : {len(df):,}")
    print(f"  Col map     : {col_map}\n")

    cid_col = col_map["customer_id"]

    print("=" * 60)
    print("  SHARED CLEANING PIPELINE  (Steps 1-8)")
    print("=" * 60)

    # Step 1 – remove missing Customer IDs
    df = df.with_columns(
        pl.col(cid_col).cast(pl.Utf8).str.strip_chars().alias(cid_col)
    )
    before = len(df)
    df = df.filter(
        pl.col(cid_col).is_not_null() &
        (pl.col(cid_col) != "") &
        (pl.col(cid_col).str.to_lowercase() != "nan")
    )
    print(f"  Step 1 – Remove missing CustomerID : -{before - len(df):,} rows → {len(df):,} remain")

    # Step 2 – compute monetary amount per row
    if "total_amount" in col_map:
        df = to_float(df, col_map["total_amount"])
        df = df.with_columns(pl.col(col_map["total_amount"]).fill_null(0.0).alias("_amount"))
    elif "unit_price" in col_map and "quantity" in col_map:
        df = to_float(df, col_map["quantity"])
        df = to_float(df, col_map["unit_price"])
        df = df.with_columns(
            (pl.col(col_map["quantity"]).fill_null(0.0) *
             pl.col(col_map["unit_price"]).fill_null(0.0)).alias("_amount")
        )
    elif "quantity" in col_map:
        df = to_float(df, col_map["quantity"])
        df = df.with_columns(pl.col(col_map["quantity"]).fill_null(0.0).alias("_amount"))
    else:
        df = to_float(df, col_map["unit_price"])
        df = df.with_columns(pl.col(col_map["unit_price"]).fill_null(0.0).alias("_amount"))
    print("  Step 2 – Monetary column computed  (Quantity × UnitPrice)")

    # Step 3 – drop zero / negative amounts
    before = len(df)
    df = df.filter(pl.col("_amount") > 0)
    print(f"  Step 3 – Drop non-positive amounts : -{before - len(df):,} rows → {len(df):,} remain")

    # Step 4 – frequency per customer
    if "invoice_no" in col_map:
        freq_agg = df.group_by(cid_col).agg(
            pl.col(col_map["invoice_no"]).n_unique().alias("Frequency")
        )
    else:
        freq_agg = df.group_by(cid_col).agg(pl.len().alias("Frequency"))
    print("  Step 4 – Frequency aggregated")

    # Step 5 – monetary per customer
    monetary_agg = df.group_by(cid_col).agg(pl.col("_amount").sum().alias("Monetary"))
    print("  Step 5 – Monetary aggregated")

    # Step 6 – recency per customer
    if "date" in col_map:
        date_col      = col_map["date"]
        df            = parse_dates(df, date_col)
        df            = df.filter(pl.col(date_col).is_not_null())
        max_date      = df[date_col].max()
        analysis_date = max_date + datetime.timedelta(days=1)
        recency_agg   = (
            df.group_by(cid_col)
            .agg(pl.col(date_col).max().alias("_last_date"))
            .with_columns(
                (pl.lit(analysis_date) - pl.col("_last_date"))
                .dt.total_days().cast(pl.Int32).alias("Recency")
            )
            .select([cid_col, "Recency"])
        )
        print(f"  Step 6 – Recency computed  (ref={analysis_date})")
    else:
        df      = df.with_row_index("_row_idx")
        max_idx = df["_row_idx"].max()
        recency_agg = (
            df.group_by(cid_col)
            .agg(pl.col("_row_idx").max().alias("_max_idx"))
            .with_columns(
                (pl.lit(max_idx) - pl.col("_max_idx")).cast(pl.Int32).alias("Recency")
            )
            .select([cid_col, "Recency"])
        )
        print("  Step 6 – Recency estimated via row-order proxy (no date column)")

    # Step 7 – join R, F, M
    rfm = (
        recency_agg
        .join(freq_agg,     on=cid_col, how="inner")
        .join(monetary_agg, on=cid_col, how="inner")
        .rename({cid_col: "CustomerID"})
    )
    print(f"  Step 7 – RFM table built  ({len(rfm):,} customers)")

    # Step 8 – log1p  (shared; reduces skewness before any scaling)
    rfm_np  = rfm.select(["Recency", "Frequency", "Monetary"]).to_numpy().astype(float)
    rfm_log = np.log1p(rfm_np)
    print("  Step 8 – log1p applied")
    print("\n  ✓ Shared pipeline done — scaling applied per-algorithm next\n")

    return rfm, rfm_log


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 9  —  algorithm-specific scaling
# ══════════════════════════════════════════════════════════════════════════════

def scale_for_kmeans(rfm_log: np.ndarray) -> np.ndarray:
    """
    Step 9a — StandardScaler for KMeans.
    KMeans minimises inertia (sum of squared Euclidean distances to centroids).
    StandardScaler (mean=0, std=1) gives equal weight to each RFM dimension,
    which is exactly what KMeans needs so no single feature dominates by scale.
    Assumes the data is roughly Gaussian after log1p — valid here.
    """
    scaler = StandardScaler()
    scaled = scaler.fit_transform(rfm_log)
    print("  Step 9a (KMeans) – StandardScaler applied  (mean=0, std=1)")
    return scaled


def scale_for_dbscan(rfm_log: np.ndarray) -> np.ndarray:
    """
    Step 9b — RobustScaler for DBSCAN.
    DBSCAN is entirely distance-based: eps is the maximum neighbourhood radius.
    RobustScaler uses median and IQR instead of mean and std, so VIP customers
    with extreme Monetary values don't distort the distance space for everyone.
    This gives DBSCAN a fairer view of density across the full customer range.
    """
    scaler = RobustScaler()
    scaled = scaler.fit_transform(rfm_log)
    print("  Step 9b (DBSCAN) – RobustScaler applied   (median=0, IQR=1)")
    return scaled


# ══════════════════════════════════════════════════════════════════════════════
#  KMEANS — optimal k via silhouette
# ══════════════════════════════════════════════════════════════════════════════

def find_optimal_k(scaled_km: np.ndarray, k_range=range(2, 9)) -> int:
    n          = len(scaled_km)
    Clusterer  = MiniBatchKMeans if n > 2_000 else KMeans
    sil_sample = min(n, 3_000)
    sil_idx    = np.random.choice(n, sil_sample, replace=False) if n > sil_sample else None
    sil_sc     = scaled_km[sil_idx] if sil_idx is not None else scaled_km

    inertias, silhouettes = [], []
    print("=" * 60)
    print("  KMEANS — optimal k search  (StandardScaler features)")
    print("=" * 60)
    for k in k_range:
        m   = Clusterer(n_clusters=k, n_init=5, random_state=RANDOM_STATE)
        lbl = m.fit_predict(scaled_km)
        inertias.append(m.inertia_ if hasattr(m, "inertia_") else np.nan)
        s = silhouette_score(sil_sc, lbl[sil_idx] if sil_idx is not None else lbl)
        silhouettes.append(s)
        print(f"  k={k}  silhouette={s:.4f}" +
              (" ← best so far" if s == max(silhouettes) else ""))

    best_k = list(k_range)[int(np.argmax(silhouettes))]
    print(f"\n  ✓ Best k = {best_k}  (silhouette={max(silhouettes):.4f})\n")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    fig.suptitle("KMeans — Optimal k Selection  (StandardScaler)", fontweight="bold")
    axes[0].plot(k_range, inertias, "o-", color=PAL[0], lw=2)
    axes[0].axvline(best_k, color="red", ls="--", label=f"k={best_k}")
    axes[0].set_xlabel("k"); axes[0].set_ylabel("Inertia (WCSS)")
    axes[0].set_title("Elbow Curve"); axes[0].legend()
    axes[1].plot(k_range, silhouettes, "o-", color=PAL[1], lw=2)
    axes[1].axvline(best_k, color="red", ls="--", label=f"k={best_k}")
    axes[1].set_xlabel("k"); axes[1].set_ylabel("Silhouette Score")
    axes[1].set_title("Silhouette Scores"); axes[1].legend()
    plt.tight_layout()
    path = f"{OUTPUT_DIR}/compare_01_kmeans_k_selection.png"
    plt.savefig(path, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  Saved: {path}")
    return best_k


# ══════════════════════════════════════════════════════════════════════════════
#  DBSCAN — grid search for best (eps, min_samples)
# ══════════════════════════════════════════════════════════════════════════════

def find_dbscan_params(scaled_db: np.ndarray) -> tuple[float, int]:
    """
    Grid-searches (eps × min_samples) on the RobustScaler feature space.
    Picks the combo that gives ≥2 real clusters and the highest silhouette.
    """
    print("=" * 60)
    print("  DBSCAN — grid search  (RobustScaler features)")
    print("=" * 60)

    n = len(scaled_db)

    # Build eps search window from the 5-NN distance distribution
    nbrs     = NearestNeighbors(n_neighbors=5).fit(scaled_db)
    dists, _ = nbrs.kneighbors(scaled_db)
    k_dists  = np.sort(dists[:, -1])

    eps_lo         = float(np.percentile(k_dists, 70))
    eps_hi         = float(np.percentile(k_dists, 95))
    eps_candidates = np.linspace(eps_lo, eps_hi, 10)
    ms_candidates  = [3, 5, 7, 10]

    print(f"  eps window    : [{eps_lo:.4f} – {eps_hi:.4f}]  (10 steps)")
    print(f"  min_samples   : {ms_candidates}\n")

    sil_sample = min(n, 3_000)
    rng        = np.random.default_rng(RANDOM_STATE)

    best_score = -1.0
    best_eps   = eps_candidates[5]
    best_ms    = 5

    print(f"  {'eps':>8}  {'min_s':>6}  {'clusters':>9}  {'noise%':>7}  {'silhouette':>11}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*9}  {'-'*7}  {'-'*11}")

    for ms in ms_candidates:
        for eps in eps_candidates:
            lbl       = DBSCAN(eps=eps, min_samples=ms).fit_predict(scaled_db)
            n_clust   = len(set(lbl)) - (1 if -1 in lbl else 0)
            n_noise   = int((lbl == -1).sum())
            noise_pct = n_noise / n * 100

            if n_clust >= 2:
                nonnoise_idx = np.where(lbl != -1)[0]
                ss     = min(len(nonnoise_idx), sil_sample)
                chosen = rng.choice(nonnoise_idx, ss, replace=False)
                sil    = silhouette_score(scaled_db[chosen], lbl[chosen])
            else:
                sil = -1.0

            flag = ""
            if n_clust >= 2 and sil > best_score:
                best_score = sil
                best_eps   = eps
                best_ms    = ms
                flag       = " ← best"

            sil_str = f"{sil:.4f}" if sil > -1 else "    n/a"
            print(f"  {eps:>8.4f}  {ms:>6}  {n_clust:>9}  {noise_pct:>6.1f}%  {sil_str:>11}{flag}")

    print(f"\n  ✓ Chosen: eps={best_eps:.4f}  min_samples={best_ms}"
          f"  silhouette={best_score:.4f}\n")

    # k-distance plot
    nbrs2     = NearestNeighbors(n_neighbors=best_ms).fit(scaled_db)
    dists2, _ = nbrs2.kneighbors(scaled_db)
    k_dists2  = np.sort(dists2[:, -1])

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(k_dists2, color=PAL[2], lw=1.5, label=f"{best_ms}-NN distance")
    ax.axhline(best_eps, color="red", ls="--", lw=2,
               label=f"chosen eps = {best_eps:.3f}")
    ax.axhspan(eps_lo, eps_hi, alpha=0.10, color="orange", label="search window")
    ax.set_xlabel("Points sorted by distance")
    ax.set_ylabel(f"{best_ms}-NN distance")
    ax.set_title(f"DBSCAN — k-Distance Plot  (RobustScaler, min_samples={best_ms})")
    ax.legend(); plt.tight_layout()
    path = f"{OUTPUT_DIR}/compare_02_dbscan_eps.png"
    plt.savefig(path, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  Saved: {path}")

    return best_eps, best_ms


# ══════════════════════════════════════════════════════════════════════════════
#  FIT MODELS
# ══════════════════════════════════════════════════════════════════════════════

def fit_kmeans(scaled_km, k):
    print(f"  Fitting KMeans  k={k}  [StandardScaler] …", end=" ", flush=True)
    t0        = time.perf_counter()
    Clusterer = MiniBatchKMeans if len(scaled_km) > 2_000 else KMeans
    labels    = Clusterer(n_clusters=k, n_init=10,
                          random_state=RANDOM_STATE).fit_predict(scaled_km)
    elapsed   = time.perf_counter() - t0
    print(f"done in {elapsed:.3f}s")
    return labels, elapsed


def fit_dbscan(scaled_db, eps, min_samples):
    print(f"  Fitting DBSCAN  eps={eps:.4f}  min_samples={min_samples}"
          f"  [RobustScaler] …", end=" ", flush=True)
    t0      = time.perf_counter()
    labels  = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(scaled_db)
    elapsed = time.perf_counter() - t0
    n_clust = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())
    print(f"done in {elapsed:.3f}s  |  clusters={n_clust}  |  noise={n_noise}")
    return labels, elapsed, n_clust, n_noise


# ══════════════════════════════════════════════════════════════════════════════
#  METRICS
# ══════════════════════════════════════════════════════════════════════════════

def evaluate(scaled, labels, name):
    """Metrics are computed on each algorithm's own scaled feature space."""
    mask = labels != -1
    X, L = scaled[mask], labels[mask]
    nc   = len(set(L))
    res  = {"Algorithm": name, "n_clusters": nc}
    if nc >= 2:
        res["Silhouette"]        = round(silhouette_score(X, L), 4)
        res["Calinski-Harabasz"] = round(calinski_harabasz_score(X, L), 4)
        res["Davies-Bouldin"]    = round(davies_bouldin_score(X, L), 4)
    else:
        res["Silhouette"] = res["Calinski-Harabasz"] = res["Davies-Bouldin"] = float("nan")
    return res


# ══════════════════════════════════════════════════════════════════════════════
#  PLOTS
# ══════════════════════════════════════════════════════════════════════════════

def plot_pca(scaled_km, scaled_db, km_lbl, db_lbl):
    """Each algorithm's clusters projected via PCA on its own scaled space."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("PCA Projection of Clusters", fontweight="bold")

    for ax, scaled, lbl, title in zip(
        axes,
        [scaled_km, scaled_db],
        [km_lbl, db_lbl],
        ["KMeans  (StandardScaler)", "DBSCAN  (RobustScaler, −1=noise)"]
    ):
        pca  = PCA(n_components=2, random_state=RANDOM_STATE)
        X2   = pca.fit_transform(scaled)
        ev   = pca.explained_variance_ratio_
        cmap = plt.cm.get_cmap("tab10", max(len(set(lbl)), 2))
        for i, u in enumerate(sorted(set(lbl))):
            mask = lbl == u
            c    = "lightgrey" if u == -1 else cmap(i)
            ax.scatter(X2[mask, 0], X2[mask, 1], c=[c],
                       s=5 if u == -1 else 12,
                       alpha=0.3 if u == -1 else 0.7,
                       label="Noise" if u == -1 else f"Cluster {u}")
        ax.set_xlabel(f"PC1 ({ev[0]:.1%})"); ax.set_ylabel(f"PC2 ({ev[1]:.1%})")
        ax.set_title(title); ax.legend(markerscale=2, fontsize=8)
    plt.tight_layout()
    path = f"{OUTPUT_DIR}/compare_03_pca_clusters.png"
    plt.savefig(path, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  Saved: {path}")


def plot_rfm_profiles(rfm, km_lbl, db_lbl):
    feats = ["Recency", "Frequency", "Monetary"]
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    fig.suptitle("Cluster RFM Profiles — Median (original scale)", fontweight="bold")
    for row, (lbl, algo) in enumerate([(km_lbl, "KMeans"), (db_lbl, "DBSCAN")]):
        tmp = rfm.to_pandas()
        tmp["Cluster"] = lbl
        tmp  = tmp[tmp["Cluster"] != -1]
        prof = tmp.groupby("Cluster")[feats].median()
        for col, feat in enumerate(feats):
            ax   = axes[row][col]
            bars = ax.bar(prof.index.astype(str), prof[feat],
                          color=PAL[:len(prof)], edgecolor="white")
            ax.set_title(f"{algo} — {feat}")
            ax.set_xlabel("Cluster"); ax.set_ylabel(feat)
            for b, v in zip(bars, prof[feat]):
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.02,
                        f"{v:.0f}", ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    path = f"{OUTPUT_DIR}/compare_04_rfm_profiles.png"
    plt.savefig(path, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  Saved: {path}")


def plot_metrics(metrics_df):
    cols  = ["Silhouette", "Calinski-Harabasz", "Davies-Bouldin"]
    notes = {"Silhouette": "↑ Higher", "Calinski-Harabasz": "↑ Higher",
             "Davies-Bouldin": "↓ Lower"}
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle("Internal Clustering Metrics Comparison\n"
                 "KMeans=StandardScaler  |  DBSCAN=RobustScaler", fontweight="bold")
    for ax, m in zip(axes, cols):
        vals  = [metrics_df[0][m], metrics_df[1][m]]
        algos = [metrics_df[0]["Algorithm"], metrics_df[1]["Algorithm"]]
        bars  = ax.bar(algos, vals, color=[PAL[0], PAL[1]], edgecolor="white", width=0.5)
        ax.set_title(f"{m}\n{notes[m]} is better", fontsize=10)
        valid = [v for v in vals if v == v]
        for b, v in zip(bars, vals):
            if v == v:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.01,
                        f"{v:.4f}", ha="center", va="bottom", fontsize=9)
        ax.set_ylim(0, max(valid) * 1.2 if valid else 1)
    plt.tight_layout()
    path = f"{OUTPUT_DIR}/compare_05_metrics.png"
    plt.savefig(path, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  Saved: {path}")


def plot_sizes(km_lbl, db_lbl):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Cluster Size Distribution", fontweight="bold")
    for ax, lbl, title in zip(
        axes, [km_lbl, db_lbl],
        ["KMeans  (StandardScaler)", "DBSCAN  (RobustScaler)"]
    ):
        unique, counts = np.unique(lbl, return_counts=True)
        slabels = ["Noise" if u == -1 else f"Cluster {u}" for u in unique]
        colors  = ["lightgrey" if u == -1 else PAL[i % 10] for i, u in enumerate(unique)]
        ax.pie(counts, labels=slabels, colors=colors, autopct="%1.1f%%",
               startangle=140, pctdistance=0.85)
        ax.set_title(title)
    plt.tight_layout()
    path = f"{OUTPUT_DIR}/compare_06_cluster_sizes.png"
    plt.savefig(path, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  Saved: {path}")


def plot_scaler_comparison(rfm_log):
    """
    Extra plot: shows what StandardScaler vs RobustScaler does to the
    Monetary feature distribution — so the difference is visually clear.
    """
    std_scaled    = StandardScaler().fit_transform(rfm_log)
    robust_scaled = RobustScaler().fit_transform(rfm_log)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    fig.suptitle("Effect of Scaler on Feature Distributions  (Monetary shown)",
                 fontweight="bold")
    labels_plot = ["Recency", "Frequency", "Monetary"]
    for i, (ax, feat) in enumerate(zip(axes, labels_plot)):
        ax.hist(rfm_log[:, i],    bins=60, alpha=0.5, label="log1p only",   color=PAL[2])
        ax.hist(std_scaled[:, i], bins=60, alpha=0.5, label="StandardScaler", color=PAL[0])
        ax.hist(robust_scaled[:, i], bins=60, alpha=0.5,
                label="RobustScaler",  color=PAL[1])
        ax.set_title(feat); ax.set_xlabel("Scaled value"); ax.set_ylabel("Count")
        ax.legend(fontsize=8)
    plt.tight_layout()
    path = f"{OUTPUT_DIR}/compare_00_scaler_comparison.png"
    plt.savefig(path, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  Saved: {path}")


# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY TABLE
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(km_m, db_m, km_t, db_t, km_k, db_n, db_noise,
                  n_customers, best_eps, best_ms):
    sep = "═" * 66
    def fmt(v): return f"{v:.4f}" if v == v else "n/a"

    print(f"\n{sep}")
    print("  PERFORMANCE COMPARISON SUMMARY")
    print(sep)
    print(f"  Dataset      : Online Retail  ({n_customers:,} customers)")
    print(f"  Features     : Recency · Frequency · Monetary  (log1p)")
    print(f"  KMeans scaler: StandardScaler  (mean=0, std=1)")
    print(f"  DBSCAN scaler: RobustScaler    (median=0, IQR=1)")
    print(f"  DBSCAN params: eps={best_eps:.4f}  min_samples={best_ms}  (grid-searched)")
    print(sep)
    print(f"  {'Metric':<28} {'KMeans':>16} {'DBSCAN':>16}")
    print(f"  {'-'*28} {'-'*16} {'-'*16}")
    print(f"  {'n_clusters':<28} {km_k:>16} {db_n:>16}")
    print(f"  {'Noise points':<28} {'n/a':>16} {db_noise:>16}")
    print(f"  {'Training time (s)':<28} {km_t:>16.4f} {db_t:>16.4f}")
    print(f"  {'Silhouette Score':<28} {fmt(km_m['Silhouette']):>16} {fmt(db_m['Silhouette']):>16}")
    print(f"  {'Calinski-Harabasz':<28} {fmt(km_m['Calinski-Harabasz']):>16} {fmt(db_m['Calinski-Harabasz']):>16}")
    print(f"  {'Davies-Bouldin':<28} {fmt(km_m['Davies-Bouldin']):>16} {fmt(db_m['Davies-Bouldin']):>16}")
    print(sep)
    print("  GUIDE: Silhouette & Calinski-Harabasz → higher is better")
    print("         Davies-Bouldin                 → lower  is better")
    print("         DBSCAN metrics exclude noise points (label = −1)")
    print(sep + "\n")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # ── Shared Steps 1-8 ──────────────────────────────────────────────────────
    rfm, rfm_log = build_rfm_log()
    n_customers  = len(rfm)

    # ── Step 9 — split scaling ────────────────────────────────────────────────
    print("=" * 60)
    print("  STEP 9 — algorithm-specific scaling")
    print("=" * 60)
    scaled_km = scale_for_kmeans(rfm_log)   # StandardScaler → KMeans
    scaled_db = scale_for_dbscan(rfm_log)   # RobustScaler   → DBSCAN
    print()

    # ── Scaler comparison plot (bonus) ────────────────────────────────────────
    print("=" * 60)
    print("  SCALER COMPARISON PLOT")
    print("=" * 60)
    plot_scaler_comparison(rfm_log)
    print()

    # ── KMeans ────────────────────────────────────────────────────────────────
    best_k             = find_optimal_k(scaled_km)
    km_labels, km_time = fit_kmeans(scaled_km, best_k)
    print()

    # ── DBSCAN ────────────────────────────────────────────────────────────────
    best_eps, best_ms                  = find_dbscan_params(scaled_db)
    db_labels, db_time, db_n, db_noise = fit_dbscan(scaled_db, best_eps, best_ms)
    print()

    # ── Evaluate (each on its own scaled space) ────────────────────────────────
    km_metrics = evaluate(scaled_km, km_labels, "KMeans")
    db_metrics = evaluate(scaled_db, db_labels, "DBSCAN")

    # ── Plots ─────────────────────────────────────────────────────────────────
    print("=" * 60)
    print("  GENERATING COMPARISON PLOTS")
    print("=" * 60)
    plot_pca(scaled_km, scaled_db, km_labels, db_labels)
    plot_rfm_profiles(rfm, km_labels, db_labels)
    plot_metrics([km_metrics, db_metrics])
    plot_sizes(km_labels, db_labels)

    # ── Save CSV ───────────────────────────────────────────────────────────────
    out = rfm.to_pandas()[["CustomerID", "Recency", "Frequency", "Monetary"]].copy()
    out["KMeans_Cluster"] = km_labels
    out["DBSCAN_Cluster"]  = db_labels
    csv_path = f"{OUTPUT_DIR}/compare_rfm_results.csv"
    out.to_csv(csv_path, index=False)
    print(f"  Saved: {csv_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print_summary(km_metrics, db_metrics, km_time, db_time,
                  best_k, db_n, db_noise, n_customers, best_eps, best_ms)


if __name__ == "__main__":
    main()
