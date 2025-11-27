"""
Автоматическая сборка базы знаний из PDF файлов.

Процесс:
1. Извлечение изображений из PDF и привязка к рисункам
2. Создание структурированных txt файлов
3. Построение индекса полнотекстового поиска из структурированных txt

Инструкции по запуску (Windows, PowerShell):

1) Активируйте виртуальное окружение Python 3.11:
   .\.venv\Scripts\Activate.ps1

2) Запустите построение базы знаний:
   python -m src.build_kb

PDF-файлы кладите в: src/knowledge/data/
Изображения сохраняются в: src/knowledge/data/images/
Структурированные тексты (временные, генерируются автоматически): src/knowledge/data/structured/
База данных полнотекстового поиска: knowledge.db
"""

import asyncio
import os
import sys
import json
import re
import io
import logging
from pypdf import PdfReader
from PIL import Image
from dotenv import load_dotenv

try:
    from .knowledge import search_store
    from .knowledge.text_search import DATA_DIR
    from .process_pdf import extract_and_structure_pdf
    from .knowledge.cleanup import (
        clean_structured_texts,
        clean_figure_mapping_titles,
        normalize_figure_refs,
        apply_safe_word_fixes,
    )
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from knowledge import search_store  # type: ignore
    from knowledge.text_search import DATA_DIR  # type: ignore
    from process_pdf import extract_and_structure_pdf  # type: ignore
    from knowledge.cleanup import (  # type: ignore
        clean_structured_texts,
        clean_figure_mapping_titles,
        normalize_figure_refs,
        apply_safe_word_fixes,
    )


IMAGES_DIR = os.path.join(DATA_DIR, "images")
STRUCTURED_DIR = os.path.join(DATA_DIR, "structured")
MAPPING_FILE = os.path.join(IMAGES_DIR, "figure_mapping.json")
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(STRUCTURED_DIR, exist_ok=True)


def convert_existing_png_to_jpg() -> None:
    """Конвертирует все существующие PNG изображения в JPG."""
    if not os.path.exists(IMAGES_DIR):
        return
    
    png_files = [f for f in os.listdir(IMAGES_DIR) if f.lower().endswith(".png")]
    
    if not png_files:
        return
    
    print(f"  Конвертация PNG в JPG: найдено {len(png_files)} файлов")
    
    for png_file in png_files:
        png_path = os.path.join(IMAGES_DIR, png_file)
        jpg_file = png_file.replace(".png", ".jpg")
        jpg_path = os.path.join(IMAGES_DIR, jpg_file)
        
        # Если JPG уже существует, пропускаем
        if os.path.exists(jpg_path):
            try:
                os.remove(png_path)
                continue
            except:
                pass
        
        try:
            img = Image.open(png_path)
            
            # Конвертируем в RGB если нужно
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Сохраняем как JPG
            img.save(jpg_path, 'JPEG', quality=95)
            
            # Удаляем PNG
            os.remove(png_path)
            
            # Обновляем маппинг, если есть
            if os.path.exists(MAPPING_FILE):
                try:
                    with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                        mapping = json.load(f)
                    
                    updated = False
                    for fig_key, fig_info in mapping.items():
                        if isinstance(fig_info, dict) and fig_info.get("image") == png_file:
                            fig_info["image"] = jpg_file
                            fig_info["path"] = fig_info["path"].replace(".png", ".jpg")
                            updated = True
                    
                    if updated:
                        with open(MAPPING_FILE, "w", encoding="utf-8") as f:
                            json.dump(mapping, f, ensure_ascii=False, indent=2)
                except:
                    pass
        except Exception as e:
            logging.warning(f"    Ошибка конвертации {png_file}: {e}")


