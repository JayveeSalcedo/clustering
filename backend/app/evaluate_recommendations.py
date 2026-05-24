"""
evaluate_recommendations.py
============================
Standalone evaluation script for the FP-Growth product recommendation engine.
Mirrors the exact logic used in backend/app/recommend.py so results are
directly comparable to what the system produces.

HOW TO RUN:
    1. Place your dataset (e.g. Online Retail.xlsx) somewhere accessible.
    2. Set DATASET_PATH below.
    3. Run:  python evaluate_recommendations.py
    4. Results are printed to console and saved to recommendation_eval_report.txt

WHAT IT EVALUATES:
    ┌─────────────────────────────────────────────────────────────┐
    │  Rule Quality Metrics  │ support, confidence, lift, leverage│
    │  Coverage Metrics      │ catalog coverage, transaction cov. │
    │  Threshold Sensitivity │ how results change across settings  │
    │  Train/Test Holdout    │ tests rules on unseen transactions  │
    │  Rule Diversity        │ unique products recommended         │
    └─────────────────────────────────────────────────────────────┘

REQUIREMENTS:
    pip install polars mlxtend pandas openpyxl numpy scikit-learn tabulate
"""

import io
import os
import sys
import time
import warnings
from datetime import datetime
from collections import defaultdict

import numpy as np
import pandas as pd
import polars as pl
from mlxtend.frequent_patterns import fpgrowth, association_rules
from tabulate import tabulate

warnings.filterwarnings("ignore")

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
DATASET_PATH   = r"C:\Users\ACER\Desktop\dataset\Online Retail.xlsx"   # ← change if needed
MIN_SUPPORT    = 0.02       # default used in recommend.py
MIN_CONFIDENCE = 0.20       # default used in recommend.py
TOP_N          = 30         # same cap as recommend.py
TEST_SPLIT     = 0.20       # 20% of invoices held out for holdout evaluation
REPORT_FILE    = "recommendation_eval_report.txt"

# ── COLUMN ALIASES (mirrors utils.py COLUMN_ALIASES) ─────────────────────────
INVOICE_ALIASES = ["invoiceno","invoice_no","transactionid","transaction_id",
                   "orderid","order_id","invoice","receipt_id","txn_id"]
PRODUCT_ALIASES = ["description","product","product_name","productname","item",
                   "item_name","itemname","sku_name","article_name"]
CUSTID_ALIASES  = ["customerid","customer_id","custid","client_id","cust_id",
                   "userid","user_id"]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def resolve_col(df_cols: list[str], aliases: list[str]) -> str | None:
    """Return the first column name that matches any alias (case-insensitive)."""
    lower_map = {c.lower().strip().replace(" ", "_"): c for c in df_cols}
    for alias in aliases:
        if alias.lower().replace(" ", "_") in lower_map:
            return lower_map[alias.lower().replace(" ", "_")]
    return None


