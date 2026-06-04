import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
from pathlib import Path
from PIL import Image
import uuid
import base64
import json
import secrets
import hashlib
import urllib.request
from urllib.parse import urlparse, urlunparse

# Supabase initialization
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
        res = supabase.table("users").select("username").eq("username", "admin").execute()
        if not getattr(res, "data", None):
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

# 1. PATH SETUP
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FOLDER = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_FOLDER, exist_ok=True)
DB_PATH = os.path.join(DATA_FOLDER, "sunsys_erp.db")
ATTACHMENT_PATH = os.path.join(DATA_FOLDER, "attachments")
os.makedirs(ATTACHMENT_PATH, exist_ok=True)

# Supabase client is now initialized inline


# 2. UPDATED GET_DB
def get_db():
    return sqlite3.connect(DB_PATH)


# 3. DATABASE INITIALIZATION FUNCTION
def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 username TEXT PRIMARY KEY,
                 password TEXT,
                 full_name TEXT,
                 dept TEXT,
                 designation TEXT,
                 phone TEXT,
                 role TEXT)''')

    c.execute("""INSERT OR IGNORE INTO users (username, password, full_name, dept, designation, phone, role)
                 VALUES (?,?,?,?,?,?,?)""", ("admin", hash_password("admin2026"), "HR Manager", "HR & Admin", "HR Head", "", "Admin"))

    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 description TEXT,
                 assigned_to TEXT,
                 dept TEXT,
                 status TEXT,
                 priority TEXT,
                 frequency TEXT,
                 due_date TEXT,
                 due_time TEXT,
                 admin_file TEXT,
                 emp_remark TEXT,
                 emp_screenshot TEXT,
                 timestamp TEXT,
                 admin_files_json TEXT DEFAULT '[]',
                 emp_files_json TEXT DEFAULT '[]')''')

    conn.commit()
    conn.close()


# Ensure attachments folder exists (do not delete files on restart)
os.makedirs(ATTACHMENT_PATH, exist_ok=True)


# ====================== DATABASE SETUP ======================
def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN due_time TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN admin_files_json TEXT DEFAULT '[]'")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN emp_files_json TEXT DEFAULT '[]'")
    except Exception:
        pass
    conn.commit()
    conn.close()


# ====================== SECURITY HELPERS ======================
def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2$sha256${salt.hex()}${digest.hex()}"


def verify_password(password, stored_password):
    if not stored_password:
        return False
    if isinstance(stored_password, str) and stored_password.startswith("pbkdf2$"):
        try:
            _, algo, salt_hex, digest_hex = stored_password.split("$")
            salt = bytes.fromhex(salt_hex)
            expected = hashlib.pbkdf2_hmac(algo.replace("sha256", "sha256"), password.encode("utf-8"), salt, 200_000).hex()
            return secrets.compare_digest(expected, digest_hex)
        except Exception:
            return False
    return stored_password == password


def supabase_response_to_df(response):
    data = getattr(response, "data", None)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if data is None:
        return pd.DataFrame()
    if isinstance(data, dict):
        return pd.DataFrame([data])
    if isinstance(data, list):
        return pd.DataFrame(data)
    return pd.DataFrame([data])


def get_users_df():
    if SUPABASE_ENABLED:
        return supabase_response_to_df(supabase.table("users").select("*").execute())
    return pd.read_sql("SELECT * FROM users", get_db())


def get_tasks_df():
    if SUPABASE_ENABLED:
        return supabase_response_to_df(supabase.table("tasks").select("*").execute())
    return pd.read_sql("SELECT * FROM tasks", get_db())


def get_user_record(username):
    users_df = get_users_df()
    if users_df.empty:
        return None
    match = users_df[users_df["username"] == username]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def authenticate_user(username, password):
    user = get_user_record(username)
    if not user:
        return None
    if verify_password(password, user.get("password")):
        return user
    return None


def ensure_supabase_seed_admin():
    if not SUPABASE_ENABLED:
        return
    users_df = get_users_df()
    if not users_df.empty and (users_df["username"] == "admin").any():
        return

    supabase.table("users").insert({
        "username": "admin",
        "password": hash_password("admin2026"),
        "full_name": "HR Manager",
        "dept": "HR & Admin",
        "designation": "HR Head",
        "phone": "",
        "role": "Admin"
    }).execute()


def ensure_supabase_tables():
    if not SUPABASE_ENABLED:
        return
    ensure_supabase_seed_admin()


def insert_user_record(full_name, username, password, dept, designation, phone):
    if SUPABASE_ENABLED:
        supabase.table("users").insert({
            "username": username,
            "password": hash_password(password),
            "full_name": full_name,
            "dept": dept,
            "designation": designation,
            "phone": phone,
            "role": "Employee"
        }).execute()
        return

    conn = get_db()
    conn.execute("""INSERT INTO users
                     (username, password, full_name, dept, designation, phone, role)
                     VALUES (?,?,?,?,?,?,?)""", (username, hash_password(password), full_name, dept, designation, phone, "Employee"))
    conn.commit()
    conn.close()


