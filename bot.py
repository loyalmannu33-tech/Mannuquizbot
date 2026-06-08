import telebot
import json
import threading
import time
import requests
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 👇 YAHAN APNI NAYI KEYS DALEIN 👇
TOKEN = os.environ.get('BOT_TOKEN)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
# 👆 YAHAN APNI NAYI KEYS DALEIN 👆

bot = telebot.TeleBot(TOKEN)

# Global Variables
quiz_setup = {}
group_scores = {}
active_q = {}
chat_quizzes = {}

# --- AI FETCH LOGIC ---
def fetch_single_question_ai(chat_id, setup, index):
    prompt = (
        f"Generate 1 unique MCQ about: {setup.get('topic')}. Level: {setup.get('level')}. "
        f"Language: {setup.get('lang', 'Hindi')}. Provide strictly in this JSON format without markdown code blocks: "
        f'{{"question": "...", "options": ["Option 1", "Option 2", "Option 3", "Option 4"], "correct": "Option 1", "explanation": "..."}}'
    )
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4
            }, 
            timeout=15
        ).json()
            
        content = response['choices'][0]['message']['content'].strip()
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        return json.loads(content)
    except Exception as e:
        print(f"Groq AI Fetch Error: {e}")
        return None

# --- STOP QUIZ COMMAND ---
@bot.message_handler(commands=['stop'])
def force_stop_quiz(message):
    chat_id = message.chat.id
    if chat_id in active_q:
        bot.send_message(chat_id, "🛑 <b>Quiz ko beech mein hi rok diya gaya hai! Chaliye Winners dekhte hain...</b>", parse_mode="HTML")
        active_q[chat_id]['timer_running'] = False
        show_leaderboard(chat_id)
        active_q.pop(chat_id, None)
    else:
        bot.send_message(chat_id, "⚠️ Abhi koi quiz chalu nahi hai.")

# --- STEP 1: START & TOPIC ---
@bot.message_handler(commands=['quiznow'])
def ask_topic(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "✍️ <b>Quiz ka Topic likh kar bhejein:</b>\n(Jaise: Anatomy, Blood, Computers, etc.)", parse_mode="HTML")
    bot.register_next_step_handler(message, ask_level)

# --- STEP 2: LEVEL BUTTONS ---
def ask_level(message):
    chat_id = message.chat.id
    quiz_setup[chat_id] = {'topic': message.text}
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Easy 🟢", callback_data="setup_lvl_Easy"),
        InlineKeyboardButton("Normal 🟡", callback_data="setup_lvl_Normal"),
        InlineKeyboardButton("Hard 🔴", callback_data="setup_lvl_Hard")
    )
    bot.send_message(chat_id, f"📚 Topic: <b>{message.text}</b>\n\n📊 Ab <b>Level</b> select karein:", reply_markup=markup, parse_mode="HTML")

# --- STEP 3: QUESTION COUNT BUTTONS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('setup_lvl_'))
def ask_count(call):
    chat_id = call.message.chat.id
    quiz_setup[chat_id]['level'] = call.data.split('_')[2]
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("10 Qs", callback_data="setup_cnt_10"),
        InlineKeyboardButton("20 Qs", callback_data="setup_cnt_20"),
        InlineKeyboardButton("50 Qs", callback_data="setup_cnt_50")
    )
    bot.send_message(chat_id, "🔢 Quiz mein total <b>kitne questions</b> chahiye?", reply_markup=markup, parse_mode="HTML")

# --- STEP 4: LANGUAGE BUTTONS (NEW) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('setup_cnt_'))
def ask_language(call):
    chat_id = call.message.chat.id
    quiz_setup[chat_id]['q_count'] = int(call.data.split('_')[2])
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("Hindi 🇮🇳", callback_data="setup_lang_Hindi"),
        InlineKeyboardButton("English 🇬🇧", callback_data="setup_lang_English"),
        InlineKeyboardButton("Hinglish 📝", callback_data="setup_lang_Hinglish")
    )
    bot.send_message(chat_id, "🌐 Quiz ki <b>Bhasha (Language)</b> select karein:", reply_markup=markup, parse_mode="HTML")

# --- STEP 5: TIMER BUTTONS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('setup_lang_'))
def ask_timer(call):
    chat_id = call.message.chat.id
    quiz_setup[chat_id]['lang'] = call.data.split('_')[2]
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("15 Sec", callback_data="setup_time_15"),
        InlineKeyboardButton("30 Sec", callback_data="setup_time_30"),
        InlineKeyboardButton("60 Sec", callback_data="setup_time_60")
    )
    bot.send_message(chat_id, "⏱ Har question ka <b>Timer</b> select karein:", reply_markup=markup, parse_mode="HTML")