def load_dataset(path: str) -> pl.DataFrame:
    """Load CSV or Excel file into a Polars DataFrame."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pl.read_csv(path, infer_schema_length=10_000,
                           ignore_errors=True,
                           null_values=["", "NA", "N/A", "null", "NULL"])
    elif ext == ".xlsx":
        try:
            return pl.read_excel(path, engine="calamine")
        except Exception:
            return pl.from_pandas(pd.read_excel(path, engine="openpyxl"))
    elif ext == ".xls":
        return pl.from_pandas(pd.read_excel(path, engine="xlrd"))
    else:
        raise ValueError(f"Unsupported format: {ext}")


def build_basket(df: pl.DataFrame, inv_col: str, prod_col: str) -> pd.DataFrame:
    """Build boolean invoice×product basket matrix (mirrors recommend.py logic)."""
    basket = (
        df.select([inv_col, prod_col])
        .unique()
        .with_columns(pl.lit(True).alias("_present"))
        .pivot(index=inv_col, on=prod_col, values="_present")
        .fill_null(False)
    )
    return basket.drop(inv_col).to_pandas().astype(bool)


def run_fpgrowth(basket_pd: pd.DataFrame,
                 min_support: float,
                 min_confidence: float,
                 top_n: int) -> pd.DataFrame:
    """Run FP-Growth + association_rules exactly as recommend.py does."""
    freq = fpgrowth(basket_pd, min_support=min_support, use_colnames=True)
    if freq.empty:
        return pd.DataFrame()
    rules = association_rules(
        freq, metric="confidence",
        min_threshold=min_confidence,
        num_itemsets=len(freq)
    )
    if rules.empty:
        return pd.DataFrame()
    return rules.sort_values("lift", ascending=False).head(top_n)


def section(title: str) -> str:
    bar = "═" * 70
    return f"\n{bar}\n  {title}\n{bar}\n"


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def eval_rule_quality(rules: pd.DataFrame) -> dict:
    """Summarise core rule metrics — the bread and butter of association rule eval."""
    if rules.empty:
        return {}

    leverage   = rules["support"] - (rules["antecedent support"] * rules["consequent support"])
    conviction = rules["confidence"].apply(
        lambda c: (1 - rules["consequent support"].mean()) / (1 - c + 1e-9) if c < 1 else float("inf")
    )

    return {
        "total_rules":            len(rules),
        "avg_support":            round(rules["support"].mean(), 4),
        "avg_confidence":         round(rules["confidence"].mean(), 4),
        "avg_lift":               round(rules["lift"].mean(), 4),
        "max_lift":               round(rules["lift"].max(), 4),
        "min_lift":               round(rules["lift"].min(), 4),
        "rules_lift_gt_1":        int((rules["lift"] > 1).sum()),
        "rules_lift_gt_2":        int((rules["lift"] > 2).sum()),
        "rules_lift_gt_3":        int((rules["lift"] > 3).sum()),
        "avg_leverage":           round(float(leverage.mean()), 4),
        "avg_antecedent_len":     round(rules["antecedents"].apply(len).mean(), 2),
        "avg_consequent_len":     round(rules["consequents"].apply(len).mean(), 2),
    }


def eval_coverage(rules: pd.DataFrame, all_products: set, n_transactions: int,
                  basket_pd: pd.DataFrame) -> dict:
    """How much of the catalog and transaction space does the rule set cover?"""
    if rules.empty:
        return {}

    recommended = set()
    for items in rules["consequents"]:
        recommended.update(items)
    antecedent_products = set()
    for items in rules["antecedents"]:
        antecedent_products.update(items)

    catalog_coverage     = len(recommended | antecedent_products) / max(len(all_products), 1)
    recommended_coverage = len(recommended) / max(len(all_products), 1)

    # Transaction coverage: fraction of transactions that contain at least one antecedent
    antecedent_cols = [c for c in basket_pd.columns if c in antecedent_products]
    if antecedent_cols:
        covered_txns = basket_pd[antecedent_cols].any(axis=1).sum()
    else:
        covered_txns = 0

    return {
        "unique_products_in_rules":  len(recommended | antecedent_products),
        "catalog_coverage_pct":      round(catalog_coverage * 100, 2),
        "recommended_products":      len(recommended),
        "recommended_coverage_pct":  round(recommended_coverage * 100, 2),
        "transaction_coverage_pct":  round(covered_txns / max(n_transactions, 1) * 100, 2),
    }


def eval_threshold_sensitivity(basket_pd: pd.DataFrame) -> list[dict]:
    """
    Test multiple support + confidence combinations.
    Shows how the number of rules and average lift change with thresholds.
    Mirrors the sliders the user controls in the frontend.
    """
    combos = [
        (0.01, 0.10), (0.01, 0.20), (0.01, 0.30),
        (0.02, 0.10), (0.02, 0.20), (0.02, 0.30),
        (0.03, 0.20), (0.05, 0.20), (0.05, 0.30),
        (0.10, 0.30), (0.10, 0.50),
    ]
    rows = []
    for sup, conf in combos:
        try:
            freq = fpgrowth(basket_pd, min_support=sup, use_colnames=True)
            if freq.empty:
                n_rules, avg_lift = 0, 0.0
            else:
                r = association_rules(freq, metric="confidence",
                                      min_threshold=conf, num_itemsets=len(freq))
                n_rules  = len(r)
                avg_lift = round(r["lift"].mean(), 3) if not r.empty else 0.0
        except Exception:
            n_rules, avg_lift = 0, 0.0

        rows.append({
            "min_support":    sup,
            "min_confidence": conf,
            "n_rules":        n_rules,
            "avg_lift":       avg_lift,
        })
    return rows


def eval_holdout(df: pl.DataFrame, inv_col: str, prod_col: str,
                 min_support: float, min_confidence: float,
                 test_split: float) -> dict:
    """
    Train/test holdout evaluation.

    - Split invoices: 80% train, 20% test (no data leakage).
    - Train FP-Growth on train basket → generate rules.
    - For each test invoice, hide half its items (input) and try to predict
      the other half (ground truth) using the rules.

    Metrics reported:
        Precision@K  — of recommended products, fraction that were actually bought
        Recall@K     — of actually bought products, fraction that were recommended
        Hit Rate     — fraction of test invoices where ≥1 recommendation was correct
    """
    all_invoices = df[inv_col].unique().to_list()
    np.random.seed(42)
    np.random.shuffle(all_invoices)

    split_idx      = int(len(all_invoices) * (1 - test_split))
    train_invoices = set(all_invoices[:split_idx])
    test_invoices  = set(all_invoices[split_idx:])

    train_df = df.filter(pl.col(inv_col).is_in(train_invoices))
    test_df  = df.filter(pl.col(inv_col).is_in(test_invoices))

    # Build train basket and mine rules
    try:
        train_basket = build_basket(train_df, inv_col, prod_col)
        freq  = fpgrowth(train_basket, min_support=min_support, use_colnames=True)
        if freq.empty:
            return {"error": "No frequent items in training set"}
        rules = association_rules(freq, metric="confidence",
                                  min_threshold=min_confidence,
                                  num_itemsets=len(freq))
        if rules.empty:
            return {"error": "No rules generated from training set"}
    except Exception as e:
        return {"error": str(e)}

    # Build antecedent → consequent lookup from rules
    rule_lookup: dict[frozenset, list[set]] = defaultdict(list)
    for _, row in rules.iterrows():
        rule_lookup[frozenset(row["antecedents"])].append(set(row["consequents"]))

    # Evaluate on test invoices
    precisions, recalls, hits = [], [], []

    test_grouped = (
        test_df.group_by(inv_col)
        .agg(pl.col(prod_col).unique().alias("products"))
    )

    for row in test_grouped.iter_rows(named=True):
        products = list(row["products"])
        if len(products) < 2:
            continue

        # Split: first half = input basket, second half = ground truth
        half        = max(1, len(products) // 2)
        input_items = set(products[:half])
        true_items  = set(products[half:])

        # Find all rules whose antecedent is a subset of the input basket
        recommended: set = set()
        for ant, conseqs in rule_lookup.items():
            if ant.issubset(input_items):
                for c in conseqs:
                    recommended.update(c)
        # Remove items already in the basket
        recommended -= input_items

        if not recommended:
            precisions.append(0.0)
            recalls.append(0.0)
            hits.append(0)
            continue

        correct    = recommended & true_items
        precision  = len(correct) / len(recommended)
        recall     = len(correct) / len(true_items)
        hit        = 1 if correct else 0

        precisions.append(precision)
        recalls.append(recall)
        hits.append(hit)

    if not precisions:
        return {"error": "No evaluable test invoices (all have < 2 products)"}

    avg_p   = round(float(np.mean(precisions)), 4)
    avg_r   = round(float(np.mean(recalls)), 4)
    f1      = round(2 * avg_p * avg_r / (avg_p + avg_r + 1e-9), 4)
    hit_rate= round(float(np.mean(hits)) * 100, 2)

    return {
        "train_invoices":       len(train_invoices),
        "test_invoices":        len(test_invoices),
        "evaluable_invoices":   len(precisions),
        "avg_precision":        avg_p,
        "avg_recall":           avg_r,
        "f1_score":             f1,
        "hit_rate_pct":         hit_rate,
    }


def eval_rule_diversity(rules: pd.DataFrame) -> dict:
    """
    Check whether the recommendation engine recommends a diverse range of
    products or keeps repeating the same few items.
    """
    if rules.empty:
        return {}

    all_consequents = []
    for items in rules["consequents"]:
        all_consequents.extend(list(items))

    freq_map = defaultdict(int)
    for p in all_consequents:
        freq_map[p] += 1

    total       = len(all_consequents)
    unique      = len(freq_map)
    top5        = sorted(freq_map.items(), key=lambda x: x[1], reverse=True)[:5]
    top5_share  = sum(v for _, v in top5) / max(total, 1)

    return {
        "unique_recommended_products": unique,
        "total_consequent_appearances": total,
        "top5_concentration_pct":      round(top5_share * 100, 2),
        "top_5_recommended":           [p for p, _ in top5],
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    lines = []   # collect all output lines for the report file

    def log(text=""):
        print(text)
        lines.append(text)

    log(f"{'='*70}")
    log(f"  FP-GROWTH RECOMMENDATION EVALUATION REPORT")
    log(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Dataset  : {DATASET_PATH}")
    log(f"{'='*70}")

    # ── Load dataset ──────────────────────────────────────────────────────────
    log("\nLoading dataset...")
    t0 = time.time()
    df = load_dataset(DATASET_PATH)
    log(f"  Loaded {len(df):,} rows × {len(df.columns)} columns in {time.time()-t0:.2f}s")

    # ── Resolve columns ───────────────────────────────────────────────────────
    inv_col  = resolve_col(df.columns, INVOICE_ALIASES)
    prod_col = resolve_col(df.columns, PRODUCT_ALIASES)
    cid_col  = resolve_col(df.columns, CUSTID_ALIASES)

    if not inv_col:
        log("ERROR: Could not find invoice/transaction ID column. Aborting.")
        sys.exit(1)
    if not prod_col:
        log("ERROR: Could not find product/description column. Aborting.")
        sys.exit(1)

    log(f"  Invoice column  : {inv_col}")
    log(f"  Product column  : {prod_col}")
    log(f"  Customer column : {cid_col or 'not found (not required)'}")

    # ── Clean (mirrors recommend.py cleaning) ─────────────────────────────────
    df = (
        df
        .filter(pl.col(inv_col).is_not_null() & pl.col(prod_col).is_not_null())
        .with_columns(
            pl.col(prod_col).cast(pl.Utf8).str.strip_chars().alias(prod_col),
            pl.col(inv_col).cast(pl.Utf8).str.strip_chars().alias(inv_col),
        )
        .filter((pl.col(prod_col) != "") & (pl.col(inv_col) != ""))
    )

    n_transactions = df[inv_col].n_unique()
    n_products     = df[prod_col].n_unique()
    all_products   = set(df[prod_col].unique().to_list())

    log(f"\n  Unique transactions : {n_transactions:,}")
    log(f"  Unique products     : {n_products:,}")
    log(f"  Total rows (clean)  : {len(df):,}")

    # ── Build basket matrix ───────────────────────────────────────────────────
    log("\nBuilding basket matrix...")
    t0 = time.time()
    basket_pd = build_basket(df, inv_col, prod_col)
    log(f"  Basket shape: {basket_pd.shape[0]:,} invoices × {basket_pd.shape[1]:,} products ({time.time()-t0:.2f}s)")

    # ── Run FP-Growth (same settings as system default) ───────────────────────
    log(f"\nRunning FP-Growth (support={MIN_SUPPORT}, confidence={MIN_CONFIDENCE}, top_n={TOP_N})...")
    t0 = time.time()
    rules = run_fpgrowth(basket_pd, MIN_SUPPORT, MIN_CONFIDENCE, TOP_N)
    log(f"  Done in {time.time()-t0:.2f}s — {len(rules)} rules returned")

    if rules.empty:
        log("\nWARNING: No rules generated at default thresholds.")
        log("Try lowering min_support or min_confidence in the CONFIGURATION block.")
        sys.exit(0)

    # ── 1. Rule Quality Metrics ───────────────────────────────────────────────
    log(section("1. RULE QUALITY METRICS"))
    quality = eval_rule_quality(rules)
    rows = [[k.replace("_", " ").title(), v] for k, v in quality.items()]
    log(tabulate(rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))

    # ── 2. Top 10 Rules by Lift ───────────────────────────────────────────────
    log(section("2. TOP 10 RULES BY LIFT"))
    top10 = rules.head(10).copy()
    top10["antecedents"] = top10["antecedents"].apply(lambda x: ", ".join(sorted(x)))
    top10["consequents"] = top10["consequents"].apply(lambda x: ", ".join(sorted(x)))
    top10_display = top10[["antecedents", "consequents", "support", "confidence", "lift"]].copy()
    top10_display.columns = ["IF (buy)", "THEN (recommend)", "Support", "Confidence", "Lift"]
    log(tabulate(top10_display.values.tolist(),
                 headers=top10_display.columns.tolist(),
                 tablefmt="rounded_outline", floatfmt=".4f"))

    # ── 3. Coverage Metrics ───────────────────────────────────────────────────
    log(section("3. COVERAGE METRICS"))
    coverage = eval_coverage(rules, all_products, n_transactions, basket_pd)
    rows = [[k.replace("_", " ").title(), v] for k, v in coverage.items()]
    log(tabulate(rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))

    # ── 4. Rule Diversity ─────────────────────────────────────────────────────
    log(section("4. RULE DIVERSITY"))
    diversity = eval_rule_diversity(rules)
    top5 = diversity.pop("top_5_recommended", [])
    rows = [[k.replace("_", " ").title(), v] for k, v in diversity.items()]
    log(tabulate(rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))
    log(f"\n  Top 5 most-recommended products:")
    for i, p in enumerate(top5, 1):
        log(f"    {i}. {p}")

    # ── 5. Threshold Sensitivity ──────────────────────────────────────────────
    log(section("5. THRESHOLD SENSITIVITY ANALYSIS"))
    log("  Testing 11 support × confidence combinations...\n")
    sensitivity = eval_threshold_sensitivity(basket_pd)
    sens_rows = [[r["min_support"], r["min_confidence"], r["n_rules"], r["avg_lift"]]
                 for r in sensitivity]
    log(tabulate(sens_rows,
                 headers=["Min Support", "Min Confidence", "N Rules", "Avg Lift"],
                 tablefmt="rounded_outline", floatfmt=".3f"))
    log(f"\n  ★ System default: support={MIN_SUPPORT}, confidence={MIN_CONFIDENCE}"
        f" → {quality['total_rules']} rules, avg lift={quality['avg_lift']}")

    # ── 6. Train / Test Holdout ───────────────────────────────────────────────
    log(section("6. TRAIN / TEST HOLDOUT EVALUATION (80/20 split)"))
    log("  Mining rules on 80% of invoices, testing on 20%...\n")
    holdout = eval_holdout(df, inv_col, prod_col, MIN_SUPPORT, MIN_CONFIDENCE, TEST_SPLIT)
    if "error" in holdout:
        log(f"  WARNING: {holdout['error']}")
    else:
        rows = [[k.replace("_", " ").title(), v] for k, v in holdout.items()]
        log(tabulate(rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))
        log("\n  Interpretation:")
        log(f"    Hit Rate {holdout['hit_rate_pct']}% — percentage of test baskets where")
        log(f"    at least one recommendation was actually purchased.")
        log(f"    Precision {holdout['avg_precision']} — of all products recommended, this")
        log(f"    fraction were genuinely in the customer's basket.")
        log(f"    Recall {holdout['avg_recall']} — of all products actually bought, this")
        log(f"    fraction were successfully recommended by the rules.")

    # ── Summary ───────────────────────────────────────────────────────────────
    log(section("SUMMARY"))
    log(f"  Dataset          : {os.path.basename(DATASET_PATH)}")
    log(f"  Transactions     : {n_transactions:,}")
    log(f"  Products         : {n_products:,}")
    log(f"  Rules generated  : {quality.get('total_rules', 0)}")
    log(f"  Avg lift         : {quality.get('avg_lift', 0)}")
    log(f"  Rules with lift>2: {quality.get('rules_lift_gt_2', 0)}")
    log(f"  Catalog coverage : {coverage.get('catalog_coverage_pct', 0)}%")
    if "hit_rate_pct" in holdout:
        log(f"  Hit rate (test)  : {holdout['hit_rate_pct']}%")
        log(f"  Precision        : {holdout['avg_precision']}")
        log(f"  Recall           : {holdout['avg_recall']}")
        log(f"  F1 Score         : {holdout['avg_f1_score'] if 'avg_f1_score' in holdout else holdout.get('f1_score', '-')}")

    log(f"\n{'='*70}")
    log(f"  Report saved to: {REPORT_FILE}")
    log(f"{'='*70}\n")

    # ── Save report to file ───────────────────────────────────────────────────
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nDone. Report saved to {REPORT_FILE}")


if __name__ == "__main__":
    main()