import os
import streamlit as st
from urllib.parse import urlparse, urlunparse
import time

try:
    from supabase import create_client
    HAS_SUPABASE_PKG = True
except Exception:
    create_client = None
    HAS_SUPABASE_PKG = False

supabase = None
SUPABASE_ENABLED = False
SUPABASE_BUCKET_NAME = "attachments"

if HAS_SUPABASE_PKG:
    try:
        raw_supabase_url = (
            st.secrets.get("SUPABASE_URL", "") or
            os.getenv("SUPABASE_URL", "")
        ).rstrip("/")
        if raw_supabase_url:
            parsed = urlparse(raw_supabase_url)
            if parsed.path and parsed.path != "/":
                raw_supabase_url = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

            key = (
                st.secrets.get("SUPABASE_KEY", "") or
                os.getenv("SUPABASE_KEY", "")
            )
            if raw_supabase_url and key:
                supabase = create_client(raw_supabase_url, key)
                SUPABASE_ENABLED = True
                SUPABASE_BUCKET_NAME = str(
                    st.secrets.get("SUPABASE_BUCKET", "") or
                    os.getenv("SUPABASE_BUCKET", "attachments")
                ).strip() or "attachments"
            else:
                SUPABASE_ENABLED = False
    except Exception as e:
        st.warning(f"Supabase client initialization failed: {e}")


def ensure_supabase_tables():
    if not SUPABASE_ENABLED:
        return
    try:
        # ensure admin user exists
        res = supabase.table("users").select("username").eq("username", "admin").execute()
        if not getattr(res, 'data', None):
            supabase.table("users").insert({
                "username": "admin",
                "password": "",
                "full_name": "HR Manager",
                "dept": "HR & Admin",
                "designation": "HR Head",
                "phone": "",
                "role": "Admin"
            }).execute()
    except Exception:
        pass