def delete_user_record(username):
    if SUPABASE_ENABLED:
        supabase.table("users").delete().eq("username", username).execute()
        supabase.table("tasks").delete().eq("assigned_to", username).execute()
        return

    conn = get_db()
    conn.execute("DELETE FROM users WHERE username=?", (username,))
    conn.execute("DELETE FROM tasks WHERE assigned_to=?", (username,))
    conn.commit()
    conn.close()


def update_user_password_record(username, new_password):
    if SUPABASE_ENABLED:
        supabase.table("users").update({"password": hash_password(new_password)}).eq("username", username).execute()
        return

    conn = get_db()
    conn.execute("UPDATE users SET password=? WHERE username=?", (hash_password(new_password), username))
    conn.commit()
    conn.close()


def insert_task_record(description, assigned_to, dept, priority, frequency, due_date, due_time, admin_files_json):
    first_admin_file = json.loads(admin_files_json)[0] if admin_files_json and json.loads(admin_files_json) else ""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if SUPABASE_ENABLED:
        supabase.table("tasks").insert({
            "description": description,
            "assigned_to": assigned_to,
            "dept": dept,
            "status": "Pending",
            "priority": priority,
            "frequency": frequency,
            "due_date": due_date,
            "due_time": due_time,
            "admin_file": first_admin_file,
            "admin_files_json": admin_files_json,
            "emp_remark": "",
            "emp_screenshot": "",
            "timestamp": timestamp,
            "emp_files_json": "[]"
        }).execute()
        return

    conn = get_db()
    conn.execute("""INSERT INTO tasks
                     (description, assigned_to, dept, status, priority, frequency, due_date, due_time, admin_file, admin_files_json, timestamp, emp_remark, emp_screenshot, emp_files_json)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (description, assigned_to, dept, "Pending", priority, frequency, due_date, due_time, first_admin_file, admin_files_json, timestamp, "", "", "[]"))
    conn.commit()
    conn.close()


def update_task_record(task_id, description, status, priority, due_date):
    if SUPABASE_ENABLED:
        supabase.table("tasks").update({
            "description": description,
            "status": status,
            "priority": priority,
            "due_date": due_date
        }).eq("id", task_id).execute()
        return

    conn = get_db()
    conn.execute("""UPDATE tasks SET description=?, status=?, priority=?, due_date=? WHERE id=?""",
                 (description, status, priority, due_date, task_id))
    conn.commit()
    conn.close()


def delete_task_record(task_id):
    if SUPABASE_ENABLED:
        supabase.table("tasks").delete().eq("id", task_id).execute()
        return

    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


def update_task_progress(task_id, status, remark, first_emp_file, emp_files_json):
    if SUPABASE_ENABLED:
        supabase.table("tasks").update({
            "status": status,
            "emp_remark": remark,
            "emp_screenshot": first_emp_file,
            "emp_files_json": emp_files_json
        }).eq("id", task_id).execute()
        return

    conn = get_db()
    conn.execute("UPDATE tasks SET status=?, emp_remark=?, emp_screenshot=?, emp_files_json=? WHERE id=?",
                 (status, remark, first_emp_file, emp_files_json, task_id))
    conn.commit()
    conn.close()


def get_task_row(task_id):
    tasks_df = get_tasks_df()
    row = tasks_df[tasks_df["id"] == task_id]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def get_employee_rows():
    users_df = get_users_df()
    return users_df[users_df["role"] == "Employee"].copy()


def get_tasks_for_user(username):
    tasks_df = get_tasks_df()
    return tasks_df[tasks_df["assigned_to"] == username].copy()


def is_storage_ref(value):
    return isinstance(value, str) and value.startswith("storage://")


def parse_storage_ref(value):
    if not is_storage_ref(value):
        return None, None
    raw = value[len("storage://"):]
    bucket, path = raw.split("/", 1)
    return bucket, path


def make_storage_ref(bucket_name, path):
    return f"storage://{bucket_name}/{path}"


def ensure_supabase_bucket():
    if not SUPABASE_ENABLED:
        raise RuntimeError("Supabase is not enabled")

    bucket_name = SUPABASE_BUCKET_NAME
    try:
        supabase.storage.get_bucket(bucket_name)
        return bucket_name
    except Exception:
        create_response = supabase.storage.create_bucket(bucket_name, {"public": False})
        if isinstance(create_response, dict) and create_response.get("error"):
            raise RuntimeError(create_response["error"])
        return bucket_name


def get_supabase_signed_url(file_ref):
    if not is_storage_ref(file_ref):
        return file_ref
    bucket_name, path = parse_storage_ref(file_ref)
    response = supabase.storage.from_(bucket_name).create_signed_url(path, 3600)
    if isinstance(response, dict):
        if response.get("error"):
            raise RuntimeError(response["error"])
        return response.get("signedURL") or response.get("data", {}).get("signedURL")
    if hasattr(response, "data") and response.data:
        return response.data.get("signedURL")
    return None


def download_storage_bytes(file_ref):
    signed_url = get_supabase_signed_url(file_ref)
    with urllib.request.urlopen(signed_url) as response:
        return response.read()


def get_attachment_name(file_ref):
    if is_storage_ref(file_ref):
        _, path = parse_storage_ref(file_ref)
        return os.path.basename(path)
    if isinstance(file_ref, str):
        return os.path.basename(file_ref)
    return "attachment"


def render_attachment(file_ref, key_prefix, allow_link=False):
    if is_storage_ref(file_ref):
        name = get_attachment_name(file_ref)
        signed_url = get_supabase_signed_url(file_ref)
        if allow_link and signed_url:
            st.markdown(f"[📄 {name}]({signed_url})")
        else:
            st.write(f"📄 {name}")
        try:
            st.download_button(
                label="⬇️ Download",
                data=download_storage_bytes(file_ref),
                file_name=name,
                key=f"{key_prefix}_{name}"
            )
        except Exception:
            st.write("Unable to download")
        return

    if isinstance(file_ref, str) and file_ref.startswith("http"):
        st.markdown(f"[📄 {get_attachment_name(file_ref)}]({file_ref})")
        return

    if isinstance(file_ref, str) and os.path.exists(file_ref):
        name = get_attachment_name(file_ref)
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"📄 {name}")
        with col2:
            try:
                with open(file_ref, "rb") as f:
                    st.download_button(
                        label="⬇️ Download",
                        data=f.read(),
                        file_name=name,
                        key=f"{key_prefix}_{name}"
                    )
            except Exception:
                st.write("Unable to download")
        return

    if file_ref:
        st.write(f"📄 {get_attachment_name(file_ref)}")


def save_file_to_supabase(uploaded_file, prefix):
    if not SUPABASE_ENABLED:
        raise RuntimeError("Supabase is not enabled. Configure SUPABASE_URL and SUPABASE_KEY.")

    bucket_name = ensure_supabase_bucket()
    file_name = Path(uploaded_file.name).name
    file_ext = Path(file_name).suffix
    unique_name = f"{prefix}_{secrets.token_hex(10)}{file_ext}"
    file_bytes = uploaded_file.getvalue()
    upload_response = supabase.storage.from_(bucket_name).upload(
        unique_name,
        file_bytes,
        {"content-type": getattr(uploaded_file, "type", "application/octet-stream")}
    )
    if isinstance(upload_response, dict) and upload_response.get("error"):
        raise RuntimeError(upload_response["error"])

    return make_storage_ref(bucket_name, unique_name)


def save_file_to_local(uploaded_file, prefix):
    file_name = Path(uploaded_file.name).name
    file_ext = Path(file_name).suffix
    unique_name = f"{prefix}_{uuid.uuid4().hex[:8]}{file_ext}"
    local_path = os.path.join(ATTACHMENT_PATH, unique_name)
    with open(local_path, "wb") as f:
        f.write(uploaded_file.getvalue())
    return local_path


def save_uploaded_file(uploaded_file, prefix):
    if SUPABASE_ENABLED:
        try:
            return save_file_to_supabase(uploaded_file, prefix)
        except Exception as e:
            raise RuntimeError(f"Supabase upload failed: {e}")
    return save_file_to_local(uploaded_file, prefix)


# 4. CRITICAL: TRIGGER INITIALIZATION with resilience
if SUPABASE_ENABLED:
    # Try to connect to Supabase with 3 retries before falling back to SQLite
    max_retries = 3
    retry_delay = 1
    connected = False
    
    for attempt in range(max_retries):
        try:
            ensure_supabase_tables()
            connected = True
            st.success("✅ Connected to Supabase")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                retry_delay *= 2  # exponential backoff
                import time
                time.sleep(retry_delay)
            else:
                st.warning(f"⚠️ Supabase unavailable after {max_retries} attempts; falling back to SQLite. Data is safe.")
                SUPABASE_ENABLED = False
                supabase = None
    
    if not connected:
        init_db()
        migrate_db()
else:
    init_db()
    migrate_db()

# ====================== HELPER FUNCTION TO DISPLAY PDF (New Feature) ======================
def display_pdf(pdf_path):
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            base64_pdf = base64.b64encode(f.read()).decode('utf-8')
        pdf_display = f'''
            <iframe src="data:application/pdf;base64,{base64_pdf}" 
                    width="100%" height="600" 
                    type="application/pdf">
            </iframe>
        '''
        st.markdown(pdf_display, unsafe_allow_html=True)
    else:
        st.info("No PDF attached for this task.")

# ====================== ATTRACTIVE UI/UX STYLING ======================
st.set_page_config(page_title="SunSys ERP", page_icon="☀️", layout="wide")

if not SUPABASE_ENABLED:
    st.info("Supabase not enabled — running in local SQLite mode. To enable Supabase, set `SUPABASE_URL` and `SUPABASE_KEY` in Streamlit secrets and install the `supabase` package.")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; font-size: 18px !important; }
    h1 { font-size: 48px !important; font-weight: 700; }
    h2 { font-size: 36px !important; }
    h3 { font-size: 28px !important; }
    
    .main-header { 
        background: linear-gradient(135deg, #1C4694 0%, #E47F15 100%); 
        padding: 30px; border-radius: 20px; color: white; 
        margin-bottom: 25px; box-shadow: 0 8px 25px rgba(0,0,0,0.2);
    }
    
    .live-time { 
        font-size: 22px; font-weight: 700; color: #E47F15; 
        background: white; padding: 15px; border-radius: 15px; 
        box-shadow: 0 4px 15px rgba(0,0,0,0.1); text-align: center;
    }
    
    .card { 
        background: white; padding: 25px; border-radius: 18px; 
        box-shadow: 0 6px 20px rgba(0,0,0,0.1); margin-bottom: 20px;
    }
    
    .stButton>button { 
        height: 55px; font-weight: 700; border-radius: 14px; 
        background: linear-gradient(90deg, #1C4694, #E47F15); color: white;
        font-size: 18px;
    }
    
    .stDataFrame { font-size: 18px !important; }
    </style>
""", unsafe_allow_html=True)

