import telebot
import threading
import time
import json

from datetime import datetime, timedelta
from config import token_bot, channel, token_ii
from openai import OpenAI

TOKEN = token_bot
CHANNEL_ID = channel
bot = telebot.TeleBot(TOKEN)
messages = []

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=token_ii
)

def run_telebot_with_reconnect(): # реконект и ошибки, возможно работает с ошибками
    while True:
        try:
            bot.send_message(CHANNEL_ID, "🚀*Автодайджест успешно запущен!* 🚀", parse_mode='Markdown')
            bot.polling(none_stop=True, skip_pending=True)
        except Exception as e:
            print("Ошибка: Недостаточно токенов, ", e)
            try:
                bot.send_message(CHANNEL_ID, "⚠️Ошибка: Недостаточно API "
                                             "токенов для использования нейросети (лимит 50 токенов в день")
            except Exception as send_err:
                print("Не удалось отправить сообщение об отключении:", send_err)
            time.sleep(10)

def contains_notnews_tag(text): #проверка на тег Notnews
    if not text:
        return False
    return 'Notnews' in text.lower()

def clean_openai_response(text):     #удаление ``````
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text

def clean_old_messages():       #очистка сообщений каждую неделю
    global messages
    one_week_ago = datetime.now() - timedelta(seconds=60)
    messages = [m for m in messages if m['date'] > one_week_ago]

def classify_news(text):    #промтик для нейронки
    prompt = (
        f"Объективно (опираясь на сегодняшние тренды) проанализируй текст новости:\n\"{text}\"\n"
        "Верни строго JSON с четырьмя полями:\n"
        "{\n"
        "  \"summary\": \О чем эта новость, напиши кратко, не более 20 слов в формате дайджеста \n"
        "  \"level\": \"Начальный уровень, Продвинутый уровень или Профессиональный уровень\",\n"
        "  \"direction\": \Одним словом оформи тег данной новости для удобного поиска (Датасаинс, "
        "Промптинг, Notnews, Инфографика, Кодинг) ,\n"
        "  \"relevance\": \Объективная оценка актуальности статьи на основе трендов направления, "
        "строго число от 1 до 10 (целое), необходим точный ответ так как от этого зависит качество обучения работников\n"
        "}\n"
        "Ответь только JSON, без комментариев и пояснений."
    )
    try:
        response = client.chat.completions.create(
            #model='deepseek/deepseek-chat-v3.1:free',
            model='openai/gpt-oss-120b:free',
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=400
        )
        answer = response.choices[0].message.content.strip()
        clean_answer = clean_openai_response(answer)
        data = json.loads(clean_answer) #распарсинг JSON-ответа модели
        return {
            "summary": data.get('summary', 'N/A'),
            "level": data.get("level", "N/A"),
            "direction": data.get("direction", "N/A"),
            "relevance": str(data.get("relevance", "N/A"))
        }
    except Exception as e:
        print("Ошибка при анализе новости:", e)
        print("Ответ модели:", answer)
        return {"level": "N/A", "direction": "N/A", "relevance": "N/A"}


def create_digest(messages): #создание списка новостей
    digest_lines = []
    channel_id_str = str(CHANNEL_ID)
    if channel_id_str.startswith("-100"):
        channel_id_short = channel_id_str[4:]
    else:
        channel_id_short = channel_id_str.lstrip('-')

    for msg in messages:
        text = msg['text']
        analysis = classify_news(text)
        message_link = f"https://t.me/c/{channel_id_short}/1/{msg['message_id']}"
        digest_lines.append(
            f"📰 Статья: {analysis['summary']}\n"
            f"🏷️ Тип инструмента: #{analysis['direction']}\n"
            f"🧑‍💻 Уровень владения: {analysis['level']}\n"
            f"✔️ Актуальность: {analysis['relevance']}\n"
            f"➡️ [Ссылка на сообщение]({message_link})\n"
        )
    return '\n'.join(digest_lines)


def fetch_and_send_summary(): #мейн функция по постингу дайджеста
    while True:
        time.sleep(60)
        clean_old_messages()
        if not messages:
            all_news = "За прошедшую неделю сообщений с ссылками не найдено."
        else:
            all_news = "📰*Дайджест за прошедшую неделю:*\n\n" + create_digest(messages)
        bot.send_message(CHANNEL_ID, all_news, parse_mode='Markdown')

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document'])
def handle_message(message):
    if int(message.chat.id) == int(CHANNEL_ID):
        text = message.text or message.caption or ''

        if message.forward_from or message.forward_from_chat:
            print("Это пересланное сообщение:")

        if text:
            analysis = classify_news(text)
            combined_fields = " ".join([str(analysis.get(k, "")).lower() for k in ["summary",
                                                                                   "direction", "level", "relevance"]])
            print("Debug combined_fields:", combined_fields)  # Отладка

            if contains_notnews_tag(combined_fields):
                print("Пропущено сообщение с тегом #Notnews после анализа")
                return

            print(f'Получено сообщение: {text}')
            messages.append({
                'text': text,
                'date': datetime.fromtimestamp(message.date),
                'message_id': message.message_id,
            })

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_telebot_with_reconnect, daemon=True)
    bot_thread.start()

    summary_thread = threading.Thread(target=fetch_and_send_summary, daemon=True)
    summary_thread.start()

    summary_thread.join()