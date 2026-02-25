import os
import json
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Ledger-Safe Ops Console", layout="wide")
st.title("Ledger-Safe Ops Console (MVP)")
st.caption("Health + Exceptions Queue + Resolve/Replay (Step 3).")

with st.sidebar:
    st.header("Filters")
    tenant_filter = st.text_input("Tenant filter (optional)", value="")
    status_filter = st.selectbox("Exception status", ["open", "resolved"], index=0)
    limit = st.slider("Limit", min_value=5, max_value=200, value=50, step=5)

    st.divider()
    actor = st.text_input("Actor (audit)", value="operator:bill")

    if st.button("Refresh"):
        st.rerun()

# ---- Health ----
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

# ---- Exceptions list ----
st.subheader("Exceptions Queue")
params = {"status": status_filter, "limit": limit}
if tenant_filter.strip():
    params["tenant_id"] = tenant_filter.strip()

ex = requests.get(f"{API_BASE_URL}/v1/exceptions", params=params, timeout=5).json()
items = ex.get("items", [])

st.write(f"Showing **{len(items)}** exceptions (status = `{status_filter}`)")
if items:
    st.dataframe(items, use_container_width=True)
else:
    st.info("No exceptions found for the selected filters.")
    st.stop()

# ---- Select an exception to view + resolve ----
options = []
id_by_label = {}
for it in items:
    label = f"{it['exception_id']} | {it['reason_code']} | {it['tenant_id']} | raw {it['raw_id']}"
    options.append(label)
    id_by_label[label] = it["exception_id"]

selected_label = st.selectbox("Select an exception to view details", options=options)
selected_id = id_by_label[selected_label]

detail = requests.get(f"{API_BASE_URL}/v1/exceptions/{selected_id}", timeout=5).json()
ex_row = detail.get("exception", {})
ep_row = detail.get("events_processed", {}) or {}
raw_event = detail.get("raw_event", {}) or {}
first_raw = detail.get("first_raw_event", {}) or {}
last_raw = detail.get("last_raw_event", {}) or {}

st.subheader("Exception Detail")

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Reason code", ex_row.get("reason_code", ""))
    st.write("Status:", ex_row.get("status", ""))
with c2:
    st.write("Tenant:", ex_row.get("tenant_id"))
    st.write("Idempotency key:", ex_row.get("idempotency_key"))
with c3:
    st.write("Created:", ex_row.get("created_at"))
    st.write("Raw id:", ex_row.get("raw_id"))

st.caption("Raw event that triggered the exception")
st.json(raw_event.get("payload_json", {}))

# For idempotency conflicts, show first vs last side-by-side (huge demo value)
if ex_row.get("reason_code") == "IDEMPOTENCY_CONFLICT" and first_raw and last_raw:
    st.subheader("Idempotency conflict comparison (first vs last)")
    left, right = st.columns(2)
    with left:
        st.caption(f"FIRST raw_id = {first_raw.get('raw_id')}")
        st.json(first_raw.get("payload_json", {}))
    with right:
        st.caption(f"LAST raw_id = {last_raw.get('raw_id')}")
        st.json(last_raw.get("payload_json", {}))

# ---- Resolution controls ----
st.subheader("Resolve / Replay")

notes = st.text_area("Resolution notes (required for real ops)", value="", height=80)

default_patch = "{}"
patch_text = st.text_area("Override patch (JSON merge patch, optional)", value=default_patch, height=120)

override_patch = {}
if patch_text.strip():
    try:
        override_patch = json.loads(patch_text)
        if not isinstance(override_patch, dict):
            st.error("Override patch must be a JSON object (dictionary).")
            override_patch = {}
    except Exception:
        st.error("Override patch is not valid JSON.")
        override_patch = {}

canonical_raw_id = None
if ex_row.get("reason_code") == "IDEMPOTENCY_CONFLICT" and first_raw and last_raw:
    choice = st.radio(
        "Choose canonical raw event for replay",
        options=[
            f"Use FIRST (raw_id={first_raw.get('raw_id')})",
            f"Use LAST (raw_id={last_raw.get('raw_id')})",
        ],
        index=1,  # default to LAST
    )
    canonical_raw_id = int(first_raw.get("raw_id")) if "FIRST" in choice else int(last_raw.get("raw_id"))

b1, b2 = st.columns(2)

with b1:
    if st.button("Resolve + Replay", type="primary"):
        body = {
            "action": "override_and_replay",
            "actor": actor.strip() or "operator:unknown",
            "resolution_notes": notes,
            "override_patch": override_patch,
            "canonical_raw_id": canonical_raw_id,
        }
        resp = requests.post(f"{API_BASE_URL}/v1/exceptions/{selected_id}/resolve", json=body, timeout=10)
        if resp.status_code >= 400:
            st.error(f"Resolve failed ({resp.status_code})")
            st.json(resp.json())
        else:
            st.success("Resolved + replayed successfully.")
            st.json(resp.json())
            st.rerun()

with b2:
    if st.button("Resolve (ignore, no replay)"):
        body = {
            "action": "mark_resolved_no_replay",
            "actor": actor.strip() or "operator:unknown",
            "resolution_notes": notes,
            "override_patch": {},
        }
        resp = requests.post(f"{API_BASE_URL}/v1/exceptions/{selected_id}/resolve", json=body, timeout=10)
        if resp.status_code >= 400:
            st.error(f"Resolve failed ({resp.status_code})")
            st.json(resp.json())
        else:
            st.success("Resolved (ignored, no replay).")
            st.json(resp.json())
            st.rerun()
