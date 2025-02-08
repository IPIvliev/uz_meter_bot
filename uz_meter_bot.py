import telebot
import requests
import cv2
import numpy as np
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto

from config import TOKEN
YOLO_MODEL = "meter.pt"
bot = telebot.TeleBot(TOKEN)

API_URL_CHECK_PHONE = "http://virt41.vet.uz/UT2_FL/hs/telegram/check_phone/"
API_URL_SEND_PARAMS = "http://virt41.vet.uz/UT2_FL/hs/telegram/write_params/"

user_data = {}

def get_counters(phone):
    response = requests.get(f"{API_URL_CHECK_PHONE}{phone}")
    if response.status_code == 200:
        return response.json().get("List", [])
    return []

def recognize_meter_value(photo_path):
    model = cv2.dnn.readNet(YOLO_MODEL)
    image = cv2.imread(photo_path)
    blob = cv2.dnn.blobFromImage(image, scalefactor=1/255.0, size=(416, 416), swapRB=True, crop=False)
    model.setInput(blob)
    outputs = model.forward()
    
    detected_values = []
    for output in outputs:
        for detection in output:
            scores = detection[5:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]
            if confidence > 0.5:
                detected_values.append(int(detection[0]))
    return max(detected_values, default=None)

@bot.message_handler(commands=['start'])
def start(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    button = KeyboardButton("Отправить номер телефона", request_contact=True)
    markup.add(button)
    bot.send_message(message.chat.id, "Отправьте ваш номер телефона для авторизации.", reply_markup=markup)

@bot.message_handler(content_types=['contact'])
def contact_handler(message):
    phone = message.contact.phone_number
    user_data[message.chat.id] = {"phone": phone, "counters": get_counters(phone)}
    ask_for_counter_data(message.chat.id)

def ask_for_counter_data(chat_id):
    user_info = user_data.get(chat_id, {})
    counters = user_info.get("counters", [])
    
    if counters:
        counter = counters.pop(0)
        user_info["current_counter"] = counter
        bot.send_message(chat_id, f"Пришлите фото счетчика {counter['device_number'] or 'без номера'} или введите показания вручную:")
    else:
        bot.send_message(chat_id, "Все показания переданы. Спасибо!")
        user_data.pop(chat_id, None)

@bot.message_handler(content_types=['photo'])
def photo_handler(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id)
    file_path = file_info.file_path
    downloaded_file = bot.download_file(file_path)
    photo_path = f"{chat_id}.jpg"
    with open(photo_path, 'wb') as new_file:
        new_file.write(downloaded_file)
    
    meter_value = recognize_meter_value(photo_path)
    if meter_value is not None:
        bot.send_message(chat_id, f"Распознанное значение: {meter_value}. Подтвердите или введите вручную.")
    else:
        bot.send_message(chat_id, "Не удалось распознать показания. Введите их вручную.")

@bot.message_handler(func=lambda message: message.chat.id in user_data and "current_counter" in user_data[message.chat.id])
def counter_handler(message):
    chat_id = message.chat.id
    user_info = user_data[chat_id]
    
    counter = user_info["current_counter"]
    param = message.text
    
    counter_data = {
        "ls_number": user_info["phone"],
        "date": "2024.10.30",
        "Counters": [{
            "factory_number": counter["device_number"],
            "param": param,
            "photo_link": ""
        }]
    }
    
    response = requests.post(API_URL_SEND_PARAMS, json=[counter_data])
    
    if response.status_code == 200 and response.json().get("result") == "success":
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton("Отправить показания ещё одного счётчика"))
        markup.add(KeyboardButton("Завершить передачу показаний"))
        bot.send_message(chat_id, "Показания успешно отправлены. Хотите отправить ещё?", reply_markup=markup)
    else:
        bot.send_message(chat_id, "Ошибка при отправке показаний. Попробуйте снова.")
    
    del user_info["current_counter"]

@bot.message_handler(func=lambda message: message.text == "Отправить показания ещё одного счётчика")
def another_counter(message):
    ask_for_counter_data(message.chat.id)

@bot.message_handler(func=lambda message: message.text == "Завершить передачу показаний")
def finish_submission(message):
    bot.send_message(message.chat.id, "Спасибо! Показания успешно переданы.")
    user_data.pop(message.chat.id, None)

bot.polling(none_stop=True)
