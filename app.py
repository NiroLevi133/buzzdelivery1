import streamlit as st
import pandas as pd
from datetime import datetime
from services import (
    send_whatsapp_message,
    load_data,
    save_data,
    calculate_time_range,
    normalize_phone
)
import uuid 
import os 

# --- תיקון קריטי ל-Streamlit Cloud ---
# מעביר את הסיסמאות מ-st.secrets למשתני סביבה כדי ש-services.py יעבוד
if hasattr(st, "secrets"):
    if "OPENAI_KEY" in st.secrets:
        os.environ["OPENAI_KEY"] = st.secrets["OPENAI_KEY"]
    if "GREEN_INSTANCE" in st.secrets:
        os.environ["GREEN_INSTANCE"] = st.secrets["GREEN_INSTANCE"]
    if "GREEN_TOKEN" in st.secrets:
        os.environ["GREEN_TOKEN"] = st.secrets["GREEN_TOKEN"]
    if "GOOGLE_APPLICATION_CREDENTIALS_JSON" in st.secrets:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = st.secrets["GOOGLE_APPLICATION_CREDENTIALS_JSON"]
# ---------------------------------------

# עיצוב RTL והתאמות לטבלה
st.markdown("""
<style>
body, html, .stTextInput, .stButton, .stDataFrame, .stTextArea, div[data-testid="stTable"], .stNumberInput {
    direction: rtl;
    text-align: right;
}
/* עיצוב כותרות הטבלה */
th {
    text-align: right !important;
}
</style>
""", unsafe_allow_html=True)

# --- אתחול נתונים חכם ---
if "all_batches" not in st.session_state:
    data = load_data()
    if isinstance(data, list):
        st.session_state["all_batches"] = {}
    else:
        st.session_state["all_batches"] = data

if not isinstance(st.session_state["all_batches"], dict):
    st.session_state["all_batches"] = {}

if "temp_route_list" not in st.session_state:
    st.session_state["temp_route_list"] = []

st.sidebar.title("🚛 Buzz Lite")
page = st.sidebar.selectbox("בחר פעולה:", ["בניית מסלול (הזנה)", "המסלול שלי (צפייה)"])

