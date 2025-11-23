import json
import requests
from openai import OpenAI
from typing import Dict, Any, List
from datetime import datetime, timedelta
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ========= הגדרות כלליות =========

# שם ה-Google Sheet שלך (חייב להיות מדויק!)
SHEET_NAME = "Buzz Deliveries" 

# טעינת סודות ממשתני סביבה
OPENAI_KEY = os.environ.get("OPENAI_KEY", "DEFAULT_OPENAI_KEY_IF_MISSING")
GREEN_INSTANCE = os.environ.get("GREEN_INSTANCE", "DEFAULT_GREEN_INSTANCE_IF_MISSING")
GREEN_TOKEN = os.environ.get("GREEN_TOKEN", "DEFAULT_GREEN_TOKEN_IF_MISSING")

# טעינת מפתחות גוגל ממשתנה סביבה (הכי בטוח לענן)
# אם משתנה הסביבה לא קיים, מנסה לחפש קובץ מקומי (לפיתוח)
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") 

# ========= פונקציות עזר ל-Google Sheets =========

def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    if GOOGLE_CREDS_JSON:
        # טעינה מתוך משתנה סביבה (מחרוזת JSON)
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    elif os.path.exists("credentials.json"):
        # טעינה מקובץ מקומי (לפיתוח)
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    else:
        raise Exception("❌ לא נמצאו מפתחות Google Sheets (לא במשתנה סביבה ולא בקובץ).")
        
    return gspread.authorize(creds)

def load_data() -> Dict[str, Dict[str, Any]]:
    """
    טוען את הנתונים מ-Google Sheet.
    מבנה ה-Sheet יהיה טבלה שטוחה, ואנחנו נמיר אותה למבנה ה-Batches המוכר לקוד.
    """
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1 # גיליון ראשון
        records = sheet.get_all_records() # רשימה של מילונים
        
        # המרה ממבנה שטוח (טבלה) למבנה היררכי (Batches) שהקוד שלנו מכיר
        all_batches = {}
        
        for row in records:
            # המרה של שדות ריקים מ-Sheet ל-None או ערך מתאים
            # gspread מחזיר מחרוזות ריקות, הקוד שלנו לפעמים מצפה ל-None
            for k, v in row.items():
                if v == "": row[k] = None
            
            batch_id = row.get("batch_id")
            if not batch_id: continue # דלג על שורות ריקות
            
            if batch_id not in all_batches:
                all_batches[batch_id] = {
                    "dispatcher_phone": row.get("dispatcher_phone_ref"), # שדה עזר לשמירת מספר השליח ברמת ה-Batch
                    "upload_time": row.get("upload_time_ref"),
                    "sent_status": "Sent", # נניח שנשלח
                    "deliveries": []
                }
            
            # ניקוי שדות עזר מהמשלוח עצמו
            delivery_data = row.copy()
            # (אופציונלי: אפשר להשאיר הכל, זה לא מפריע)
            
            all_batches[batch_id]["deliveries"].append(delivery_data)
            
        return all_batches

    except Exception as e:
        print(f"❌ שגיאה בטעינה מ-Google Sheets: {e}")
        return {}


def save_data(data: Dict[str, Dict[str, Any]]):
    """
    שומר את כל הנתונים ל-Google Sheet (דריסה מלאה - פחות יעיל אבל בטוח).
    """
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1
        
        # המרה ממבנה היררכי (Batches) למבנה שטוח (רשימת שורות לטבלה)
        flat_records = []
        
        for batch_id, batch_data in data.items():
            dispatcher = batch_data.get("dispatcher_phone")
            upload_time = batch_data.get("upload_time")
            
            for delivery in batch_data.get("deliveries", []):
                # הוספת שדות עזר לכל שורה כדי שנוכל לשחזר את המבנה אח"כ
                row = delivery.copy()
                row["batch_id"] = batch_id
                row["dispatcher_phone_ref"] = dispatcher
                row["upload_time_ref"] = upload_time
                
                # המרת None למחרוזת ריקה (כי Sheets לא אוהב None)
                for k, v in row.items():
                    if v is None: row[k] = ""
                
                flat_records.append(row)
        
        if not flat_records:
            return # אין מה לשמור
            
        # עדכון ה-Sheet
        # 1. ננקה את הגיליון (למעט כותרות אם נרצה, אבל כאן נדרוס הכל לנוחות)
        sheet.clear()
        
        # 2. כתיבת כותרות (לפי המפתחות של הרשומה הראשונה)
        if flat_records:
            headers = list(flat_records[0].keys())
            # וידוא סדר כותרות הגיוני (אופציונלי)
            
            # עדכון עם gspread (דורש רשימה של רשימות)
            # שורה ראשונה: כותרות
            data_to_write = [headers]
            
            # שאר השורות: נתונים
            for record in flat_records:
                row_data = [record.get(h, "") for h in headers]
                data_to_write.append(row_data)
            
            sheet.update("A1", data_to_write)
            
    except Exception as e:
        print(f"❌ שגיאה בשמירה ל-Google Sheets: {e}")


