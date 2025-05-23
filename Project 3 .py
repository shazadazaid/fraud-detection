# -*- coding: utf-8 -*-
"""Untitled17.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1qUvm7KDOaOnj7GPqEZDjZvBNe19n-Gj3
"""

# Install all required packages
!pip install -q flask flask-cors pandas scikit-learn joblib pyngrok pywebio plotly

# Import libraries
from flask import Flask, request, jsonify
from flask_cors import CORS
from pywebio import start_server
from pywebio.input import *
from pywebio.output import *
from pywebio.platform.flask import webio_view
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
import sqlite3
from datetime import datetime
import plotly.express as px
from pyngrok import ngrok
import warnings
warnings.filterwarnings('ignore')

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize database
def init_db():
    conn = sqlite3.connect('transactions.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 amount REAL,
                 merchant TEXT,
                 category TEXT,
                 customer_id TEXT,
                 timestamp DATETIME,
                 is_fraud INTEGER,
                 probability REAL)''')
    conn.commit()
    conn.close()

# Load or train model
def get_model():
    try:
        model = joblib.load('fraud_model.pkl')
        scaler = joblib.load('scaler.pkl')
        model_columns = joblib.load('model_columns.pkl')
    except:
        # Generate synthetic data if no model exists
        np.random.seed(42)
        data = {
            'amount': np.concatenate([np.random.normal(50, 15, 950), np.random.normal(500, 200, 50)]),
            'merchant': np.random.choice(['Amazon', 'Walmart', 'Target', 'BestBuy', 'Starbucks'], 1000),
            'category': np.random.choice(['Retail', 'Food', 'Electronics', 'Services'], 1000),
            'customer_id': ['CUST'+str(i).zfill(4) for i in range(1000)],
            'is_fraud': [0]*950 + [1]*50
        }
        df = pd.DataFrame(data)

        # Feature engineering
        df = pd.get_dummies(df, columns=['merchant', 'category'])
        model_columns = df.drop(['customer_id', 'is_fraud'], axis=1).columns
        joblib.dump(model_columns, 'model_columns.pkl')

        X = df.drop(['customer_id', 'is_fraud'], axis=1)
        y = df['is_fraud']

        # Train model
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = IsolationForest(contamination=0.05, random_state=42)
        model.fit(X_scaled)

        # Save model
        joblib.dump(model, 'fraud_model.pkl')
        joblib.dump(scaler, 'scaler.pkl')

    return model, scaler, model_columns

model, scaler, model_columns = get_model()
init_db()

# API Endpoints
@app.route('/predict', methods=['POST'])
def predict():
    data = request.json
    transaction = pd.DataFrame([{
        'amount': data['amount'],
        'merchant': data['merchant'],
        'category': data['category']
    }])

    # Feature engineering
    transaction = pd.get_dummies(transaction)

    # Ensure all columns match training data
    for col in model_columns:
        if col not in transaction.columns:
            transaction[col] = 0
    transaction = transaction[model_columns]

    # Scale and predict
    X_scaled = scaler.transform(transaction)
    proba = model.decision_function(X_scaled)[0]
    is_fraud = 1 if proba < -0.1 else 0  # Threshold

    # Store transaction
    conn = sqlite3.connect('transactions.db')
    c = conn.cursor()
    c.execute('''INSERT INTO transactions
                 (amount, merchant, category, customer_id, timestamp, is_fraud, probability)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (data['amount'], data['merchant'], data['category'],
               data.get('customer_id', 'ANON'), datetime.now(), is_fraud, float(proba)))
    conn.commit()
    conn.close()

    return jsonify({
        'is_fraud': bool(is_fraud),
        'probability': float(proba),
        'alert': is_fraud == 1
    })

