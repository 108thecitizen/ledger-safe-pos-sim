import os
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Ledger-Safe Ops Console", layout="wide")
st.title("Ledger-Safe Ops Console (MVP)")

st.caption("Step 1: Prove the stack runs end-to-end (UI -> API -> DB).")

col1, col2 = st.columns([1, 2])

with col1:
    if st.button("Refresh health"):
        st.rerun()

with col2:
    st.write(f"API Base URL: `{API_BASE_URL}`")

try:
    r = requests.get(f"{API_BASE_URL}/v1/health", timeout=3)
    r.raise_for_status()
    data = r.json()
    st.success(f"API status: {data.get('status')} | DB: {data.get('db')}")
    st.json(data)
except Exception as e:
    st.error("Could not reach API /v1/health")
    st.code(str(e))