# ====================== HEADER WITH LIVE TIME & DATE ======================
import streamlit.components.v1 as components

col1, col2, col3 = st.columns([1.2, 3.5, 2.2])

with col1:
    if os.path.exists("sunsys logo.jpeg"):
        st.image("sunsys logo.jpeg", width=200)
    else:
        st.title("☀️ SunSys")

with col2:
    st.markdown('<div class="main-header"><h1>SunSys ERP Portal</h1></div>', unsafe_allow_html=True)

with col3:
    components.html(
        """
        <div style="
            background: rgba(28, 70, 148, 0.05); 
            padding: 15px; 
            border-radius: 12px; 
            border-left: 5px solid #E47F15;
            font-family: 'Segoe UI', sans-serif;
            text-align: center;
        ">
            <div id="date" style="font-size: 14px; color: #666; font-weight: 600;"></div>
            <div id="clock" style="font-size: 28px; color: #1C4694; font-weight: 800; margin-top: 5px;"></div>
        </div>

        <script>
            function updateClock() {
                const now = new Date();
                const dateOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
                document.getElementById('date').innerText = now.toLocaleDateString('en-US', dateOptions);
                const timeOptions = { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true };
                document.getElementById('clock').innerText = now.toLocaleTimeString('en-US', timeOptions);
            }
            setInterval(updateClock, 1000);
            updateClock();
        </script>
        """,
        height=110,
    )