def extract_images_from_pdfs() -> dict:
    """Шаг 1: Извлекает изображения из всех PDF и связывает с рисунками."""
    print("\n=== Шаг 1: Извлечение изображений из PDF ===")
    
    mapping = {}
    pdf_files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]
    
    if not pdf_files:
        print("PDF файлы не найдены")
        return mapping
    
    print(f"Найдено PDF файлов: {len(pdf_files)}")
    
    for pdf_filename in sorted(pdf_files):
        print(f"  Обработка: {pdf_filename}")
        pdf_path = os.path.join(DATA_DIR, pdf_filename)
        
        if not os.path.exists(pdf_path):
            continue
        
        reader = PdfReader(pdf_path)
        base_name = pdf_filename.replace(".pdf", "").replace(" ", "_")
        
        # Извлекаем текст по страницам для поиска номеров рисунков
        page_texts = {}
        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = page.extract_text()
                page_texts[page_num] = page_text
            except:
                pass
        
        # Ищем номера рисунков и их заголовки
        figures_on_pages = {}
        figures_titles = {}
        for page_num, text in page_texts.items():
            # Ищем паттерны типа "Текст Рис.1.1.1" или "# Заголовок: Рис.1.1.1"
            # Ищем все упоминания Рис.X.X.X и текст перед ними
            # Допускаем пробелы: «Рис. 1.2. 3» тоже считаем валидным
            figure_pattern = r'Рис\.?\s*([0-9\s\.]{3,})'
            matches = list(re.finditer(figure_pattern, text or ""))
            
            for match in matches:
                raw_num = match.group(1)
                normalized_num = re.sub(r"\s*\.\s*", ".", raw_num.strip())
                fig_key = f"Рис.{normalized_num}"
                
                if fig_key not in figures_on_pages:
                    figures_on_pages[fig_key] = page_num
                    
                    # Извлекаем заголовок - текст перед номером рисунка
                    # Ищем строку, в которой находится рисунок
                    line_start = text.rfind('\n', 0, match.start()) + 1
                    line_end = text.find('\n', match.start())
                    if line_end == -1:
                        line_end = len(text)
                    line_text = text[line_start:line_end].strip()
                    
                    # Убираем сам номер рисунка и всё после него
                    line_text = line_text[:match.start() - line_start].strip()
                    
                    # Убираем лишние символы
                    line_text = re.sub(r'[#:]+', ' ', line_text)
                    line_text = re.sub(r'\s+', ' ', line_text).strip()
                    
                    # Берем последние 2-4 слова как заголовок (если есть)
                    words = line_text.split()
                    if words:
                        # Берем последние слова, но не более 4
                        title = " ".join(words[-4:]) if len(words) > 4 else " ".join(words)
                        title = title.strip()
                        # Убираем слишком длинные или неинформативные заголовки
                        if title and 3 < len(title) < 60 and not title.startswith('#'):
                            # Нормализуем заголовок (безопасные фиксы слов и фигур)
                            title_clean = apply_safe_word_fixes(normalize_figure_refs(title))
                            figures_titles[fig_key] = title_clean
        
        # Извлекаем изображения
        images_on_pages = {}
        for page_num, page in enumerate(reader.pages, 1):
            try:
                if "/XObject" in page.get("/Resources", {}):
                    xobjects = page["/Resources"]["/XObject"].get_object()
                    
                    for obj_name, obj in xobjects.items():
                        if obj.get("/Subtype") == "/Image":
                            try:
                                data = obj.get_data()
                                width = obj.get("/Width", 0)
                                height = obj.get("/Height", 0)
                                color_space = obj.get("/ColorSpace", "")
                                
                                # Пробуем открыть как изображение через PIL
                                img = None
                                try:
                                    img = Image.open(io.BytesIO(data))
                                except:
                                    try:
                                        if "/DeviceRGB" in str(color_space) or "/RGB" in str(color_space):
                                            mode = "RGB"
                                        elif "/DeviceGray" in str(color_space) or "/Gray" in str(color_space):
                                            mode = "L"
                                        else:
                                            mode = "RGB"
                                        
                                        if width > 0 and height > 0:
                                            img = Image.frombytes(mode, (width, height), data)
                                    except:
                                        pass
                                
                                if img is None:
                                    continue
                                
                                # Конвертируем в RGB если нужно
                                if img.mode in ('RGBA', 'LA', 'P'):
                                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                                    if img.mode == 'P':
                                        img = img.convert('RGBA')
                                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                                    img = rgb_img
                                elif img.mode != 'RGB':
                                    img = img.convert('RGB')
                                
                                # Сохраняем как JPG
                                safe_obj_name = obj_name.replace("/", "_").replace("\\", "_")
                                img_filename = f"{base_name}_page{page_num}_{safe_obj_name}.jpg"
                                img_path = os.path.join(IMAGES_DIR, img_filename)
                                
                                img.save(img_path, 'JPEG', quality=95)
                                
                                if page_num not in images_on_pages:
                                    images_on_pages[page_num] = []
                                images_on_pages[page_num].append({
                                    "filename": img_filename,
                                    "path": img_path
                                })
                            except Exception as e:
                                logging.warning(f"    Ошибка извлечения изображения: {e}")
            except:
                pass
        
        # Связываем рисунки с изображениями
        for fig_key, fig_page in figures_on_pages.items():
            if fig_page in images_on_pages and images_on_pages[fig_page]:
                img_info = images_on_pages[fig_page][0]
                fig_data = {
                    "page": fig_page,
                    "image": img_info["filename"],
                    "path": img_info["path"],
                    "source": pdf_filename
                }
                # Добавляем заголовок, если найден
                if fig_key in figures_titles:
                    fig_data["title"] = figures_titles[fig_key]
                
                mapping[fig_key] = fig_data
                title_info = f" ({figures_titles.get(fig_key, '')})" if fig_key in figures_titles else ""
                print(f"    {fig_key}{title_info} -> {img_info['filename']}")
    
    # Сохраняем маппинг
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    
    print(f"Извлечено рисунков: {len(mapping)}")
    return mapping