# ========= שאר הפונקציות (ללא שינוי) =========

def normalize_phone(phone: str) -> str:
    phone = str(phone).strip().replace("-", "").replace(" ", "").replace("+", "")
    phone = phone.lstrip("0")
    if not phone.startswith("972"):
        phone = "972" + phone
    return phone


def calculate_time_range(position: int, start_time: datetime = None) -> str:
    if start_time is None:
        start_time = datetime.now()
    
    base_delay = 30
    per_delivery = 5
    
    start_delay = base_delay + (position * per_delivery)
    end_delay = start_delay + 120 
    
    arrival_min = start_time + timedelta(minutes=start_delay)
    arrival_max = start_time + timedelta(minutes=end_delay)
    
    time_format = "%H:%M"
    return f"{arrival_min.strftime(time_format)}-{arrival_max.strftime(time_format)}"


def send_whatsapp_message(phone: str, message: str):
    phone = normalize_phone(phone)
    url = f"https://api.green-api.com/waInstance{GREEN_INSTANCE}/sendMessage/{GREEN_TOKEN}"
    chat_id = phone + "@c.us"
    payload = {"chatId": chat_id, "message": message}
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print("❌ שגיאה בשליחה:", e)
        return False


# ========= AI – ניתוח ושיחה (טבעי וזורם) =========

def analyze_text_with_ai(text: str, current_state: dict) -> dict:
    # ... (אותה פונקציית AI מעולה שכבר כתבנו, ללא שינוי) ...
    client = OpenAI(api_key=OPENAI_KEY)
    state_desc = json.dumps(current_state, ensure_ascii=False)
    
    system_prompt = f"""
    אתה "בוט Buzz", שליח חכם, אדיב וקליל.
    המטרה שלך: לנהל שיחה נעימה עם הלקוח כדי להשיג את פרטי הגישה למשלוח.
    
    הנחיות לתגובה (reply_message):
    1. **סגנון דיבור:** דבר בעברית טבעית, יומיומית וקצרה. תהיה נחמד אבל ענייני. מותר להשתמש באימוג'יז 📦😊.
    2. **זרימת השיחה:** - אם חסר מידע, תשאל עליו בצורה שמתאימה להקשר. אל תהיה רובוטי ("חסר שדה X").
       - תשאל שאלה אחת בכל פעם כדי לא להעמיס.
       - סדר עדיפות: קודם כל תברר אם בבית. אם לא - איפה להשאיר. אחר כך פרטים טכניים (דירה/קומה/קוד).
    
    3. **חילוץ מידע:**
       - נסה להבין הקשר. אם הלקוח כותב "תשאיר בלובי", תבין מזה שצריך לעדכן את המיקום ל"לובי" ושלא צריך לשאול יותר שאלות.
       - אם הלקוח כותב "קומה 2 דירה 4", תחלץ את שניהם בבת אחת.
    
    מבנה פלט JSON:
    {{
      "extracted_data": {{
          "someone_home": "yes" | "no" | null,
          "drop_location": string | null,
          "apartment": string | null,
          "floor": string | null,
          "entrance_code": string | null
      }},
      "reply_message": "ההודעה שלך ללקוח"
    }}
    
    מצב נוכחי של הנתונים (מה שיש לנו כבר):
    {state_desc}
    """
    
    user_content = f"""הודעת הלקוח: "{text}"\nתגיב בצורה טבעית."""
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",  "content": user_content},
            ],
            temperature=0.7,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print("❌ AI Error:", e)
        return {
            "extracted_data": {},
            "reply_message": "סליחה, לא הבנתי. תוכל לחזור על זה?"
        }