# ====================== AUTHENTICATION ======================
if "auth" not in st.session_state:
    st.session_state.update({"auth": False, "role": None, "user": None, "dept": None})


def login_page():
    st.markdown("<h2 style='text-align:center; color:#1C4694;'>🔐 Department Center Login</h2>", unsafe_allow_html=True)
    with st.container():
        role = st.radio("Select Access Type", ["Employee", "HR Admin"], horizontal=True)

        if role == "HR Admin":
            username = st.text_input("Admin Username")
            password = st.text_input("Password", type="password")
            if st.button("Enter HR Command Center", use_container_width=True):
                user = authenticate_user(username.strip(), password.strip())
                if user and user.get("role") == "Admin":
                    st.session_state.update({"auth": True, "role": "Admin", "user": username})
                    st.rerun()
                else:
                    st.error("❌ Invalid Admin Credentials")

        else:
            username = st.text_input("Employee Username")
            password = st.text_input("Password", type="password")
            selected_dept = st.selectbox(
                "Choose Your Department Center",
                ["Solar Installation", "Technical Support", "Sales & Marketing", "HR & Admin", "Accounts"]
            )

            if st.button("Enter My Department Center", use_container_width=True):
                user = authenticate_user(username.strip(), password.strip())
                if user and user.get("role") == "Employee":
                    stored_dept = (user.get("dept") or "").strip()
                    selected_dept_clean = selected_dept.strip()
                    if stored_dept == selected_dept_clean:
                        st.session_state.update({"auth": True, "role": "Employee", "user": username, "dept": selected_dept})
                        st.rerun()
                    else:
                        st.error(f"❌ Department mismatch. Your registered department is '{stored_dept}' but you selected '{selected_dept_clean}'")
                else:
                    st.error("❌ Invalid username or password")


if not st.session_state.auth:
    login_page()
    st.stop()

if st.sidebar.button("🚪 Logout"):
    st.session_state.auth = False
    st.rerun()

# ====================== HELPER FUNCTION: GET RECENTLY UPDATED TASKS ======================
def get_recent_task_updates(hours=24):
    """Fetch tasks updated in the last N hours with employee details"""
    cutoff_time = datetime.now() - timedelta(hours=hours)
    tasks_df = get_tasks_df()
    users_df = get_users_df()

    if tasks_df.empty:
        return pd.DataFrame()

    recent_tasks = tasks_df.merge(
        users_df[["username", "full_name"]],
        left_on="assigned_to",
        right_on="username",
        how="left"
    )
    recent_tasks = recent_tasks[
        (recent_tasks["emp_remark"].notna() & (recent_tasks["emp_remark"] != "")) |
        recent_tasks["status"].isin(["In Progress", "Need Help", "Work Completed"])
    ].copy()

    recent_tasks["assigned_date"] = pd.to_datetime(recent_tasks["timestamp"], errors="coerce")
    recent_tasks = recent_tasks[recent_tasks["assigned_date"] >= cutoff_time].copy()
    recent_tasks["updated_time"] = recent_tasks["assigned_date"]
    recent_tasks = recent_tasks.sort_values("id", ascending=False).head(20)

    return recent_tasks[[
        "id",
        "description",
        "assigned_to",
        "full_name",
        "status",
        "priority",
        "emp_remark",
        "assigned_date",
        "updated_time"
    ]]


