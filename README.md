# Airtable Gym Telegram Bot

بوت تيليجرام تفاعلي يقرأ من Airtable ويعرض البرنامج بالقوائم والأزرار، ويسجل الأداء داخل جدول `Log`.

## المميزات
- قائمة رئيسية بالأزرار
- اختيار الأسبوع ثم اليوم ثم التمرين
- عرض تفاصيل التمرين: sets / reps / RPE / الراحة / الملاحظات
- دعم روابط الفيديو من جدول `Videos` أو من `Program` / `Exercise_Catalog`
- عرض البدائل من `Substitutions`
- عرض الإحماء من `Warmup`
- تسجيل الأداء في `Log`
- عرض آخر أداء لنفس التمرين
- إحصائيات بسيطة
- زر `تمرين النهارده` يقترح التالي بناءً على آخر تسجيل لك

## 1) قبل التشغيل
لازم يكون عندك:
- Telegram bot token من BotFather
- Airtable Personal Access Token
- Airtable Base ID
- الجداول بالأسماء التالية:
  - Program
  - Exercise_Catalog
  - Videos
  - Substitutions
  - Warmup
  - Log

## 2) تجهيز البيئة
```bash
python -m venv .venv
source .venv/bin/activate  # على ويندوز: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3) ملف الإعدادات
انسخ `.env.example` إلى `.env` ثم املأ القيم:
```bash
cp .env.example .env
```

## 4) تشغيل البوت
```bash
python bot.py
```

## 5) الجداول المطلوبة
### Program
لازم يحتوي على الأقل على الأعمدة:
- Week
- Day
- Day Focus
- Exercise
- Normalized Exercise
- Working Sets
- Reps / Duration
- RPE / %
- Rest
- Notes
- Video URL
- Video Note
- Alternative 1
- Alternative 2
- Alternative 3

### Exercise_Catalog
يفضل يحتوي:
- Normalized Exercise
- Display Name
- Primary Muscle
- Video URL
- Video Note
- Alternative 1
- Alternative 2
- Alternative 3

### Videos
- Exercise
- Normalized Exercise
- Video URL
- Video Note

### Substitutions
- Exercise
- Normalized Exercise
- Alternative 1
- Alternative 2
- Alternative 3

### Warmup
- Exercise
- Sets
- Reps / Time
- Notes

### Log
لازم يحتوي الأعمدة دي بالضبط:
- Timestamp
- Week
- Day
- Exercise
- Weight
- Reps_Done
- Sets_Done
- Notes
- User_ID
- User_Name

## 6) تشغيله على Render
- اعمل New Web Service أو Background Worker
- ارفع ملفات المشروع إلى GitHub
- أضف Environment Variables من `.env`
- Start command:
```bash
python bot.py
```

## 7) تحسينات مستقبلية
- إضافة زر “التالي” للتنقل بين التمارين داخل اليوم
- حفظ `current week` يدويًا لكل مستخدم
- تسجيل أكثر من set بالتفصيل
- توليد PR tracking
- تنبيهات راحة بين الجولات
