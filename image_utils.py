"""
image_utils.py — утилиты для работы с картинками (наложение слоёв)
Все картинки имеют размер 1000x1000 пиксель
"""

from PIL import Image
from pathlib import Path
import io

IMAGES_DIR = Path("Images")

# Коэффициент оптимизации для Telegram (уменьшаем до 512x512)
COMPRESS_SCALE = 512 / 1000


def composite_cat_image(
    state_icons: list = None,
    action_layer: str = None,
    accessory: str = None,
) -> io.BytesIO:
    """
    Создаёт композитное изображение кота.
    
    Args:
        state_icons: список иконок состояния ('energy', 'mood', 'satiety')
        action_layer: слой действия ('food', 'game')
        accessory: аксессуар ('finance', 'gaming', 'weather')
    
    Returns:
        BytesIO с готовым PNG
    """
    
    # Загружаем базовое изображение кота
    cat_img = Image.open(IMAGES_DIR / "Cat.png").convert("RGBA")
    
    # Наложение слоя действия (сверху)
    if action_layer:
        action_map = {
            "food": IMAGES_DIR / "Food.png",
            "game": IMAGES_DIR / "Game.png",
            "sleep": IMAGES_DIR / "CatLowEnergy.png",
        }
        if action_layer in action_map:
            action_img = Image.open(action_map[action_layer]).convert("RGBA")
            cat_img = Image.alpha_composite(cat_img, action_img)

    # Наложение аксессуара
    if accessory:
        accessory_map = {
            "finance": IMAGES_DIR / "AcsFinance.png",
            "gaming": IMAGES_DIR / "AcsGaming.png",
            "weather": IMAGES_DIR / "AcsWeather.png",
        }
        if accessory in accessory_map:
            acc_img = Image.open(accessory_map[accessory]).convert("RGBA")
            cat_img = Image.alpha_composite(cat_img, acc_img)
    
    # Наложение иконок состояния
    if state_icons:
        icon_map = {
            "energy": IMAGES_DIR / "EnergyIcon.png",
            "mood": IMAGES_DIR / "MoodIcon.png",
            "satiety": IMAGES_DIR / "SatietyIcon.png",
        }
        for icon_key in state_icons:
            if icon_key in icon_map:
                icon_img = Image.open(icon_map[icon_key]).convert("RGBA")
                cat_img = Image.alpha_composite(cat_img, icon_img)
    
    # Оптимизация размера для Telegram
    new_size = (COMPRESS_SCALE * cat_img.width, COMPRESS_SCALE * cat_img.height)
    cat_img.thumbnail((512, 512), Image.Resampling.LANCZOS)
    
    # Сохраняем в BytesIO
    output = io.BytesIO()
    cat_img.save(output, format="PNG", optimize=True)
    output.seek(0)
    
    return output


def get_status_image(
    satiety: int,
    energy: int,
    mood: int,
    pet_inventory: list = None,
) -> io.BytesIO:
    """
    Возвращает картинку кота с соответствующими иконками состояния.
    """
    state_icons = []
    
    if satiety < 30:
        state_icons.append("satiety")
    if energy < 20:
        state_icons.append("energy")
    if mood < 50:
        state_icons.append("mood")
    
    accessory = None
    if pet_inventory and len(pet_inventory) > 0:
        accessory = pet_inventory[0]
    
    return composite_cat_image(state_icons=state_icons, accessory=accessory)


def get_action_image(action: str, pet_inventory: list = None) -> io.BytesIO:
    """
    Возвращает картинку действия (кормление, игра).
    """
    accessory = None
    if pet_inventory and len(pet_inventory) > 0:
        accessory = pet_inventory[0]
    
    return composite_cat_image(action_layer=action, accessory=accessory)


def get_low_stat_image(stat_type: str) -> Path:
    """
    Возвращает предупредительное изображение для низкого статуса.
    """
    stat_map = {
        "satiety": IMAGES_DIR / "CatLowSatiety.png",
        "energy": IMAGES_DIR / "CatLowEnergy.png",
        "mood": IMAGES_DIR / "CatLowMood.png",
    }
    return stat_map.get(stat_type, IMAGES_DIR / "Cat.png")