def get_status_badge_color(status):
    """Return color based on task status"""
    if status == "Work Completed":
        return "🟢 Completed"
    elif status == "In Progress":
        return "🟡 In Progress"
    elif status == "Need Help":
        return "🔴 Need Help"
    else:
        return "⚪ Pending"

# ====================== ADMIN PANEL ======================
if st.session_state.role == "Admin":
    st.header("📊 HR Command Center")
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📋 Assign Task", "👥 Team Overview", "✏️ Edit/Delete", "📊 Dashboard", "➕ Add/Remove Employee", "🔔 Live Updates"])
    
    with tab1:
        st.subheader("Assign New Task")
        # Department selector outside form for dynamic updates
        dept_col, _ = st.columns([1, 3])
        with dept_col:
            selected_dept = st.selectbox("📍 Select Department", ["Solar Installation", "Technical Support", "Sales & Marketing", "HR & Admin", "Accounts"], key="admin_dept_select")
        
        # Fetch employees based on selected department
        emps_df = get_users_df()
        emps_df = emps_df[(emps_df["role"] == "Employee") & (emps_df["dept"] == selected_dept)].copy()
        # Build a human-friendly list for selectbox: "Full Name (username)"
        employee_list = [f"{row['full_name']} ({row['username']})" for _, row in emps_df.iterrows()] if not emps_df.empty else []
        
        if emps_df.empty:
            st.warning(f"📍 No employees found in **{selected_dept}**.")
        else:
            st.success(f"📍 Found **{len(emps_df)}** employee(s) in **{selected_dept}**")
            st.write(", ".join([row['full_name'] for _, row in emps_df.iterrows()]))
        
        with st.form("assign_task", clear_on_submit=True):
            desc = st.text_area("Task Description", height=140)
            c1, c2, c3, c4 = st.columns(4)
            
            # Department (hidden, using selected_dept from outside)
            dept = selected_dept
            
            if emps_df.empty:
                c2.write("No employees available for assignment.")
                assigned_to = None
            else:
                selected_emp = c2.selectbox("👤 Assign To", employee_list, key="form_emp_select")
                assigned_to = selected_emp.split("(")[-1].strip(")") if "(" in selected_emp else None
            
            priority = c3.selectbox("Priority", ["High", "Medium", "Low"])
            frequency = c4.selectbox("Frequency", ["Daily", "Weekly", "Fortnightly", "One-Time"])
            
            # --- NEW TIME & FILE OPTIONS ---
            col_date, col_time = st.columns(2)
            due_date = col_date.date_input("Due Date", datetime.now().date() + timedelta(days=7))
            due_time = col_time.time_input("Due Time (Deadline)", value=datetime.now().time())
            
            admin_file = st.file_uploader("📎 Attach Resources (PDF, Excel, Video, Image) - Upload Multiple Files", 
                                        type=["pdf", "xlsx", "xls", "mp4", "jpg", "png", "jpeg", "doc", "docx", "txt"],
                                        accept_multiple_files=True)
            
            if st.form_submit_button("🚀 Assign Task"):
                if not desc:
                    st.error("❌ Please enter a task description.")
                elif not assigned_to:
                    st.error("❌ Please select an employee from the selected department.")
                else:
                    try:
                        admin_files_json = "[]"
                        if admin_file:
                            file_paths = []
                            for uploaded_file in admin_file:
                                file_path = save_uploaded_file(uploaded_file, f"admin_{uuid.uuid4().hex[:8]}")
                                file_paths.append(file_path)
                            admin_files_json = json.dumps(file_paths)

                        insert_task_record(
                            desc,
                            assigned_to,
                            dept,
                            priority,
                            frequency,
                            due_date.strftime("%Y-%m-%d"),
                            due_time.strftime("%H:%M"),
                            admin_files_json
                        )
                        st.success("✅ Task Assigned Successfully!")
                        st.info(f"📎 {len(json.loads(admin_files_json))} file(s) attached")
                        st.balloons()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error assigning task: {str(e)}")

    with tab2:
        st.subheader("👥 Team Member Directory")
        employees = get_employee_rows()

        if employees.empty:
            st.info("No employees added yet.")
        else:
            selected_member = st.selectbox("Select Team Member to View Details", employees['full_name'].tolist())
            member = employees[employees['full_name'] == selected_member].iloc[0]
            
            st.markdown(f"""
                <div class="card">
                    <h3>{member['full_name']}</h3>
                    <p><strong>Department:</strong> {member['dept']}<br>
                       <strong>Designation:</strong> {member['designation']}<br>
                       <strong>Phone:</strong> {member['phone']}</p>
                </div>
            """, unsafe_allow_html=True)
            
            if member['phone']:
                wa_link = f"https://wa.me/{member['phone']}?text=Hello%20{member['full_name']}%2C%20regarding%20your%20task..."
                st.markdown(f"[💬 Message on WhatsApp]({wa_link})")
            
            st.divider()
            st.subheader(f"Tasks & Proofs for {member['full_name']}")

            tasks_df = get_tasks_for_user(member['username'])
            tasks_df = tasks_df[["id", "description", "status", "priority", "frequency", "due_date", "emp_remark", "emp_screenshot", "emp_files_json"]].copy()

            if tasks_df.empty:
                st.info("No tasks assigned yet.")
            else:
                for _, row in tasks_df.iterrows():
                    with st.container():
                        # Status indicator with badge
                        col_title, col_badge = st.columns([3, 1])
                        with col_title:
                            st.write(f"**Task:** {row['description']}")
                        with col_badge:
                            st.markdown(f"### {get_status_badge_color(row['status'])}")

                        col_main, col_priority = st.columns([3, 1])
                        with col_main:
                            st.caption(f"Frequency: **{row['frequency']}** | Due: **{row.get('due_date','N/A')}**")
                        with col_priority:
                            if row['priority'] == 'High':
                                st.error("🔴 HIGH PRIORITY")
                            elif row['priority'] == 'Medium':
                                st.warning("🟡 MEDIUM PRIORITY")
                            else:
                                st.info("🟢 LOW PRIORITY")

                        if row.get('emp_remark'):
                            st.success(f"💬 **Employee Note:** _{row['emp_remark']}_")

                        # Display multiple uploaded files
                        try:
                            emp_files_json = row.get('emp_files_json', '[]')
                            emp_files = json.loads(emp_files_json) if emp_files_json else []

                            if emp_files:
                                st.subheader("📎 Uploaded Files")
                                for file_path in emp_files:
                                    render_attachment(file_path, f"download_{row['id']}", allow_link=True)
                            else:
                                st.info("No files uploaded yet.")
                        except Exception as e:
                            st.warning(f"Error loading files: {str(e)}")

                        st.divider()

    with tab3:
        st.subheader("Edit / Delete Task")
        all_tasks = get_tasks_df()
        all_tasks = all_tasks[["id", "description"]].copy()
        all_tasks = all_tasks.sort_values("id", ascending=False)

        if all_tasks.empty:
            st.info("No tasks available.")
        else:
            task_options = [f"ID {row['id']}: {row['description'][:50]}..." for _, row in all_tasks.iterrows()]
            selected_task_option = st.selectbox("Select Task", task_options)
            task_id = int(selected_task_option.split(":")[0].replace("ID ", ""))

            task_data = get_task_row(task_id)
            if task_data is None:
                st.error("Task not found.")
            else:
                with st.form("edit_form"):
                    new_desc = st.text_area("Task Description", value=task_data['description'], height=100)
                    new_status = st.selectbox("Status", ["Pending", "In Progress", "Need Help", "Work Completed"],
                                            index=["Pending", "In Progress", "Need Help", "Work Completed"].index(task_data['status']))
                    new_priority = st.selectbox("Priority", ["High", "Medium", "Low"],
                                              index=["High", "Medium", "Low"].index(task_data['priority']))
                    new_due = st.date_input("Due Date", value=datetime.strptime(task_data['due_date'], "%Y-%m-%d").date() if task_data['due_date'] else datetime.now().date())

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("💾 Update Task"):
                            update_task_record(task_id, new_desc, new_status, new_priority, new_due.strftime("%Y-%m-%d"))
                            st.success("Task updated successfully!")
                            st.rerun()

                    with col2:
                        confirm = st.checkbox("⚠️ I confirm I want to delete this task")
                        if st.form_submit_button("🗑️ Delete Task", type="secondary", disabled=not confirm):
                            delete_task_record(task_id)
                            st.success("Task deleted successfully!")
                            st.rerun()

    with tab4:
        st.subheader("📊 Overall Dashboard & Task Analytics")
        col1, col2, col3, col4 = st.columns(4)

        tasks_df = get_tasks_df()
        total_tasks = len(tasks_df)
        completed = int((tasks_df["status"] == "Work Completed").sum())
        pending = int((tasks_df["status"] != "Work Completed").sum())
        overdue = int(((tasks_df["due_date"] < datetime.now().date().strftime("%Y-%m-%d")) & (tasks_df["status"] != "Work Completed")).sum())

        with col1:
            st.metric("Total Tasks", total_tasks)
        with col2:
            st.metric("Completed", completed, delta=f"{completed} done")
        with col3:
            st.metric("Pending", pending)
        with col4:
            st.metric("Overdue", overdue, delta=f"{overdue} urgent", delta_color="inverse")
        
        st.divider()
        st.subheader("📋 All Tasks Overview")
        users_df = get_users_df()
        detailed_df = tasks_df.merge(
            users_df[["username", "full_name"]],
            left_on="assigned_to",
            right_on="username",
            how="left"
        ).copy()
        detailed_df = detailed_df.rename(columns={
            "description": "task_description",
            "full_name": "employee_name",
            "dept": "department",
            "timestamp": "assigned_date",
            "emp_remark": "employee_remark"
        })
        detailed_df = detailed_df[[
            "id",
            "task_description",
            "employee_name",
            "department",
            "status",
            "priority",
            "frequency",
            "due_date",
            "assigned_date",
            "employee_remark"
        ]].sort_values("id", ascending=False)

        if not detailed_df.empty:
            # Display tasks with visual indicators
            for idx, (_, row) in enumerate(detailed_df.iterrows()):
                with st.container():
                    col1, col2, col3 = st.columns([2, 1, 1])
                    
                    with col1:
                        st.markdown(f"**Task #{row['id']}:** {row['task_description'][:60]}...")
                        st.caption(f"👤 {row['employee_name']} | 🏢 {row['department']}")
                    
                    with col2:
                        st.markdown(f"### {get_status_badge_color(row['status'])}")
                    
                    with col3:
                        if row['priority'] == 'High':
                            st.error("🔴 HIGH")
                        elif row['priority'] == 'Medium':
                            st.warning("🟡 MEDIUM")
                        else:
                            st.info("🟢 LOW")
                    
                    col_info1, col_info2, col_info3 = st.columns(3)
                    with col_info1:
                        st.caption(f"📅 Due: {row['due_date']}")
                    with col_info2:
                        st.caption(f"🔄 Frequency: {row['frequency']}")
                    with col_info3:
                        st.caption(f"📌 Assigned: {row['assigned_date'][:10]}")
                    
                    if row['employee_remark']:
                        st.info(f"💬 **Employee Update:** {row['employee_remark']}")
        else:
            st.info("No tasks have been assigned yet.")
        
        st.divider()
        st.subheader("📍 Department-wise Task Summary")
        dept_summary = tasks_df.groupby("dept").agg(
            total_tasks=("id", "count"),
            completed=("status", lambda s: int((s == "Work Completed").sum())),
            pending=("status", lambda s: int((s != "Work Completed").sum())),
            overdue=("due_date", lambda s: int(((s < datetime.now().date().strftime("%Y-%m-%d")) & (tasks_df.loc[s.index, "status"] != "Work Completed")).sum()))
        ).reset_index()

        st.dataframe(dept_summary, use_container_width=True, hide_index=True)

    with tab5:
        col_add, col_rem = st.columns(2)
        
        with col_add:
            st.subheader("➕ Add New Employee")
            with st.form("add_new_employee", clear_on_submit=True):
                full_name = st.text_input("Full Name *")
                username = st.text_input("Username (Login ID) *")
                password = st.text_input("Password *", type="password")
                dept = st.selectbox("Department",
                                  ["Solar Installation", "Technical Support", "Sales & Marketing", "HR & Admin", "Accounts"])
                designation = st.text_input("Designation")
                phone = st.text_input("Phone Number")

                if st.form_submit_button("✅ Add Employee", type="primary"):
                    if full_name and username and password and dept:
                        try:
                            insert_user_record(full_name.strip(), username.strip(), password.strip(), dept.strip(), designation.strip(), phone.strip())
                            st.success(f"✅ Employee **{full_name}** added!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Username '{username}' already exists or error: {str(e)}")
                    else:
                        st.error("Please fill all required fields (*)")

        with col_rem:
            st.subheader("🗑️ Remove Employee")
            emp_list_df = get_employee_rows()[["username", "full_name", "dept"]].copy()

            if emp_list_df.empty:
                st.info("No employees found in database.")
            else:
                options = {f"{row['full_name']} ({row['username']}) - {row['dept']}": row['username']
                           for _, row in emp_list_df.iterrows()}

                selected_to_remove = st.selectbox("Select Employee to Remove", options.keys())
                target_user = options[selected_to_remove]

                confirm = st.checkbox(f"I confirm I want to delete {target_user}")

                if st.button("❌ Permanent Delete", type="secondary", use_container_width=True):
                    if confirm:
                        delete_user_record(target_user)
                        st.warning(f"Employee {target_user} and their tasks have been removed.")
                        st.rerun()
                    else:
                        st.error("Please check the confirmation box first.")

    with tab6:
        st.subheader("🔔 Live Task Update Notifications")
        st.info("📬 Real-time updates when employees submit task progress")
        
        # Refresh button
        col_refresh, col_filter = st.columns([1, 3])
        with col_refresh:
            if st.button("🔄 Refresh Now", use_container_width=True, type="primary"):
                st.rerun()
        
        with col_filter:
            show_hours = st.slider("Show updates from last (hours)", 1, 168, 24)
        
        st.divider()
        
        # Get recent updates
        recent_updates = get_recent_task_updates(show_hours)
        
        if recent_updates.empty:
            st.info("✨ No task updates in the selected time period.")
        else:
            # Summary cards
            col1, col2, col3, col4 = st.columns(4)
            
            completed_count = len(recent_updates[recent_updates['status'] == 'Work Completed'])
            in_progress_count = len(recent_updates[recent_updates['status'] == 'In Progress'])
            need_help_count = len(recent_updates[recent_updates['status'] == 'Need Help'])
            
            with col1:
                st.metric("🟢 Completed", completed_count)
            with col2:
                st.metric("🟡 In Progress", in_progress_count)
            with col3:
                st.metric("🔴 Need Help", need_help_count)
            with col4:
                st.metric("📊 Total Updates", len(recent_updates))
            
            st.divider()
            st.subheader("📋 Recent Activity")
            
            # Display updates with visual indicators
            for idx, (_, row) in enumerate(recent_updates.iterrows()):
                with st.container():
                    col_status, col_priority = st.columns([2, 1])

                    with col_status:
                        st.markdown(f"**{row['full_name']}** - {get_status_badge_color(row['status'])}")
                        st.caption(f"📌 Task ID: {row['id']} | Priority: {row['priority']}")
                        st.write(f"📝 {row['description'][:100]}..." if len(str(row['description'])) > 100 else f"📝 {row['description']}")

                    with col_priority:
                        if row['priority'] == 'High':
                            st.error("🔴 HIGH")
                        elif row['priority'] == 'Medium':
                            st.warning("🟡 MEDIUM")
                        else:
                            st.info("🟢 LOW")

                    if row['emp_remark']:
                        st.markdown(f"**Employee Note:** _{row['emp_remark']}_")

                    # Action buttons
                    col_view, col_contact = st.columns(2)
                    with col_view:
                        if st.button(f"👁️ View Full Details", key=f"view_{row['id']}", use_container_width=True):
                            st.session_state.expand_task = row['id']
                            st.rerun()
                    with col_contact:
                        if row['id'] and not pd.isna(row['id']):
                            st.info(f"✅ Last update received")

    st.divider()
    st.caption("© 2026 SunSys ERP Portal by Aditya kumar | All rights reserved.")