# --- STEP 6: START QUIZ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('setup_time_'))
def start_quiz_engine(call):
    chat_id = call.message.chat.id
    quiz_setup[chat_id]['time'] = int(call.data.split('_')[2])
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    
    group_scores[chat_id] = {}
    chat_quizzes[chat_id] = []
    active_q[chat_id] = {'index': 0, 'answered_users': [], 'clicks': {}, 'voter_details': {}, 'timer_running': True}
    
    setup_info = (
        f"🚀 <b>Quiz Setup Complete!</b>\n\n"
        f"📌 Topic: {quiz_setup[chat_id]['topic']}\n"
        f"📊 Level: {quiz_setup[chat_id]['level']}\n"
        f"🌐 Lang: {quiz_setup[chat_id]['lang']}\n"
        f"📝 Questions: {quiz_setup[chat_id]['q_count']}\n"
        f"⏱ Timer: {quiz_setup[chat_id]['time']} Sec\n\n"
        f"<b>Pehla question aa raha hai...</b>"
    )
    bot.send_message(chat_id, setup_info, parse_mode="HTML")
    send_next_question(chat_id)

# --- GET QUIZ TEXT FORMAT (WITH INLINE VOTERS) ---
def get_quiz_text(chat_id, index, time_left, show_results=False, user_opt_idx=None, correct_idx=None):
    q_data = chat_quizzes[chat_id][index]
    options_list = q_data.get('options', [])
    labels = ["A", "B", "C", "D"]
    
    text = f"<b>🔹 Q{index+1}: {q_data['question']}</b>\n\n"
    
    # Voter details ko options ke hisab se group karna
    voters_by_opt = {0: [], 1: [], 2: [], 3: []}
    if show_results and 'voter_details' in active_q.get(chat_id, {}):
        for uid, details in active_q[chat_id]['voter_details'].items():
            if details['choice'] in voters_by_opt:
                voters_by_opt[details['choice']].append(details['name'])

    for i, opt in enumerate(options_list):
        if show_results:
            if i == correct_idx:
                text += f"✅ <b>{labels[i]})</b> {opt}\n"
            elif i == user_opt_idx and i != correct_idx:
                text += f"❌ <b>{labels[i]})</b> {opt}\n"
            else:
                text += f"🔹 <b>{labels[i]})</b> {opt}\n"
                
            # Kis kis ne ye option chuna wo naam dikhayein
            if voters_by_opt[i]:
                voter_names = ", ".join(voters_by_opt[i])
                text += f"   └ 👤 <i>{voter_names}</i>\n"
        else:
            text += f"<b>{labels[i]})</b> {opt}\n"
            
    if show_results:
        text += f"\n💡 <b>Explanation:</b> <i>{q_data.get('explanation', 'N/A')}</i>"
    else:
        clock_emojis = ["🕛", "🕒", "🕕", "🕘"]
        current_emoji = clock_emojis[time_left % 4]
        text += f"\n{current_emoji} <b>Time Remaining: {time_left} Seconds</b>"
        
    return text

