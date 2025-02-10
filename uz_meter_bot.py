import telebot
import requests
import json
import time
import logging
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from ultralytics import YOLO
from predict import extract_value_from_yolo

# Инициализация бота
from config import TOKEN
bot = telebot.TeleBot(TOKEN)

# Настройка логирования: уровень INFO, форматирование и запись в файл bot.log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename="bot.log",
    filemode="a",
    encoding="utf-8"
)
# Базовые API-эндпоинты
API_BASE = "http://virt41.vet.uz/UT2_FL/hs/telegram"
CHECK_PHONE_URL = f"{API_BASE}/check_phone/"
CHECK_LS_CONNECT_URL = f"{API_BASE}/check_ls_connect/"
WRITE_PARAMS_URL = f"{API_BASE}/write_params/"
from config import headers

# Хранилище временных данных (без базы данных)
user_data = {}

def get_user_data(phone, headers, chat_id):
    """Получаем данные пользователя из 1С и запускаем сбор показаний"""
    response = requests.get(f"{CHECK_PHONE_URL}{phone}", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Ответ сервера на попытку проверить привязку номера телефона к ЛС: {data}")
        logging.info((f"Ответ сервера на попытку проверить привязку номера телефона к ЛС: {data}"))

        if "List" in data and len(data["List"]) > 0:
            user_data[chat_id]['account'] = data["List"]
            # Сохраняем список счётчиков, полученных из 1С
            user_data[chat_id]["counters"] = user_data[chat_id]['account'][0]['Counters']
            # print("Полученные счётчики:", user_data[chat_id]["counters"])
            bot.send_message(chat_id, "Ваш номер телефона привязан к системе. Начнём сбор показаний.")
            request_meter_readings(chat_id)
        elif data.get("ERROR") == "Передан некорректный номер телефона":
            logging.error((f"Некорректный номер телефона: {phone}"))
            print(f"Некорректный номер телефона: {phone}")
            bot.send_message(chat_id, "Передан некорректный номер телефона")
        else:
            bot.send_message(chat_id, "Ваш номер не найден в системе. Давайте привяжем его.")
            request_ls_info(chat_id)
    else:
        # print('error: ', data)
        bot.send_message(chat_id, "Ошибка связи с сервером. Попробуйте позже.")

# При старте выводим кнопку "Передать показания"
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Передать показания")
    bot.send_message(chat_id, "Здравствуйте! Для передачи показаний нажмите кнопку 'Передать показания'.", reply_markup=markup)

# Если пользователь нажимает кнопку "Передать показания"
@bot.message_handler(func=lambda message: message.text == "Передать показания")
def handle_submit_readings(message):
    chat_id = message.chat.id
    # Если контакт ещё не отправлен, запрашиваем его
    if chat_id not in user_data or "phone" not in user_data[chat_id]:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button = KeyboardButton("Отправить мой номер телефона", request_contact=True)
        markup.add(button)
        bot.send_message(chat_id, "Для начала работы отправьте ваш контакт.", reply_markup=markup)
    else:
        # Если контакт уже есть – начинаем сбор показаний
        request_meter_readings(chat_id)

@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    if not message.contact:
        bot.send_message(message.chat.id, "Пожалуйста, отправьте контакт через кнопку ниже.")
        return

    phone = message.contact.phone_number
    chat_id = message.chat.id
    user_data[chat_id] = {"phone": phone}
    get_user_data(phone, headers, chat_id)

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
            bot.send_message(chat_id, "Ошибка привязки: " + result.get("ERROR", "Попробуйте ещё раз."))
            request_ls_info(chat_id)
    else:
        result = response.json()
        print(f"Ошибка сервера в функции process_apartment_number. Попробуйте позже: {result}")
        bot.send_message(chat_id, "Ошибка сервера. Попробуйте позже.")

def request_meter_readings(chat_id):
    """Инициализируем сбор показаний устанавливаем индекс первого счётчика"""
    counters = user_data[chat_id].get("counters", [])
    if not counters:
        bot.send_message(chat_id, "Ошибка: не найдено ни одного счётчика.")
        return
    user_data[chat_id]["current_counter_index"] = 0
    ask_for_meter_reading(chat_id)

def ask_for_meter_reading(chat_id):
    """
    Запрашиваем показание для текущего счётчика.
    Пользователь может отправить либо число (текстом), либо фото.
    """
    index = user_data[chat_id].get("current_counter_index", 0)
    counters = user_data[chat_id]["counters"]
    if index >= len(counters):
        finish_meter_readings(chat_id)
        return

    current_counter = counters[index]
    user_data[chat_id]["current_counter"] = current_counter
    bot.send_message(
        chat_id,
        f"Введите показание для счётчика №{current_counter.get('device_number', 'Неизвестный номер')}.\n"
        f"Предыдущие показания счётчика были: {current_counter.get('last_param', '0.00')}.\n"
        "Вы можете отправить число или фотографию счётчика."
    )
    bot.register_next_step_handler_by_chat_id(chat_id, process_meter_reading)

def process_meter_reading(message):
    chat_id = message.chat.id

    if message.content_type == "photo":
        # Получаем информацию о фото и формируем URL для скачивания
        file_info = bot.get_file(message.photo[-1].file_id)
        file_path = file_info.file_path
        photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

        # Скачиваем фото
        response = requests.get(photo_url, stream=True)
        if response.status_code != 200:
            bot.send_message(chat_id, "Ошибка при загрузке фото. Пожалуйста, попробуйте ещё раз.")
            bot.register_next_step_handler_by_chat_id(chat_id, process_meter_reading)
            return

        with open("meter.jpg", "wb") as f:
            f.write(response.content)

        # Используем функцию, которая обрабатывает фото: обнаруживает рамку, выравнивает и распознаёт цифры
        recognized_value = extract_value_from_yolo("meter.jpg")
        if recognized_value is None:
            bot.send_message(chat_id, "Не удалось распознать цифры с фото. Пожалуйста, введите показание вручную.")
            bot.register_next_step_handler_by_chat_id(chat_id, process_manual_correction)
            return

        # Предлагаем пользователю подтвердить распознанное значение или исправить его вручную
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Подтвердить", callback_data="confirm_value"))
        markup.add(InlineKeyboardButton("Исправить", callback_data="manual_input"))
        bot.send_message(
            chat_id,
            f"Распознано показание: {recognized_value}.\n\nЕсли всё верно, нажмите «Подтвердить».\nЕсли требуется исправить, нажмите «Исправить» и введите правильное значение.",
            reply_markup=markup
        )
        user_data[chat_id]["current_value"] = recognized_value
        user_data[chat_id]["current_photo"] = photo_url
        return

    elif message.content_type == "text":
        # Если пользователь вводит значение текстом (например, после исправления)
        text = message.text.strip().replace(',', '.')
        try:
            value = float(text)
            user_data[chat_id]["current_value"] = value
            save_meter_reading(chat_id)
        except ValueError:
            bot.send_message(chat_id, "Пожалуйста, введите корректное числовое значение.")
            bot.register_next_step_handler_by_chat_id(chat_id, process_meter_reading)
            return

def save_meter_reading(chat_id):
    """
    Функция сохраняет текущее показание для текущего счётчика и
    переходит к следующему счётчику для ввода показаний.
    
    Она использует данные, сохранённые в user_data:
      - "current_value": текущее введённое или распознанное значение,
      - "current_photo": (опционально) ссылка на фото, если показание получено с фото.
    
    После обновления данных счётчика функция увеличивает индекс и вызывает
    функцию, которая запрашивает показание для следующего счётчика.
    """
    # Получаем индекс текущего счётчика
    index = user_data[chat_id]["current_counter_index"]
    # Извлекаем текущий счётчик из данных пользователя
    current_counter = user_data[chat_id]["current_counter"]
    
    # Обновляем показание и фото (если имеется)
    current_counter["param"] = user_data[chat_id]["current_value"]
    current_counter["photo_link"] = user_data[chat_id].get("current_photo", "")
    
    # Сохраняем обновлённые данные для текущего счётчика
    user_data[chat_id]["counters"][index] = current_counter
    
    # Переходим к следующему счётчику
    user_data[chat_id]["current_counter_index"] += 1
    ask_for_meter_reading(chat_id)

@bot.callback_query_handler(func=lambda call: call.data in ["confirm_value", "manual_input"])
def handle_confirmation(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "confirm_value":
        # Пользователь подтвердил распознанное значение
        save_meter_reading(chat_id)
    elif call.data == "manual_input":
        # Пользователь хочет исправить значение вручную
        bot.send_message(chat_id, "Введите корректное показание вручную:")
        bot.register_next_step_handler_by_chat_id(chat_id, process_manual_correction)

def process_manual_correction(message):
    chat_id = message.chat.id
    try:
        value = float(message.text.strip().replace(',', '.'))
        user_data[chat_id]["current_value"] = value
        save_meter_reading(chat_id)
    except ValueError:
        bot.send_message(chat_id, "Введите корректное числовое значение.")
        bot.register_next_step_handler_by_chat_id(chat_id, process_manual_correction)

def finish_meter_readings(chat_id):
    """
    Когда все показания введены, формируем сводное сообщение
    и предлагаем подтвердить или начать передачу заново.
    """
    counters = user_data[chat_id]["counters"]
    summary_lines = []
    for counter in counters:
        line = f"Для счётчика {counter.get('device_number', 'Неизвестный номер')} вы передали показание {counter.get('param', 'нет данных')}."
        summary_lines.append(line)
    summary_message = "\n".join(summary_lines)
    summary_message += (
        "\n\nЕсли показания записаны правильно, нажмите кнопку «Отправить».\n"
        "Если показания содержат ошибку, нажмите «Начать заново»."
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отправить", callback_data="send_all"))
    markup.add(InlineKeyboardButton("Начать заново", callback_data="restart"))
    bot.send_message(chat_id, summary_message, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["send_all", "restart"])
def handle_final_decision(call):
    chat_id = call.message.chat.id
    if call.data == "send_all":
        send_all_meters(chat_id)
    elif call.data == "restart":
        # Сбрасываем индекс и начинаем сбор показаний сначала
        user_data[chat_id]["current_counter_index"] = 0
        bot.send_message(chat_id, "Передача показаний начнется заново.")
        ask_for_meter_reading(chat_id)

def send_all_meters(chat_id):
    """
    Формирует данные в виде:
    [
        {
            "ls_number": "07000038886",
            "date": "2024.10.30",
            "Counters": [
                {
                    "factory_number": "33333333",
                    "param": "159",
                    "photo_link": ""
                },
                {
                    "factory_number": "22222222",
                    "param": "51",
                    "photo_link": ""
                }
            ]
        }
    ]
    где factory_number – это значение device_number.
    """
    # print("Собранные показания:", user_data[chat_id]["counters"])
    transformed_counters = []
    for counter in user_data[chat_id]["counters"]:
        transformed_counters.append({
            "factory_number": counter.get("device_number", ""),
            "param": str(counter.get("param", "")),
            "photo_link": counter.get("photo_link", "")
        })
    data = [{
        "ls_number": user_data[chat_id]['account'][0]['ls_number'],
        "date": "2024.10.30",
        "Counters": transformed_counters
    }]
    response = requests.post(WRITE_PARAMS_URL, json=data, headers=headers)
    if response.status_code == 200 and response.json().get("result") == "success":
        # После успешной передачи выводим кнопку для новой передачи показаний
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Передать новые показания", callback_data="restart_process"))
        bot.send_message(chat_id, "Все показания успешно отправлены!", reply_markup=markup)
    else:
        bot.send_message(chat_id, response.json().get("ERROR"))

# Обработка нажатия кнопки "Передать показания" после успешной передачи
@bot.callback_query_handler(func=lambda call: call.data == "restart_process")
def restart_process_handler(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    # Перезапрашиваем данные из 1С для актуального списка счётчиков
    phone = user_data.get(chat_id, {}).get("phone")
    if phone:
        bot.send_message(chat_id, "Перезапрашиваю данные из 1С, пожалуйста, подождите...")
        get_user_data(phone, headers, chat_id)
    else:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button = KeyboardButton("Отправить мой номер телефона", request_contact=True)
        markup.add(button)
        bot.send_message(chat_id, "Номер телефона не найден. Пожалуйста, отправьте ваш контакт.", reply_markup=markup)

# def extract_value_from_yolo(result):
#     # Здесь необходимо реализовать извлечение числа из результата модели.
#     # В этом примере возвращается тестовое значение.
#     return 'False'

# bot.polling(none_stop=True) # Для тестов

# Включаем бота в продакшн
if __name__ == '__main__':
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            time.sleep(3)
            print(e)