# ============================================================
# 1) בניית מסלול (הזנה דינמית)
# ============================================================
if page == "בניית מסלול (הזנה)":
    st.title("📝 בניית מסלול הפצה")
    st.info("הוסף את המשלוחים אחד-אחד. בסיום, לחץ על 'שלח הודעות לכולם'.")
    
    if "dispatcher_phone" not in st.session_state:
        st.session_state["dispatcher_phone"] = ""
        
    dispatcher_phone = st.text_input("מספר הטלפון שלך (השליח):", 
                                     value=st.session_state["dispatcher_phone"],
                                     placeholder="05X-XXXXXXX").strip()
    st.session_state["dispatcher_phone"] = dispatcher_phone 

    st.markdown("---")

    current_list = st.session_state["temp_route_list"]
    if current_list:
        next_seq = max([item['seq'] for item in current_list]) + 1
    else:
        next_seq = 1

    with st.form(key="add_delivery_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 2, 2])
        with c1:
            seq_input = st.number_input("מס' סידורי", min_value=1, value=next_seq, step=1)
        with c2:
            name_input = st.text_input("שם הנמען (אופציונלי)")
        with c3:
            phone_input = st.text_input("טלפון (חובה)")
            
        add_btn = st.form_submit_button("➕ הוסף לרשימה")

    if add_btn:
        if not phone_input:
            st.error("❌ חובה להזין מספר טלפון.")
        else:
            new_item = {
                "seq": seq_input,
                "name": name_input if name_input else "לקוח",
                "phone": normalize_phone(phone_input)
            }
            st.session_state["temp_route_list"].append(new_item)
            st.rerun()

    if st.session_state["temp_route_list"]:
        st.write(f"### 📋 רשימת משלוחים ({len(st.session_state['temp_route_list'])})")
        
        df = pd.DataFrame(st.session_state["temp_route_list"])
        st.dataframe(
            df.rename(columns={"seq": "מס'", "name": "שם", "phone": "טלפון"}),
            use_container_width=True,
            hide_index=True
        )
        
        col_actions1, col_actions2 = st.columns(2)
        
        with col_actions1:
            if st.button("🗑️ נקה רשימה והתחל מחדש"):
                st.session_state["temp_route_list"] = []
                st.rerun()
                
        with col_actions2:
            if st.button("🚀 סיימתי - צור מסלול ושלח הודעות"):
                if not dispatcher_phone:
                    st.error("אנא הזן את מספר הטלפון שלך למעלה.")
                else:
                    batch_id = f"ROUTE-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    
                    new_batch = {
                        "dispatcher_phone": normalize_phone(dispatcher_phone),
                        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "deliveries": []
                    }
                    
                    progress = st.progress(0)
                    sent_count = 0
                    total = len(st.session_state["temp_route_list"])
                    
                    for i, item in enumerate(st.session_state["temp_route_list"]):
                        time_range = calculate_time_range(i + 1)
                        
                        delivery = {
                            "sequence_number": item["seq"],
                            "recipient_name": item["name"],
                            "recipient_phone": item["phone"],
                            "status": "נשלח",
                            "last_message": "",
                            "someone_home": None,
                            "drop_location": None,
                            "apartment": None,
                            "floor": None,
                            "entrance_code": None,
                            "estimated_time_range": time_range,
                            "batch_id": batch_id
                        }
                        
                        new_batch["deliveries"].append(delivery)
                        
                        msg_name = f" {item['name']}" if item['name'] != "לקוח" else ""
                        msg = f"""היי{msg_name}! 👋 כאן השליח של Buzz.
יש לי משלוח עבורך שצפוי להגיע בין השעות {time_range}.

כדי שאוכל למסור אותו, אני צריך לדעת:
❓ האם יהיה מישהו בבית בשעות אלו? (כן / לא)"""

                        send_whatsapp_message(item["phone"], msg)
                        sent_count += 1
                        progress.progress((i + 1) / total)
                    
                    st.session_state["all_batches"][batch_id] = new_batch
                    save_data(st.session_state["all_batches"])
                    
                    st.session_state["temp_route_list"] = []
                    st.success(f"✅ המסלול נוצר בהצלחה! נשלחו {sent_count} הודעות.")
                    st.balloons()

# ============================================================
# 2) המסלול שלי (צפייה וניהול)
# ============================================================
elif page == "המסלול שלי (צפייה)":
    st.title("📋 המסלול שלי")
    
    default_phone = st.session_state.get("dispatcher_phone", "")
    search = st.text_input("הכנס טלפון שליח:", value=default_phone, placeholder="05X-XXXXXXX").strip()
    
    if search:
        norm_search = normalize_phone(search)
        all_data = st.session_state["all_batches"]
        my_deliveries = []
        
        if isinstance(all_data, dict):
            for bid, bdata in all_data.items():
                if bdata.get("dispatcher_phone") == norm_search:
                    my_deliveries.extend(bdata["deliveries"])
        
        if not my_deliveries:
            st.warning("לא נמצאו משלוחים למספר זה.")
        else:
            df = pd.DataFrame(my_deliveries)
            df = df.sort_values(by=["batch_id", "sequence_number"], ascending=[False, True])
            
            st.subheader(f"סה״כ משלוחים פעילים: {len(df)}")

            df_show = df[[
                "sequence_number", "recipient_name", "recipient_phone", "someone_home", 
                "drop_location", "floor", "apartment", "entrance_code", "status"
            ]].rename(columns={
                "sequence_number": "מס'",
                "recipient_name": "שם",
                "recipient_phone": "טלפון",
                "someone_home": "בבית?",
                "drop_location": "איפה להשאיר",
                "floor": "קומה",
                "apartment": "דירה",
                "entrance_code": "קוד",
                "status": "סטטוס"
            })
            
            st.dataframe(df_show, hide_index=True)
            
            st.info("💡 הנתונים מתעדכנים בזמן אמת כשהלקוחות עונים בוואטסאפ.")
            
            if st.button("🔄 רענן נתונים"):
                st.session_state["all_batches"] = load_data()
                st.rerun()