import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("gym_bot")

# ---------- Env ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN", "")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
BOT_LANGUAGE = os.getenv("BOT_LANGUAGE", "ar")
TIMEZONE_NAME = os.getenv("TIMEZONE_NAME", "Africa/Cairo")

TABLE_PROGRAM = os.getenv("TABLE_PROGRAM", "Program")
TABLE_EXERCISE = os.getenv("TABLE_EXERCISE", "Exercise_Catalog")
TABLE_VIDEOS = os.getenv("TABLE_VIDEOS", "Videos")
TABLE_SUBS = os.getenv("TABLE_SUBS", "Substitutions")
TABLE_WARMUP = os.getenv("TABLE_WARMUP", "Warmup")
TABLE_LOG = os.getenv("TABLE_LOG", "Log")

API_BASE = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"
HEADERS = {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}

# ---------- User state keys ----------
STATE_IDLE = "idle"
STATE_AWAIT_SEARCH = "await_search"
STATE_AWAIT_WEIGHT = "await_weight"
STATE_AWAIT_REPS = "await_reps"
STATE_AWAIT_SETS = "await_sets"
STATE_AWAIT_NOTES = "await_notes"


@dataclass
class ExerciseSelection:
    week: int
    day: int
    exercise: str
    day_focus: str
    working_sets: str
    reps: str
    rpe: str
    rest: str
    notes: str
    video_url: str
    video_note: str
    normalized: str
    alt1: str
    alt2: str
    alt3: str


