import os
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Ledger-Safe Ops Console", layout="wide")
st.title("Ledger-Safe Ops Console (MVP)")

st.caption("Health + Exceptions Queue (quarantine workflow starting point).")

with st.sidebar:
    st.header("Filters")
    tenant_filter = st.text_input("Tenant filter (optional)", value="")
    status_filter = st.selectbox("Exception status", ["open", "resolved"], index=0)
    limit = st.slider("Limit", min_value=5, max_value=200, value=50, step=5)
    if st.button("Refresh"):
        st.rerun()

# --- Health ---
st.subheader("Health")
try:
    health = requests.get(f"{API_BASE_URL}/v1/health", timeout=3).json()
    if health.get("status") == "ok":
        st.success(f"API: {health.get('status')} | DB: {health.get('db')}")
    else:
        st.warning("Health is degraded")
    st.json(health)
except Exception as e:
    st.error("Could not reach API /v1/health")
    st.code(str(e))
    st.stop()

# --- Exceptions ---
st.subheader("Exceptions Queue")
params = {"status": status_filter, "limit": limit}
if tenant_filter.strip():
    params["tenant_id"] = tenant_filter.strip()

try:
    ex = requests.get(f"{API_BASE_URL}/v1/exceptions", params=params, timeout=5).json()
    items = ex.get("items", [])
    st.write(f"Showing **{len(items)}** exceptions (status = `{status_filter}`)")
    if items:
        st.dataframe(items, use_container_width=True)
    else:
        st.info("No exceptions found for the selected filters.")
except Exception as e:
    st.error("Could not fetch exceptions")
    st.code(str(e))
