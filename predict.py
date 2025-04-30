import os
import uuid
import shutil
from typing import Optional, Union
from roboflow import Roboflow

# 1) Инициализация Roboflow
API_KEY   = 'WJjDz5ju5Mxb3ZlkNMMw'  # или задайте явно
PROJECT   = "combined_ad_v2"
VERSION   = 4
CONF_THRESHOLD = 0.40  # в процентах

rf   = Roboflow(api_key=API_KEY)
model = rf.workspace().project(PROJECT).version(VERSION).model

UPLOAD_FOLDER = 'uploads'

# def extract_value_from_roboflow(image_path: str) -> Optional[str]:
def extract_value_from_roboflow(
    image_path: Union[str, "FileStorage"], 
    phone: Union[str, int]
) -> Optional[str]:
    """
    1) Отправляем всё изображение в Roboflow.
    2) Фильтруем предсказания: оставляем только цифры (class != 'frame') 
       и с confidence >= CONF_THRESHOLD (%).
    3) Сортируем по центру bbox.x слева→направо и объединяем в строку.
    4) Сохраняем исходный файл в уникальную папку результатов.
    """
    # 1) Предсказание
    response = model.predict(
        image_path,
        confidence=CONF_THRESHOLD,
        overlap=30
    ).json()

    # 2) Фильтрация цифр
    digits = [
        p for p in response["predictions"]
        if p["class"] != "frame" and p["confidence"] >= CONF_THRESHOLD
    ]
    if not digits:
        return None

    # 3) Сортировка и сборка строки
    digits.sort(key=lambda p: p["x"])
    recognized_value = "".join(p["class"] for p in digits)

    # 4) Сохранение исходного изображения
    result_id          = f"{phone}_{uuid.uuid4()}"
    result_folder_path = os.path.join(UPLOAD_FOLDER, result_id)
    os.makedirs(result_folder_path, exist_ok=True)
    result_image_path  = os.path.join(result_folder_path, "result.jpg")

    # Если это объект с .save(), используем его, иначе копируем файл
    if hasattr(image_path, "save"):
        image_path.save(result_image_path)
    else:
        shutil.copy(image_path, result_image_path)

    return recognized_value