# ---------- Airtable helpers ----------
def _check_env() -> None:
    missing = [
        name
        for name, value in [
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("AIRTABLE_TOKEN", AIRTABLE_TOKEN),
            ("AIRTABLE_BASE_ID", AIRTABLE_BASE_ID),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")


def airtable_request(method: str, table: str, *, params: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{API_BASE}/{table}"
    resp = requests.request(method, url, headers=HEADERS, params=params, json=payload, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Airtable error {resp.status_code}: {resp.text}")
    return resp.json()


def airtable_list_records(table: str, *, fields: Optional[List[str]] = None, formula: Optional[str] = None, max_records: Optional[int] = None, sort_field: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"pageSize": 100}
    if fields:
        params["fields[]"] = fields
    if formula:
        params["filterByFormula"] = formula
    if max_records:
        params["maxRecords"] = max_records
    if sort_field:
        params["sort[0][field]"] = sort_field
        params["sort[0][direction]"] = "asc"

    all_records: List[Dict[str, Any]] = []
    offset = None
    while True:
        if offset:
            params["offset"] = offset
        data = airtable_request("GET", table, params=params)
        all_records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return all_records


def airtable_create_record(table: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    return airtable_request("POST", table, payload={"fields": fields})


# ---------- Data access ----------
def get_available_weeks() -> List[int]:
    rows = airtable_list_records(TABLE_PROGRAM, fields=["Week"])
    weeks = sorted({int(r["fields"].get("Week")) for r in rows if r["fields"].get("Week") not in (None, "")})
    return weeks


def get_days_for_week(week: int) -> List[Tuple[int, str]]:
    rows = airtable_list_records(
        TABLE_PROGRAM,
        fields=["Week", "Day", "Day Focus"],
        formula=f"{{Week}}={week}",
    )
    seen = {}
    for row in rows:
        f = row.get("fields", {})
        day = f.get("Day")
        if day is None:
            continue
        seen[int(day)] = str(f.get("Day Focus", ""))
    return sorted(seen.items(), key=lambda x: x[0])


def get_exercises_for_day(week: int, day: int) -> List[Dict[str, Any]]:
    formula = f"AND({{Week}}={week},{{Day}}={day})"
    rows = airtable_list_records(TABLE_PROGRAM, formula=formula)
    return [r.get("fields", {}) for r in rows]


def get_video_for_exercise(exercise: str, normalized: str) -> Tuple[str, str]:
    for formula in [f"{{Exercise}}='{exercise.replace("'", "\\'")}'", f"{{Normalized Exercise}}='{normalized.replace("'", "\\'")}'"]:
        rows = airtable_list_records(TABLE_VIDEOS, formula=formula, max_records=1)
        if rows:
            f = rows[0].get("fields", {})
            return str(f.get("Video URL", "")), str(f.get("Video Note", ""))
    return "", ""


def get_catalog_for_exercise(normalized: str) -> Dict[str, Any]:
    rows = airtable_list_records(TABLE_EXERCISE, formula=f"{{Normalized Exercise}}='{normalized.replace("'", "\\'")}'", max_records=1)
    return rows[0].get("fields", {}) if rows else {}


def get_substitutions(exercise: str, normalized: str) -> Tuple[str, str, str]:
    for formula in [f"{{Exercise}}='{exercise.replace("'", "\\'")}'", f"{{Normalized Exercise}}='{normalized.replace("'", "\\'")}'"]:
        rows = airtable_list_records(TABLE_SUBS, formula=formula, max_records=1)
        if rows:
            f = rows[0].get("fields", {})
            return str(f.get("Alternative 1", "")), str(f.get("Alternative 2", "")), str(f.get("Alternative 3", ""))
    return "", "", ""


def get_warmup_rows() -> List[Dict[str, Any]]:
    rows = airtable_list_records(TABLE_WARMUP)
    return [r.get("fields", {}) for r in rows]


def get_recent_logs(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    rows = airtable_list_records(TABLE_LOG, formula=f"{{User_ID}}='{user_id}'")
    def keyfunc(f: Dict[str, Any]) -> str:
        return str(f.get("Timestamp", ""))
    fields_rows = [r.get("fields", {}) for r in rows]
    fields_rows.sort(key=keyfunc, reverse=True)
    return fields_rows[:limit]


def get_last_log_for_exercise(user_id: int, exercise: str) -> Optional[Dict[str, Any]]:
    rows = airtable_list_records(TABLE_LOG, formula=f"AND({{User_ID}}='{user_id}',{{Exercise}}='{exercise.replace("'", "\\'")}')")
    fields_rows = [r.get("fields", {}) for r in rows]
    fields_rows.sort(key=lambda f: str(f.get("Timestamp", "")), reverse=True)
    return fields_rows[0] if fields_rows else None


def infer_today_workout(user_id: int) -> Tuple[int, int]:
    recent = get_recent_logs(user_id, limit=1)
    weeks = get_available_weeks()
    if not recent:
        return weeks[0], 1
    r = recent[0]
    try:
        week = int(r.get("Week", weeks[0]))
        day = int(r.get("Day", 1))
    except Exception:
        return weeks[0], 1
    days = [d for d, _ in get_days_for_week(week)]
    if day in days and day != max(days):
        return week, day + 1
    next_weeks = [w for w in weeks if w > week]
    if next_weeks:
        return next_weeks[0], 1
    return weeks[0], 1


def build_selection_from_fields(fields: Dict[str, Any]) -> ExerciseSelection:
    exercise = str(fields.get("Exercise", ""))
    normalized = str(fields.get("Normalized Exercise", exercise))
    catalog = get_catalog_for_exercise(normalized)
    video_url = str(fields.get("Video URL", "") or catalog.get("Video URL", ""))
    video_note = str(fields.get("Video Note", "") or catalog.get("Video Note", ""))
    if not video_url:
        v_url, v_note = get_video_for_exercise(exercise, normalized)
        video_url = video_url or v_url
        video_note = video_note or v_note
    alt1 = str(fields.get("Alternative 1", "") or catalog.get("Alternative 1", ""))
    alt2 = str(fields.get("Alternative 2", "") or catalog.get("Alternative 2", ""))
    alt3 = str(fields.get("Alternative 3", "") or catalog.get("Alternative 3", ""))
    if not any([alt1, alt2, alt3]):
        alt1, alt2, alt3 = get_substitutions(exercise, normalized)
    return ExerciseSelection(
        week=int(fields.get("Week", 1)),
        day=int(fields.get("Day", 1)),
        exercise=exercise,
        day_focus=str(fields.get("Day Focus", "")),
        working_sets=str(fields.get("Working Sets", "")),
        reps=str(fields.get("Reps / Duration", "")),
        rpe=str(fields.get("RPE / %", "")),
        rest=str(fields.get("Rest", "")),
        notes=str(fields.get("Notes", "")),
        video_url=video_url,
        video_note=video_note,
        normalized=normalized,
        alt1=alt1,
        alt2=alt2,
        alt3=alt3,
    )


# ---------- UI helpers ----------
def chunk_buttons(buttons: List[InlineKeyboardButton], n: int = 2) -> List[List[InlineKeyboardButton]]:
    return [buttons[i:i+n] for i in range(0, len(buttons), n)]


def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🏋️ برنامج التمرين", callback_data="menu:program")],
        [InlineKeyboardButton("📅 تمرين النهارده", callback_data="menu:today"), InlineKeyboardButton("🔥 الإحماء", callback_data="menu:warmup")],
        [InlineKeyboardButton("📝 سجل أدائي", callback_data="menu:log"), InlineKeyboardButton("📊 إحصائياتي", callback_data="menu:stats")],
        [InlineKeyboardButton("🕘 آخر أداء", callback_data="menu:recent"), InlineKeyboardButton("🔎 ابحث عن تمرين", callback_data="menu:search")],
    ]
    return InlineKeyboardMarkup(rows)


def weeks_kb() -> InlineKeyboardMarkup:
    weeks = get_available_weeks()
    buttons = [InlineKeyboardButton(f"الأسبوع {w}", callback_data=f"week:{w}") for w in weeks]
    rows = chunk_buttons(buttons, 2)
    rows.append([InlineKeyboardButton("⬅️ الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def days_kb(week: int) -> InlineKeyboardMarkup:
    day_rows = []
    for day, focus in get_days_for_week(week):
        label = f"اليوم {day}"
        if focus:
            label += f" - {focus[:16]}"
        day_rows.append([InlineKeyboardButton(label, callback_data=f"day:{week}:{day}")])
    day_rows.append([InlineKeyboardButton("⬅️ الأسابيع", callback_data="menu:program"), InlineKeyboardButton("🏠 الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(day_rows)


def exercises_kb(week: int, day: int) -> InlineKeyboardMarkup:
    exercises = get_exercises_for_day(week, day)
    rows = []
    for idx, fields in enumerate(exercises):
        name = str(fields.get("Exercise", f"Exercise {idx+1}"))[:32]
        rows.append([InlineKeyboardButton(name, callback_data=f"ex:{week}:{day}:{idx}")])
    rows.append([InlineKeyboardButton("⬅️ الأيام", callback_data=f"week:{week}"), InlineKeyboardButton("🏠 الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def exercise_actions_kb(sel: ExerciseSelection) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    if sel.video_url:
        rows.append([InlineKeyboardButton("🎥 افتح الفيديو", url=sel.video_url)])
    rows.append([
        InlineKeyboardButton("✅ سجل أدائي", callback_data=f"logstart:{sel.week}:{sel.day}:{sel.exercise}"),
        InlineKeyboardButton("🕘 آخر مرة", callback_data=f"last:{sel.exercise}"),
    ])
    rows.append([
        InlineKeyboardButton("🔁 البدائل", callback_data=f"subs:{sel.exercise}"),
        InlineKeyboardButton("⬅️ تمارين اليوم", callback_data=f"day:{sel.week}:{sel.day}"),
    ])
    rows.append([InlineKeyboardButton("🏠 الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def searched_exercises_kb(matches: List[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(m[:35], callback_data=f"searchpick:{m}")] for m in matches[:15]]
    rows.append([InlineKeyboardButton("🏠 الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(rows)


# ---------- Rendering ----------
def render_exercise(sel: ExerciseSelection) -> str:
    parts = [
        f"<b>{sel.exercise}</b>",
        f"الأسبوع: {sel.week} | اليوم: {sel.day}",
    ]
    if sel.day_focus:
        parts.append(f"التركيز: {sel.day_focus}")
    parts.append(f"الجولات: {sel.working_sets or '-'}")
    parts.append(f"العدات / المدة: {sel.reps or '-'}")
    if sel.rpe:
        parts.append(f"RPE / النسبة: {sel.rpe}")
    if sel.rest:
        parts.append(f"الراحة: {sel.rest}")
    if sel.notes:
        parts.append(f"ملاحظات: {sel.notes}")
    if sel.video_note:
        parts.append(f"معلومة الفيديو: {sel.video_note}")
    return "\n".join(parts)


def render_subs(sel: ExerciseSelection) -> str:
    alts = [a for a in [sel.alt1, sel.alt2, sel.alt3] if a]
    if not alts:
        return f"لا يوجد بدائل محفوظة حاليًا لـ <b>{sel.exercise}</b>."
    txt = [f"<b>بدائل {sel.exercise}</b>"]
    for i, alt in enumerate(alts, 1):
        txt.append(f"{i}. {alt}")
    return "\n".join(txt)


def render_recent_logs(logs: List[Dict[str, Any]]) -> str:
    if not logs:
        return "لسه ما سجلتش أي أداء."
    lines = ["<b>آخر أداءاتك</b>"]
    for r in logs:
        lines.append(
            f"• W{r.get('Week','-')} D{r.get('Day','-')} | {r.get('Exercise','-')} | وزن: {r.get('Weight','-')} | عدات: {r.get('Reps_Done','-')} | جولات: {r.get('Sets_Done','-')}"
        )
    return "\n".join(lines)


def render_stats(logs: List[Dict[str, Any]]) -> str:
    if not logs:
        return "لسه ما فيش بيانات كفاية للإحصائيات."
    total = len(logs)
    unique_ex = len({str(r.get('Exercise', '')) for r in logs})
    last = logs[0]
    return (
        "<b>إحصائياتك</b>\n"
        f"عدد التسجيلات: {total}\n"
        f"عدد التمارين المختلفة: {unique_ex}\n"
        f"آخر تمرين: {last.get('Exercise','-')}\n"
        f"آخر أسبوع/يوم: W{last.get('Week','-')} / D{last.get('Day','-')}"
    )


def render_warmup(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "لا توجد بيانات إحماء حاليًا."
    parts = ["<b>الإحماء</b>"]
    for row in rows:
        parts.append(f"• {row.get('Exercise','-')} | Sets: {row.get('Sets','-')} | Reps/Time: {row.get('Reps / Time','-')}")
        if row.get('Notes'):
            parts.append(f"  {row.get('Notes')}")
    return "\n".join(parts)


# ---------- Bot handlers ----------
async def send_or_edit(update: Update, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=False)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = STATE_IDLE
    text = (
        "أهلاً بيك في <b>Sayem Gym</b>\n"
        "اختار من القايمة اللي تحت، وأنا أمشي معاك خطوة بخطوة من غير أوامر معقدة."
    )
    await send_or_edit(update, text, main_menu_kb())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""

    if data == "home":
        await start(update, context)
        return

    if data == "menu:program":
        await send_or_edit(update, "اختار الأسبوع:", weeks_kb())
        return

    if data.startswith("week:"):
        week = int(data.split(":")[1])
        context.user_data["selected_week"] = week
        await send_or_edit(update, f"الأسبوع {week} — اختار اليوم:", days_kb(week))
        return

    if data.startswith("day:"):
        _, week, day = data.split(":")
        week_i, day_i = int(week), int(day)
        context.user_data["selected_week"] = week_i
        context.user_data["selected_day"] = day_i
        await send_or_edit(update, f"الأسبوع {week_i} | اليوم {day_i}\nاختار التمرين:", exercises_kb(week_i, day_i))
        return

    if data.startswith("ex:"):
        _, week, day, idx = data.split(":")
        fields = get_exercises_for_day(int(week), int(day))[int(idx)]
        sel = build_selection_from_fields(fields)
        context.user_data["selected_exercise"] = sel.exercise
        context.user_data["current_selection"] = sel.__dict__
        await send_or_edit(update, render_exercise(sel), exercise_actions_kb(sel))
        return

    if data == "menu:today":
        user_id = update.effective_user.id
        week, day = infer_today_workout(user_id)
        await send_or_edit(update, f"ده تمرينك المقترح النهارده: الأسبوع {week} | اليوم {day}", exercises_kb(week, day))
        return

    if data == "menu:warmup":
        await send_or_edit(update, render_warmup(get_warmup_rows()), InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        return

    if data == "menu:recent":
        logs = get_recent_logs(update.effective_user.id, 5)
        await send_or_edit(update, render_recent_logs(logs), InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        return

    if data == "menu:stats":
        logs = get_recent_logs(update.effective_user.id, 100)
        await send_or_edit(update, render_stats(logs), InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        return

    if data == "menu:search":
        context.user_data["state"] = STATE_AWAIT_SEARCH
        await send_or_edit(update, "ابعت اسم التمرين أو جزء منه، وأنا أجيب لك النتائج.", InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        return

    if data.startswith("searchpick:"):
        exercise_name = data.split(":", 1)[1]
        rows = airtable_list_records(TABLE_PROGRAM, formula=f"{{Exercise}}='{exercise_name.replace("'", "\\'")}'", max_records=1)
        if not rows:
            await send_or_edit(update, "ما لقيتش التمرين ده في البرنامج.", InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
            return
        sel = build_selection_from_fields(rows[0].get("fields", {}))
        context.user_data["current_selection"] = sel.__dict__
        await send_or_edit(update, render_exercise(sel), exercise_actions_kb(sel))
        return

    if data.startswith("subs:"):
        sel_dict = context.user_data.get("current_selection")
        if not sel_dict:
            await send_or_edit(update, "اختار تمرين الأول.", main_menu_kb())
            return
        sel = ExerciseSelection(**sel_dict)
        await send_or_edit(update, render_subs(sel), InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data=f"day:{sel.week}:{sel.day}")], [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        return

    if data.startswith("last:"):
        exercise = data.split(":", 1)[1]
        last = get_last_log_for_exercise(update.effective_user.id, exercise)
        if not last:
            text = f"لسه ما سجلتش أداء سابق لـ <b>{exercise}</b>."
        else:
            text = (
                f"<b>آخر أداء لـ {exercise}</b>\n"
                f"التاريخ: {last.get('Timestamp','-')}\n"
                f"الأسبوع/اليوم: W{last.get('Week','-')} / D{last.get('Day','-')}\n"
                f"الوزن: {last.get('Weight','-')}\n"
                f"العدات: {last.get('Reps_Done','-')}\n"
                f"الجولات: {last.get('Sets_Done','-')}\n"
                f"ملاحظات: {last.get('Notes','-')}"
            )
        await send_or_edit(update, text, InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        return

    if data == "menu:log":
        sel_dict = context.user_data.get("current_selection")
        if sel_dict:
            sel = ExerciseSelection(**sel_dict)
            context.user_data["log_payload"] = {"Week": sel.week, "Day": sel.day, "Exercise": sel.exercise}
            context.user_data["state"] = STATE_AWAIT_WEIGHT
            await send_or_edit(update, f"هنسجل أداء <b>{sel.exercise}</b>\nابعت الوزن اللي لعبت بيه.", InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        else:
            await send_or_edit(update, "اختار تمرين الأول من برنامج التمرين، وبعدها اضغط سجل أدائي.", main_menu_kb())
        return

    if data.startswith("logstart:"):
        _, week, day, exercise = data.split(":", 3)
        context.user_data["log_payload"] = {"Week": int(week), "Day": int(day), "Exercise": exercise}
        context.user_data["state"] = STATE_AWAIT_WEIGHT
        await send_or_edit(update, f"هنسجل أداء <b>{exercise}</b>\nابعت الوزن اللي لعبت بيه.", InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]]))
        return

    await send_or_edit(update, "الخيار ده لسه مش متعرف. ارجع للرئيسية.", main_menu_kb())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    state = context.user_data.get("state", STATE_IDLE)

    if state == STATE_AWAIT_SEARCH:
        rows = airtable_list_records(TABLE_PROGRAM, fields=["Exercise"])
        unique = sorted({str(r.get("fields", {}).get("Exercise", "")).strip() for r in rows if r.get("fields", {}).get("Exercise")})
        matches = [e for e in unique if text.lower() in e.lower()]
        if not matches:
            context.user_data["state"] = STATE_IDLE
            await update.message.reply_text("ما لقيتش نتائج. جرّب كلمة تانية.", reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
            return
        context.user_data["state"] = STATE_IDLE
        await update.message.reply_text("دي أقرب النتائج:", reply_markup=searched_exercises_kb(matches), parse_mode=ParseMode.HTML)
        return

    if state == STATE_AWAIT_WEIGHT:
        context.user_data.setdefault("log_payload", {})["Weight"] = text
        context.user_data["state"] = STATE_AWAIT_REPS
        await update.message.reply_text("تمام. ابعت عدد العدات اللي عملتها.")
        return

    if state == STATE_AWAIT_REPS:
        context.user_data.setdefault("log_payload", {})["Reps_Done"] = text
        context.user_data["state"] = STATE_AWAIT_SETS
        await update.message.reply_text("كويس. ابعت عدد الجولات اللي خلصتها.")
        return

    if state == STATE_AWAIT_SETS:
        context.user_data.setdefault("log_payload", {})["Sets_Done"] = text
        context.user_data["state"] = STATE_AWAIT_NOTES
        await update.message.reply_text("لو عندك ملاحظة ابعتها دلوقتي، أو ابعت 0 لو مافيش.")
        return

    if state == STATE_AWAIT_NOTES:
        payload = context.user_data.setdefault("log_payload", {})
        payload["Notes"] = "" if text == "0" else text
        payload["Timestamp"] = datetime.now().isoformat(timespec="seconds")
        payload["User_ID"] = str(update.effective_user.id)
        payload["User_Name"] = update.effective_user.full_name
        airtable_create_record(TABLE_LOG, payload)
        context.user_data["state"] = STATE_IDLE
        context.user_data["log_payload"] = {}
        await update.message.reply_text("تم تسجيل أدائك ✅", reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text("استخدم /start أو اختار من القايمة.", reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)


def main() -> None:
    _check_env()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