@app.route('/dashboard', methods=['GET'])
def dashboard():
    conn = sqlite3.connect('transactions.db')
    df = pd.read_sql('SELECT * FROM transactions', conn)
    conn.close()

    if df.empty:
        return jsonify({})

    # Generate insights
    fraud_rate = df['is_fraud'].mean()
    high_risk_merchants = df[df['is_fraud']==1]['merchant'].value_counts().to_dict()
    time_patterns = df.groupby([df['timestamp'].str[:13]])['is_fraud'].mean().to_dict()

    return jsonify({
        'total_transactions': len(df),
        'fraud_rate': fraud_rate,
        'high_risk_merchants': high_risk_merchants,
        'time_patterns': time_patterns,
        'recent_transactions': df.sort_values('timestamp', ascending=False).head(10).to_dict('records')
    })

# Web Interface
def fraud_detection_app():
    put_markdown("# 🕵️ Fraud Detection System")

    # Transaction Form
    with put_collapse("New Transaction Analysis", open=True):
        transaction_data = input_group("Enter Transaction Details", [
            input("Amount", name="amount", type=FLOAT, required=True),
            input("Merchant", name="merchant", required=True),
            select("Category", name="category",
                  options=['Retail', 'Food', 'Electronics', 'Services']),
            input("Customer ID (optional)", name="customer_id")
        ])

        if transaction_data:
            with put_loading():
                response = requests.post('http://localhost:5000/predict',
                                      json=transaction_data).json()

            if response['alert']:
                put_error(f"🚨 Fraud Detected! (Confidence: {response['probability']*100:.2f}%)")
            else:
                put_success(f"✅ Transaction Normal (Confidence: {response['probability']*100:.2f}%)")

    # Dashboard
    with put_collapse("Live Dashboard", open=True):
        while True:
            data = requests.get('http://localhost:5000/dashboard').json()

            if not data:
                put_text("No transaction data available yet")
                break

            put_row([
                put_card(f"Total Transactions: {data['total_transactions']}",
                        style="width: 200px; text-align: center"),
                put_card(f"Fraud Rate: {data['fraud_rate']*100:.2f}%",
                        style="width: 200px; text-align: center; color: red"),
                put_card(f"High Risk Merchants: {len(data['high_risk_merchants'])}",
                        style="width: 200px; text-align: center")
            ], size="1fr 1fr 1fr")

            # Time pattern chart
            time_df = pd.DataFrame({
                'Hour': list(data['time_patterns'].keys()),
                'Fraud Rate': list(data['time_patterns'].values())
            })
            fig = px.line(time_df, x='Hour', y='Fraud Rate',
                         title="Fraud Rate by Hour")
            put_html(fig.to_html(include_plotlyjs='cdn'))

            # Merchant risk chart
            merchant_df = pd.DataFrame({
                'Merchant': list(data['high_risk_merchants'].keys()),
                'Fraud Count': list(data['high_risk_merchants'].values())
            })
            fig = px.bar(merchant_df, x='Merchant', y='Fraud Count',
                         title="High Risk Merchants")
            put_html(fig.to_html(include_plotlyjs='cdn'))

            # Recent transactions table
            put_table([
                ['Amount', 'Merchant', 'Category', 'Time', 'Status']
            ] + [
                [
                    f"${tx['amount']}",
                    tx['merchant'],
                    tx['category'],
                    tx['timestamp'][11:19],
                    put_text("Fraud", style="color: red") if tx['is_fraud'] else put_text("Normal", style="color: green")
                ] for tx in data['recent_transactions']
            ])

            # Refresh every 10 seconds
            time.sleep(10)
            clear()

# Configure Flask routes
app.add_url_rule('/', 'webio_view', webio_view(fraud_detection_app),
                 methods=['GET', 'POST', 'OPTIONS'])

# Run the app
if __name__ == '__main__':
    import threading
    import requests
    import time

    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=app.run, kwargs={'port': 5000})
    flask_thread.daemon = True
    flask_thread.start()

    # Set up ngrok tunnel
    ngrok.set_auth_token("YOUR_NGROK_AUTH_TOKEN")  # Replace with your ngrok token
    public_url = ngrok.connect(5000).public_url
    print(f" * Running on {public_url}")

    # Start PyWebIO app
    start_server(fraud_detection_app, port=5000, debug=True)