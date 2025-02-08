import telebot
import requests
import json
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from ultralytics import YOLO

# Инициализация бота
from config import TOKEN
bot = telebot.TeleBot(TOKEN)

# Инициализация модели YOLO
model = YOLO("meter.pt")  # Замените на путь к вашей обученной модели

# Базовые API-эндпоинты
API_BASE = "http://virt41.vet.uz/UT2_FL/hs/telegram"
CHECK_PHONE_URL = f"{API_BASE}/check_phone/"
CHECK_LS_CONNECT_URL = f"{API_BASE}/check_ls_connect/"
WRITE_PARAMS_URL = f"{API_BASE}/write_params/"
headers = {
  'Authorization': 'Basic VGVsZWdyYW1BUEk6YXNkQVNEQCMxNDU2'
}
# Хранилище временных данных (без базы данных)
user_data = {}

# Команда /start
@bot.message_handler(commands=["start"])
def start(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    button = KeyboardButton("Отправить мой номер телефона", request_contact=True)
    markup.add(button)
    bot.send_message(
        message.chat.id,
        "Здравствуйте! Для работы с ботом отправьте ваш контакт.",
        reply_markup=markup,
    )

# Обработка контакта
@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    if not message.contact:
        bot.send_message(message.chat.id, "Пожалуйста, отправьте контакт через кнопку ниже.")
        return

    phone = message.contact.phone_number
    chat_id = message.chat.id
    user_data[chat_id] = {"phone": phone}

    # Проверяем телефон в 1С
    response = requests.get(f"{CHECK_PHONE_URL}{phone}", headers=headers)
    if response.status_code == 200:
        data = response.json()
        if "List" in data and len(data["List"]) > 0:
            user_data[chat_id]["accounts"] = data["List"]
            bot.send_message(chat_id, "Ваш номер телефона привязан к системе. Начнём сбор показаний.")
            request_meter_readings(chat_id)
        else:
            bot.send_message(chat_id, "Ваш номер не найден в системе. Давайте привяжем его.")
            request_ls_info(chat_id)
    else:
        print(response.text)
        bot.send_message(chat_id, "Ошибка связи с сервером. Попробуйте позже.")

# Запрос данных для привязки ЛС
def request_ls_info(chat_id):
    bot.send_message(chat_id, "Введите номер лицевого счёта:")
    bot.register_next_step_handler_by_chat_id(chat_id, process_ls_number)

def process_ls_number(message):
    chat_id = message.chat.id
    user_data[chat_id]["ls_number"] = message.text
    bot.send_message(chat_id, "Введите номер дома:")
    bot.register_next_step_handler_by_chat_id(chat_id, process_house_number)

def process_house_number(message):
    chat_id = message.chat.id
    user_data[chat_id]["house_number"] = message.text
    bot.send_message(chat_id, "Введите номер квартиры (если есть, иначе напишите 0):")
    bot.register_next_step_handler_by_chat_id(chat_id, process_apartment_number)

def process_apartment_number(message):
    chat_id = message.chat.id
    user_data[chat_id]["apartment_number"] = message.text if message.text != "0" else ""

    # Отправляем запрос на привязку
    data = {
        "phone_number": user_data[chat_id]["phone"],
        "ls_number": user_data[chat_id]["ls_number"],
        "house_number": user_data[chat_id]["house_number"],
        "apartment_number": user_data[chat_id]["apartment_number"],
    }
    response = requests.post(CHECK_LS_CONNECT_URL, json=data, headers=headers)

    if response.status_code == 200:
        result = response.json()
        if result.get("result") == "success":
            bot.send_message(chat_id, "Номер телефона успешно привязан! Теперь можно вводить показания.")
            request_meter_readings(chat_id)
        else:
            bot.send_message(chat_id, "Ошибка привязки: " + result.get("INFO", "Попробуйте ещё раз."))
            request_ls_info(chat_id)
    else:
        print(response.text)
        bot.send_message(chat_id, "Ошибка сервера. Попробуйте позже.")

# Запрос показаний счётчиков
def request_meter_readings(chat_id):
    bot.send_message(chat_id, "Отправьте фото счётчика или введите показания вручную.")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    file_path = file_info.file_path
    photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

    # Сохранение фото
    file = requests.get(photo_url)
    with open("meter.jpg", "wb") as f:
        f.write(file.content)

    # Распознавание YOLO
    result = model("meter.jpg")
    if result:
        recognized_value = extract_value_from_yolo(result)
        bot.send_message(chat_id, f"Распознано: {recognized_value}. Подтвердите или введите вручную.")
        user_data[chat_id]["photo_link"] = photo_url
        user_data[chat_id]["meter_value"] = recognized_value
    else:
        bot.send_message(chat_id, "Не удалось распознать показания. Введите вручную:")
        bot.register_next_step_handler_by_chat_id(chat_id, handle_manual_input)

def extract_value_from_yolo(result):
    # Здесь логика извлечения текста из результата YOLO
    return "123.45"  # Замените на реальную обработку

@bot.message_handler(func=lambda message: message.text.isdigit())
def handle_manual_input(message):
    chat_id = message.chat.id
    user_data[chat_id]["meter_value"] = message.text
    send_meter_data(chat_id)

# Отправка показаний в 1С
def send_meter_data(chat_id):
    data = [
        {
            "ls_number": user_data[chat_id]["ls_number"],
            "date": "2024.10.30",
            "Counters": [
                {
                    "factory_number": "12345678",
                    "param": user_data[chat_id]["meter_value"],
                    "photo_link": user_data.get(chat_id, {}).get("photo_link", ""),
                }
            ],
        }
    ]
    response = requests.post(WRITE_PARAMS_URL, headers=headers, json=data)

    if response.status_code == 200 and response.json().get("result") == "success":
        bot.send_message(chat_id, "Показания успешно отправлены!")
    else:
        bot.send_message(chat_id, "Ошибка отправки. Попробуйте снова.")

# Запуск бота
bot.polling(none_stop=True)
