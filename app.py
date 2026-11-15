import streamlit as st
import requests
from collections import defaultdict

BASE_URL = "https://web.mashov.info/api"

# הגדרות עמוד וממשק מותאם למובייל
st.set_page_config(page_title="ממוצעי משוב", page_icon="📊", layout="centered")

# עיצוב RTL וכרטיסיות ב-CSS
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
def get_schools():
    resp = requests.get(f"{BASE_URL}/schools", timeout=15)
    resp.raise_for_status()
    return resp.json()

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

# --- ממשק משתמש ---
st.title("📊 מחשבון ממוצעים - משוב")

schools = get_schools()
school_search = st.text_input("חיפוש בית ספר", value="הכפר הירוק")
matching_schools = [s for s in schools if school_search in s.get("name", "")]

if not matching_schools:
    st.warning("לא נמצא מוסד תואם לחיפוש.")
    st.stop()

selected_school = st.selectbox(
    "בחר מוסד לימודים",
    options=matching_schools,
    format_func=lambda s: f"{s['name']} ({s['semel']})"
)

years = sorted(selected_school.get("years", [2027]), reverse=True)
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
                name, grades_data = fetch_grades(username, password, selected_school["semel"], year)
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
                    st.info("לא נמצאו ציונים מספריים לשנה זו.")
                else:
                    # חישוב ממוצע כללי
                    subject_final_avgs = []
                    subject_summaries = []

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

                    overall_avg = sum(subject_final_avgs) / len(subject_final_avgs)
                    
                    st.markdown("---")
                    m1, m2 = st.columns(2)
                    m1.metric("ממוצע כללי (כל המקצועות)", f"{overall_avg:.2f}")
                    m2.metric("מספר מקצועות עם ציון", len(subjects))
                    st.markdown("---")

                    # הצגת כרטיסיות לכל מקצוע
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
                                w_txt = f" (משקל: {item['weight']:g}%)" if item['weight'] > 0 else ""
                                st.write(f"**{idx}. {item['event']}:** `{item['grade']:g}`{w_txt}")

            except Exception as e:
                st.error(f"שגיאה: {e}")