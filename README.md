# RFM Customer Segmentation App

A full-stack web app that performs RFM (Recency, Frequency, Monetary) analysis and K-Means clustering on retail transaction data. Automatically selects the optimal number of clusters using Silhouette Scores.

## Project Structure
```
clustering/
├── backend/
│   ├── main.py
│   └── requirements.txt
└── frontend/
    ├── public/index.html
    ├── package.json
    └── src/
        ├── index.js / index.css
        ├── App.js / App.css
        └── components/
            ├── FileUpload.js / FileUpload.css
            └── Results.js / Results.css
```

## Quick Start

### 1 — Backend (FastAPI)
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2 — Frontend (React)
```bash
cd frontend
npm install
npm start
```

Then open **http://localhost:3000**

---

## Dataset Compatibility

Supports any CSV/Excel with these columns (auto-detected):

| Canonical      | Accepted names                                            |
|----------------|-----------------------------------------------------------|
| Customer ID    | CustomerID, Customer_ID, UserID, CustID …                 |
| Date           | Date, InvoiceDate, Transaction_Date, OrderDate …          |
| Amount         | Total_Amount, UnitPrice × Quantity, Price_per_Unit …      |
| Invoice (opt.) | InvoiceNo, Transaction_ID, OrderID …                      |

Tested with the [Retail Transactions Dataset](https://www.kaggle.com/datasets/prasad22/retail-transactions-dataset/data) on Kaggle.

---

## How It Works

1. **Upload** a CSV or Excel file.
2. **RFM Computation**
   - **Recency** – days since last purchase (per customer)
   - **Frequency** – number of distinct transactions
   - **Monetary** – total spend
3. **Preprocessing** – log1p transform → StandardScaler
4. **Auto k-Selection** – tries k = 2…8, picks the k with the highest Silhouette Score. Uses `MiniBatchKMeans` for datasets > 10 000 customers.
5. **Cluster Profiles** – mean/median R, F, M per segment + descriptive labels (Champions, Loyal, At Risk, …)

---

## Performance Notes
- MiniBatchKMeans kicks in above 10 k customers for speed.
- Silhouette is computed on a 5 k random sample when the dataset exceeds 5 k rows.
- Works on files with millions of rows — memory is the main constraint.