def create_structured_texts() -> None:
    """Шаг 2: Создает структурированные txt файлы из PDF."""
    print("\n=== Шаг 2: Создание структурированных текстов ===")
    
    pdf_files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf")]
    
    if not pdf_files:
        print("PDF файлы не найдены")
        return
    
    print(f"Обработка PDF файлов: {len(pdf_files)}")
    
    for pdf_file in sorted(pdf_files):
        try:
            print(f"  Обработка: {pdf_file}")
            structured_text = extract_and_structure_pdf(pdf_file)
            
            output_filename = pdf_file.replace(".pdf", "_structured.txt")
            output_path = os.path.join(STRUCTURED_DIR, output_filename)
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(structured_text)
            
            print(f"    Сохранен: {output_filename}")
        except Exception as e:
            print(f"    Ошибка при обработке {pdf_file}: {e}")


def build_text_index() -> None:
    """Шаг 3: Строит индекс полнотекстового поиска из структурированных txt файлов."""
    print("\n=== Шаг 3: Построение индекса полнотекстового поиска ===")
    search_store.build_index()
    print("Индекс полнотекстового поиска построен успешно")


def cleanup_generated_artifacts() -> None:
    """Шаг 2.5: Автоочистка текстов и заголовков после генерации.

    - Нормализует *_structured.txt
    - Нормализует title в figure_mapping.json
    """
    print("\n=== Шаг 2.5: Очистка и нормализация артефактов ===")
    clean_structured_texts(STRUCTURED_DIR)
    clean_figure_mapping_titles(MAPPING_FILE)


async def main() -> None:
    """Основная функция: выполняет все шаги автоматически."""
    load_dotenv()
    
    print("=" * 60)
    print("Автоматическая сборка базы знаний")
    print("=" * 60)
    
    # Шаг 0: Конвертация существующих PNG в JPG
    print("\n=== Шаг 0: Конвертация PNG в JPG ===")
    convert_existing_png_to_jpg()
    
    # Шаг 1: Извлечение изображений
    extract_images_from_pdfs()
    
    # Шаг 2: Создание структурированных текстов
    create_structured_texts()
    
    # Шаг 2.5: Очистка после генерации
    cleanup_generated_artifacts()
    
    # Шаг 3: Построение индекса полнотекстового поиска
    build_text_index()
    
    print("\n" + "=" * 60)
    print("Готово! Все шаги выполнены успешно.")
    print(f"База данных полнотекстового поиска: knowledge.db")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
