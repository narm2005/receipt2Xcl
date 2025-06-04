from PIL import Image
import pytesseract
from langdetect import detect
import easyocr
import os

os.environ['TESSDATA_PREFIX'] = '/usr/local/Cellar/tesseract/5.5.0_1/share/tessdata/'

# Optional: Map detected language codes to Tesseract-compatible ones
LANG_CODE_MAP = {
    'en': 'eng',
    'es': 'spa',
    'fr': 'fra',
    'de': 'deu',
    'it': 'ita',
    'pt': 'por',
    'ja': 'jpn',
    'zh-cn': 'chi_sim',
    'zh-tw': 'chi_tra'
}

def detect_language(text):
    try:
        lang = detect(text)
        return LANG_CODE_MAP.get(lang, 'eng')  # default to English if not mapped
    except Exception:
        return 'eng'

def ocr_image_multilang(image_path: str, lang: str = None, auto_detect: bool = False) -> str:
    """
    Perform OCR on an image using Tesseract with optional language support.

    :param image_path: Path to the image file.
    :param lang: Specific language code to use (Tesseract format, e.g., 'eng', 'spa').
    :param auto_detect: If True, will auto-detect language from partial OCR result.
    :return: Extracted text from the image.
    """
    if auto_detect:
        # Initial scan in English (or default) to detect language
        initial_text = pytesseract.image_to_string(Image.open(image_path), lang='eng')
        lang = detect_language(initial_text)

    # Fall back to English if language not provided
    lang = lang or 'eng'

    # Final OCR pass with detected or specified language
    text = pytesseract.image_to_string(Image.open(image_path), lang=lang)
    print("TEXT:",text)
    return text


def easyocr_image_multilang(image_path: str, lang: str = None, auto_detect: bool = False) -> str:
    """
    Perform OCR on an image using Tesseract with optional language support.

    :param image_path: Path to the image file.
    :param lang: Specific language code to use (Tesseract format, e.g., 'eng', 'spa').
    :param auto_detect: If True, will auto-detect language from partial OCR result.
    :return: Extracted text from the image.
    """
        # Initial scan in English (or default) to detect language
    reader = easyocr.Reader(['ch_tra', 'en'])

    with open(image_path, "rb") as f:
        img = f.read()
    text = reader.readtext(img)

    # Final OCR pass with detected or specified language
    print("TEXT:", text)
    return text


