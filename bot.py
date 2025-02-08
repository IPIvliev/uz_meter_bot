import telebot
import requests
import json
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
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

# Получаем данные пользователя из бд 1С
def get_user_data(phone, headers, chat_id):
    # Проверяем телефон в 1С
    response = requests.get(f"{CHECK_PHONE_URL}{phone}", headers=headers)
    if response.status_code == 200:
        data = response.json()
        if "List" in data and len(data["List"]) > 0:
            user_data[chat_id]['account'] = data["List"]

            if "counters" not in user_data[chat_id]:
                user_data[chat_id]["counters"] = []
            user_data[chat_id]["counters"] = user_data[chat_id]['account'][0]['Counters']

            print(user_data[chat_id]["counters"])

            # set_user_data(user_data, chat_id, data)
            # print('user_data[chat_id] ', user_data[chat_id])
            bot.send_message(chat_id, "Ваш номер телефона привязан к системе. Начнём сбор показаний.")
            request_meter_readings(chat_id)
        else:
            bot.send_message(chat_id, "Ваш номер не найден в системе. Давайте привяжем его.")
            request_ls_info(chat_id)
    else:
        print(response.text)
        bot.send_message(chat_id, "Ошибка связи с сервером. Попробуйте позже.")

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
    get_user_data(phone, headers, chat_id)

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
            get_user_data(user_data[chat_id]["phone"], headers, chat_id)
            request_meter_readings(chat_id)
        else:
            bot.send_message(chat_id, "Ошибка привязки: " + result.get("INFO", "Попробуйте ещё раз."))
            request_ls_info(chat_id)
    else:
        print(response.text)
        bot.send_message(chat_id, "Ошибка сервера. Попробуйте позже.")

# Запрос показаний счётчиков
def request_meter_readings(chat_id):
    """Запрашивает у пользователя показания по каждому счётчику"""
    counters = user_data[chat_id].get("counters", [])

    if not counters:
        bot.send_message(chat_id, "Ошибка: не найдено ни одного счётчика.")
        return

    user_data[chat_id]["current_counter_index"] = 0  # Начинаем с первого счётчика
    ask_for_next_reading(chat_id)

def ask_for_next_reading(chat_id):
    """Запрашивает показания у пользователя для следующего счётчика"""
    index = user_data[chat_id].get("current_counter_index", 0)
    counters = user_data[chat_id]["counters"]

    if index >= len(counters):
        send_all_meters(chat_id)  # Отправляем все показания в 1С
        return

    current_counter = counters[index]
    factory_number = current_counter.get("device_number", "Неизвестный номер")

    user_data[chat_id]["current_counter"] = current_counter  # Запоминаем текущий счётчик

    # Клавиатура с вариантами
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("Ввести вручную"), KeyboardButton("Отправить фото"))

    bot.send_message(
        chat_id,
        f"Введите показания для счётчика №{factory_number} или отправьте фото:",
        reply_markup=markup,
    )



@bot.message_handler(func=lambda message: message.text in ["Ввести вручную", "Отправить фото"])
def handle_meter_option(message):
    """Обрабатывает выбор пользователя"""
    chat_id = message.chat.id
    option = message.text

    if option == "Ввести вручную":
        bot.send_message(chat_id, "Введите показания цифрами:", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(message, handle_manual_input)

    elif option == "Отправить фото":
        bot.send_message(chat_id, "Отправьте фото счётчика.", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(message, handle_photo)

def extract_value_from_yolo(result):
    return "123.45"  # Здесь должно быть извлечение числа из результата модели

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    """Обрабатывает фото, распознаёт показания через YOLO"""
    chat_id = message.chat.id

    if "current_counter" not in user_data[chat_id]:
        bot.send_message(chat_id, "Ошибка: счётчик не найден.")
        return

    file_info = bot.get_file(message.photo[-1].file_id)
    file_path = file_info.file_path
    photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

    # Загружаем фото
    response = requests.get(photo_url, stream=True)
    if response.status_code != 200:
        bot.send_message(chat_id, "Ошибка при загрузке фото.")
        return

    with open("meter.jpg", "wb") as f:
        f.write(response.content)

    # Распознаём показания через YOLO
    result = model("meter.jpg")

    if result:
        recognized_value = extract_value_from_yolo(result)
        user_data[chat_id]["current_photo"] = photo_url
        user_data[chat_id]["current_value"] = recognized_value

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_value"),
            InlineKeyboardButton("✏️ Ввести вручную", callback_data="manual_input"),
        )

        bot.send_message(chat_id, f"Распознано: {recognized_value}. Подтвердите или введите вручную.", reply_markup=markup)
    else:
        bot.send_message(chat_id, "Не удалось распознать. Введите вручную:")
        bot.register_next_step_handler_by_chat_id(chat_id, handle_manual_input)

@bot.callback_query_handler(func=lambda call: call.data in ["confirm_value", "manual_input"])
def handle_confirmation(call):
    chat_id = call.message.chat.id
    if call.data == "confirm_value":
        save_meter_reading(chat_id)
    elif call.data == "manual_input":
        bot.send_message(chat_id, "Введите показания вручную:")
        bot.register_next_step_handler_by_chat_id(chat_id, handle_manual_input)

@bot.message_handler(func=lambda message: message.text.replace('.', '', 1).isdigit())
def handle_manual_input(message):
    chat_id = message.chat.id
    print('["ls_number"] ', user_data[chat_id]['account'][0]['ls_number'])
    user_data[chat_id]["current_value"] = float(message.text)
    ["current_counter"]
    save_meter_reading(chat_id)

def save_meter_reading(chat_id):
    # if "counters" not in user_data[chat_id]:
    #     user_data[chat_id]["counters"] = []

    factory_number = user_data[chat_id]["counters"][0].get("device_number", "Неизвестный номер")
    print('factory_number ', factory_number)

    user_data[chat_id]["counters"].append({
        "factory_number": factory_number,
        "param": user_data[chat_id]["current_value"],
        "photo_link": user_data[chat_id].get("current_photo", ""),
    })
    ask_add_more_counters(chat_id)

# Запрос на добавление ещё одного счётчика или завершение
def ask_add_more_counters(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("➕ Отправить ещё один", callback_data="add_more"),
        InlineKeyboardButton("✅ Завершить", callback_data="finish"),
    )
    bot.send_message(chat_id, "Что дальше?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["add_more", "finish"])
def handle_counter_options(call):
    chat_id = call.message.chat.id
    if call.data == "add_more":
        bot.send_message(chat_id, "Отправьте фото следующего счётчика или введите данные вручную.")
    elif call.data == "finish":
        send_all_meters(chat_id)

# Отправка всех показаний в 1С
def send_all_meters(chat_id):
    print('user_data[chat_id]["counters"] ', user_data[chat_id]["counters"])
    data = [{
        "ls_number": user_data[chat_id]['account'][0]['ls_number'],
        "date": "2024.10.30",
        "Counters": user_data[chat_id]["counters"]
    }]
    response = requests.post(WRITE_PARAMS_URL, json=data, headers=headers)
    # print()

    if response.status_code == 200 and response.json().get("result") == "success":
        bot.send_message(chat_id, "Все показания успешно отправлены!")
    else:
        bot.send_message(chat_id, response.json().get("ERROR"))


bot.polling(none_stop=True)