# --- LIVE TIMER COUNTDOWN THREAD ---
def run_live_timer(chat_id, index, time_limit):
    time_left = time_limit
    while time_left > 0:
        if chat_id not in active_q or active_q[chat_id]['index'] != index or not active_q[chat_id]['timer_running']:
            return 
            
        time.sleep(1)
        time_left -= 1
        
        if time_left % 5 == 0 or time_left <= 3:
            try:
                msg_id = active_q[chat_id]['msg_id']
                updated_text = get_quiz_text(chat_id, index, time_left)
                
                # Sirf chote emojis wale buttons rahenge (No 'View Results' button)
                markup = InlineKeyboardMarkup(row_width=4)
                btn_list = [InlineKeyboardButton(e, callback_data=f"ans_{index}_{i}") for i, e in enumerate(["🅰️", "🅱️", "🅲", "🅳"])]
                markup.add(*btn_list)
                
                bot.edit_message_text(updated_text, chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
            except:
                pass
                
    if chat_id in active_q and active_q[chat_id]['index'] == index and active_q[chat_id]['timer_running']:
        handle_timeout(chat_id, index)

def handle_timeout(chat_id, index):
    active_q[chat_id]['timer_running'] = False
    q_data = chat_quizzes[chat_id][index]
    options_list = q_data.get('options', [])
    correct_opt = q_data.get('correct', '')
    
    correct_idx = -1
    for i, opt in enumerate(options_list):
        if str(opt).strip() == str(correct_opt).strip():
            correct_idx = i
            break
            
    # Timeout hone par result dikhaye, bina kisi ke answer ke (user_opt_idx=-1)
    final_text = get_quiz_text(chat_id, index, 0, show_results=True, user_opt_idx=-1, correct_idx=correct_idx)
    try:
        # Edit message and remove buttons completely
        bot.edit_message_text(final_text, chat_id, active_q[chat_id]['msg_id'], reply_markup=None, parse_mode="HTML")
    except: 
        pass
    
    active_q[chat_id]['index'] += 1
    threading.Timer(4.0, lambda: send_next_question(chat_id)).start()

# --- QUESTION SENDER LOGIC ---
def send_next_question(chat_id):
    if chat_id not in active_q: 
        return
    index = active_q[chat_id]['index']
    
    if index >= quiz_setup[chat_id]['q_count']:
        show_leaderboard(chat_id)
        active_q.pop(chat_id, None)
        return
    
    q_data = fetch_single_question_ai(chat_id, quiz_setup[chat_id], index)
    if not q_data or 'options' not in q_data or len(q_data['options']) < 4:
        bot.send_message(chat_id, "⚠️ AI Response slow hai, 2 second mein retry kar rahe hain...")
        time.sleep(2)
        send_next_question(chat_id)
        return
        
    chat_quizzes[chat_id].append(q_data)
    timer_sec = quiz_setup[chat_id]['time']
    
    active_q[chat_id]['answered_users'] = []
    active_q[chat_id]['timer_running'] = True
    active_q[chat_id]['voter_details'] = {}
    
    text = get_quiz_text(chat_id, index, timer_sec)
    
    markup = InlineKeyboardMarkup(row_width=4)
    btn_list = [InlineKeyboardButton(e, callback_data=f"ans_{index}_{i}") for i, e in enumerate(["🅰️", "🅱️", "🅲", "🅳"])]
    markup.add(*btn_list)
    
    msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    active_q[chat_id]['msg_id'] = msg.message_id
    
    threading.Thread(target=run_live_timer, args=(chat_id, index, timer_sec)).start()

# --- ANSWER CHECKER ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('ans_'))
def handle_answer(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    user_name = call.from_user.first_name
    parts = call.data.split('_')
    q_idx, opt_idx = int(parts[1]), int(parts[2])
    
    if chat_id not in active_q or active_q[chat_id]['index'] != q_idx:
        bot.answer_callback_query(call.id, "⏳ Yeh question expire ho chuka hai!")
        return
        
    if user_id in active_q[chat_id]['answered_users']:
        bot.answer_callback_query(call.id, "⚠️ Aap pehle hi answer de chuke hain!")
        return
        
    active_q[chat_id]['answered_users'].append(user_id)
    active_q[chat_id]['timer_running'] = False 
    
    q_data = chat_quizzes[chat_id][q_idx]
    correct_opt = q_data.get('correct', '')
    options_list = q_data.get('options', [])
    
    correct_idx = -1
    for i, opt in enumerate(options_list):
        if str(opt).strip() == str(correct_opt).strip():
            correct_idx = i
            break
            
    # Record user vote
    if user_id not in active_q[chat_id]['voter_details']:
        active_q[chat_id]['voter_details'][user_id] = {'name': user_name, 'choice': opt_idx}
        
    if user_id not in group_scores[chat_id]:
        group_scores[chat_id][user_id] = {'name': user_name, 'right': 0, 'wrong': 0}
        
    if opt_idx == correct_idx:
        group_scores[chat_id][user_id]['right'] += 1
        bot.answer_callback_query(call.id, "✅ Sahi Jawab!")
    else:
        group_scores[chat_id][user_id]['wrong'] += 1
        bot.answer_callback_query(call.id, "❌ Galat Jawab!")
        
    # Result generate karo aur options ke neeche naam dikhao
    final_text = get_quiz_text(chat_id, q_idx, 0, show_results=True, user_opt_idx=opt_idx, correct_idx=correct_idx)
    
    try:
        # Edit karke buttons hata diye jayenge
        bot.edit_message_text(final_text, chat_id, call.message.message_id, reply_markup=None, parse_mode="HTML")
    except: 
        pass
    
    active_q[chat_id]['index'] += 1
    # 4 Second ka gap taki sab log naam aur explanation padh sakein
    threading.Timer(4.0, lambda: send_next_question(chat_id)).start()

# --- FINAL TOP 5 LEADERBOARD ---
def show_leaderboard(chat_id):
    scores = group_scores.get(chat_id, {})
    if not scores:
        bot.send_message(chat_id, "🏆 <b>Quiz Samapt!</b>\n\nKoi participant nahi tha.", parse_mode="HTML")
        return
        
    sorted_users = sorted(scores.values(), key=lambda x: x['right'], reverse=True)
    text = "🏆 <b>FINAL LEADERBOARD (TOP 5 WINNERS)</b> 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
    
    for i, user in enumerate(sorted_users[:5]):
        medal = medals[i] if i < len(medals) else "🏅"
        text += f"{medal} <b>{user['name']}</b>\n   ✅ Sahi: {user['right']} | ❌ Galat: {user['wrong']}\n\n"
        
    bot.send_message(chat_id, text, parse_mode="HTML")
    if sorted_users:
        bot.send_message(chat_id, f"🌟 <b>Congratulations Champion:</b> {sorted_users[0]['name']}! 🏆🎉", parse_mode="HTML")

from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Krishu Quiz Bot is Running 24/7!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("🚀 NATIVE @QuizBot format Pydroid par Start ho gaya hai...")
    
    # Render ke liye Flask server ko alag thread me start karna
    server_thread = threading.Thread(target=run_server)
    server_thread.start()
    
    while True:
        try:
            bot.polling(none_stop=True, timeout=30)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
