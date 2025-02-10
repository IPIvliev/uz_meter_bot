import cv2
import numpy as np
from ultralytics import YOLO

# Предположим, что модели загружены глобально:
frame_model = YOLO("meter_model.pt")   # Модель для поиска рамки с цифрами
digit_model = YOLO("digit_model.pt")     # Модель для распознавания цифр в рамке

def correct_rotation(image):
    """
    Корректирует поворот изображения, выравнивая его по длинной стороне.
    
    Алгоритм:
      1. Преобразует изображение в оттенки серого и применяет размытие для уменьшения шума.
      2. Применяет бинаризацию (Otsu) и находит внешние контуры.
      3. Выбирает самый большой контур и вычисляет минимальный поворачиваемый прямоугольник.
      4. Определяет угол поворота. Если ширина прямоугольника меньше высоты, добавляет 90°,
         чтобы длинная сторона стала горизонтальной.
      5. Поворачивает изображение вокруг его центра на найденный угол.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    ret, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image  # Если контуры не найдены, возвращаем исходное изображение
    
    # Находим наибольший контур по площади
    largest_contour = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(largest_contour)  # rect = ((center_x, center_y), (width, height), angle)
    angle = rect[2]
    (w, h) = rect[1]
    # Если ширина меньше высоты, корректируем угол для поворота так, чтобы длинная сторона была горизонтальной
    if w < h:
        angle = angle + 90

    (h_img, w_img) = image.shape[:2]
    center = (w_img // 2, h_img // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(image, M, (w_img, h_img), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated

def extract_value_from_yolo(image_path):
    """
    Использует две модели:
      1. frame_model обнаруживает рамку с цифрами на исходном изображении.
      2. digit_model распознает отдельные цифры в выровненном изображении рамки.

    Алгоритм:
      - Вызывается frame_model для поиска рамки.
      - Из результата извлекается bounding box рамки (координаты x1, y1, x2, y2).
      - С исходного изображения (через cv2) вырезается область рамки.
      - Функция correct_rotation() корректирует поворот обрезанного изображения.
      - Выровненное изображение передаётся в digit_model для распознавания цифр.
      - Для каждой найденной цифры извлекается её x-координата, класс (число) и уровень уверенности.
      - Цифры сортируются по x-координате (слева направо) и объединяются в итоговую строку.
    """

    # Шаг 1. Поиск рамки с цифрами на исходном изображении
    frame_results = frame_model(image_path)
    if not frame_results or not hasattr(frame_results[0], "boxes") or frame_results[0].boxes is None or len(frame_results[0].boxes) == 0:
        return None  # Рамка не найдена

    # Берем первый обнаруженный бокс (при необходимости можно выбрать с наивысшей уверенностью)
    frame_box = frame_results[0].boxes[0]
    coords = frame_box.xyxy.cpu().numpy()[0]  # [x1, y1, x2, y2]
    x1, y1, x2, y2 = map(int, coords[:4])
    
    # Загружаем изображение и обрезаем рамку
    image = cv2.imread(image_path)
    if image is None:
        return None
    cropped_frame = image[y1:y2, x1:x2]

    # Шаг 2. Выравнивание рамки с цифрами
    corrected_frame = correct_rotation(cropped_frame)
    
    # Шаг 3. Распознавание цифр в выровненном изображении рамки
    digit_results = digit_model(corrected_frame)
    if not digit_results or not hasattr(digit_results[0], "boxes") or digit_results[0].boxes is None or len(digit_results[0].boxes) == 0:
        return None  # Цифры не обнаружены

    digit_boxes = digit_results[0].boxes
    digit_predictions = []
    for box in digit_boxes:
        coords_digit = box.xyxy.cpu().numpy()[0]
        x1_digit = coords_digit[0]
        cls_id = int(box.cls.cpu().numpy()[0])
        digit = str(cls_id)
        conf = box.conf.cpu().numpy()[0]
        if conf < 0.5:
            continue
        digit_predictions.append((x1_digit, digit))
    
    if not digit_predictions:
        return None

    # Сортируем обнаруженные цифры по x-координате (слева направо)
    digit_predictions.sort(key=lambda item: item[0])
    recognized_value = "".join([digit for _, digit in digit_predictions])
    return recognized_value