# ====================== EMPLOYEE PANEL ======================
elif st.session_state.role == "Employee":
    st.header(f"🚀 {st.session_state.dept} Center • Welcome, {st.session_state.user}")
    
    # Create tabs for Tasks and Security
    tab_tasks, tab_security = st.tabs(["📋 My Tasks", "🔐 Security & Password"])

    with tab_tasks:
        tasks = get_tasks_for_user(st.session_state.user)

        if tasks.empty:
            st.info("No tasks assigned to you yet.")
        else:
            for _, row in tasks.iterrows():
                with st.container():
                    st.subheader(f"Task: {row['description']}")
                    st.warning(f"⏰ **Deadline:** {row['due_date']} at {row.get('due_time', 'Not set')}")

                    try:
                        admin_files_json = row.get('admin_files_json', '[]')
                        admin_files = json.loads(admin_files_json) if admin_files_json else []

                        if admin_files:
                            st.subheader("📦 Resources from Admin")
                            for file_path in admin_files:
                                render_attachment(file_path, f"admin_task_{row['id']}", allow_link=True)
                    except Exception as e:
                        st.warning(f"Error loading resources: {str(e)}")

                    st.divider()

                    col_status, col_upload = st.columns(2)
                    with col_status:
                        new_status = st.selectbox("Update Status", ["Pending", "In Progress", "Work Completed"], key=f"s_{row['id']}")
                        remark = st.text_area("Notes", value=row.get('emp_remark', ''), key=f"r_{row['id']}")
                    with col_upload:
                        proof_file = st.file_uploader("📎 Upload Proof/Attachments - Multiple Files",
                                                     type=["pdf", "xlsx", "xls", "mp4", "jpg", "png", "jpeg", "doc", "docx", "txt"],
                                                     key=f"p_{row['id']}", accept_multiple_files=True)

                    if st.button("🚀 Submit Update", key=f"b_{row['id']}", type="primary"):
                        try:
                            emp_files_json = row.get('emp_files_json', '[]')
                            if emp_files_json == '[]' or not emp_files_json:
                                emp_files_json = '[]'

                            current_files = json.loads(emp_files_json) if emp_files_json else []

                            if proof_file:
                                for uploaded_file in proof_file:
                                    file_path = save_uploaded_file(uploaded_file, f"proof_{row['id']}_{uuid.uuid4().hex[:5]}")
                                    current_files.append(file_path)

                            final_files_json = json.dumps(current_files)
                            first_emp_file = current_files[0] if current_files else ""
                            update_task_progress(row['id'], new_status, remark, first_emp_file, final_files_json)

                            st.success("✅ Work updated successfully!")
                            st.info(f"✔️ Status: {new_status} | {len(current_files)} file(s) uploaded | Saved at {datetime.now().strftime('%H:%M:%S')}")
                            st.balloons()
                            import time
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error updating task: {str(e)}")

    with tab_security:
        st.subheader("Update Your Password")
        st.info("Keep your account secure by choosing a strong password.")

        with st.form("change_password_form"):
            current_pass = st.text_input("Current Password", type="password")
            new_pass = st.text_input("New Password", type="password")
            confirm_pass = st.text_input("Confirm New Password", type="password")

            if st.form_submit_button("Update Password"):
                user_record = get_user_record(st.session_state.user)

                if not current_pass or not new_pass:
                    st.error("Please fill all fields.")
                elif not verify_password(current_pass, user_record.get("password") if user_record else None):
                    st.error("❌ Current password is incorrect.")
                elif new_pass != confirm_pass:
                    st.error("❌ New passwords do not match.")
                elif len(new_pass) < 6:
                    st.warning("⚠️ New password should be at least 6 characters long.")
                else:
                    update_user_password_record(st.session_state.user, new_pass)
                    st.success("✅ Password updated successfully! Please login again next time.")

    st.divider()
    st.caption("© 2026 SunSys ERP Portal by Aditya kumar | All rights reserved.")
