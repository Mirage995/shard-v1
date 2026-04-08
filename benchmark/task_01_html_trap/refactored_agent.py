from typing import List, Dict, Optional
from decimal import Decimal, ROUND_HALF_UP

# ── Sample data (the benchmark fixture) ──────────────────────────────────────

SAMPLE_MENU = {
    "restaurant": {
        "name": "Pizzeria Da Mario",
        "since": 1996,
        "city": "Zevio",
        "motto": "La tradizione nel piatto",
    },
    "categories": [
        {
            "name": "Pizze Classiche",
            "items": [
                {"name": "Margherita", "price": 7.50, "rating": 4.8,
                 "is_special": False, "allergens": ["glutine", "lattosio"]},
                {"name": "Diavola", "price": 9.00, "rating": 4.5,
                 "is_special": True, "allergens": ["glutine", "lattosio"]},
                {"name": "Quattro Formaggi", "price": 10.00, "rating": 4.9,
                 "is_special": False, "allergens": ["glutine", "lattosio", "uova"]},
            ],
        },
        {
            "name": "Primi Piatti",
            "items": [
                {"name": "Spaghetti allo Scoglio", "price": 14.00, "rating": 4.7,
                 "is_special": True, "allergens": ["glutine", "crostacei"]},
                {"name": "Risotto ai Funghi", "price": 12.00, "rating": 4.3,
                 "is_special": False, "allergens": ["glutine"]},
            ],
        },
        {
            "name": "Dolci",
            "items": [
                {"name": "Tiramisu", "price": 6.00, "rating": 4.9,
                 "is_special": False, "allergens": ["glutine", "lattosio", "uova"]},
                {"name": "Panna Cotta", "price": 5.50, "rating": 4.6,
                 "is_special": True, "allergens": ["lattosio"]},
            ],
        },
    ],
    "daily_special": {
        "dish": "Frittura Mista di Pesce",
        "original_price": 18.00,
        "discount_pct": 20,
    },
    "promo_code": "MARIO2024",
}

# ── Constants ───────────────────────────────────────────────────────────────

STAR_THRESHOLD = 4.7
MAX_ALLERGENS_SHOWN = 2

# ── Business Logic Layer ────────────────────────────────────────────────────

def calculate_discounted_price(price: float, discount_pct: Optional[float]) -> float:
    if discount_pct is not None:
        return round(price * (1 - discount_pct / 100), 2)
    return price

def truncate_allergens(allergens: List[str]) -> str:
    if len(allergens) > MAX_ALLERGENS_SHOWN:
        return ", ".join(allergens[:MAX_ALLERGENS_SHOWN]) + f" +{len(allergens) - MAX_ALLERGENS_SHOWN}"
    return ", ".join(allergens)

def calculate_average_rating(items: List[Dict]) -> float:
    return sum(item["rating"] for item in items) / len(items)

def get_star_dishes(cats: List[Dict]) -> List[str]:
    star_names = []
    for cat in cats:
        for item in cat["items"]:
            if item["rating"] >= STAR_THRESHOLD:
                star_names.append(item["name"])
    return star_names

# ── Rendering Layer ──────────────────────────────────────────────────────────

def render_css() -> str:
    return (
        "<style>\n"
        "body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; color: #2d3748; }\n"
        ".page-header { text-align: center; padding: 30px 0; border-bottom: 3px solid #e53e3e; margin-bottom: 30px; }\n"
        ".page-header h1 { font-size: 2.4em; color: #c53030; margin: 0; }\n"
        ".page-header .subtitle { color: #718096; font-size: 1.1em; margin-top: 8px; }\n"
        ".page-header .motto { font-style: italic; color: #a0aec0; margin-top: 4px; }\n"
        ".category-card { background: white; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
        ".category-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 2px solid #fed7d7; padding-bottom: 12px; }\n"
        ".category-header h2 { margin: 0; color: #c53030; }\n"
        ".avg-badge { background: #fff5f5; color: #c53030; padding: 4px 12px; border-radius: 20px; font-weight: bold; }\n"
        ".menu-item { padding: 12px 0; border-bottom: 1px solid #edf2f7; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }\n"
        ".menu-item:last-child { border-bottom: none; }\n"
        ".item-name { font-weight: 600; font-size: 1.1em; flex: 1; }\n"
        ".star-badge { background: #fefcbf; color: #975a16; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; margin-left: 8px; }\n"
        ".item-price { font-weight: bold; color: #2d3748; }\n"
        ".original-price { text-decoration: line-through; color: #a0aec0; margin-right: 8px; }\n"
        ".discount-price { color: #e53e3e; font-size: 1.15em; }\n"
        ".allergens { font-size: 0.85em; color: #a0aec0; width: 100%; }\n"
        ".ai-image { margin-top: 8px; width: 100%; }\n"
        ".ai-image img { max-width: 300px; border-radius: 8px; }\n"
        ".ai-image .img-caption { font-size: 0.8em; color: #a0aec0; font-style: italic; }\n"
        ".special-banner { background: linear-gradient(135deg, #fff5f5 0%, #fed7d7 100%); border-radius: 12px; padding: 24px; margin-bottom: 24px; text-align: center; border: 2px solid #feb2b2; }\n"
        ".special-title { font-size: 0.9em; text-transform: uppercase; letter-spacing: 2px; color: #c53030; margin-bottom: 8px; }\n"
        ".special-dish { font-size: 1.6em; font-weight: bold; color: #2d3748; margin-bottom: 12px; }\n"
        ".special-pricing { font-size: 1.2em; margin-bottom: 12px; }\n"
        ".savings { color: #38a169; font-weight: bold; }\n"
        ".promo-code { background: #c53030; color: white; display: inline-block; padding: 8px 20px; border-radius: 8px; font-weight: bold; letter-spacing: 1px; }\n"
        ".stats-footer { display: flex; justify-content: space-around; background: white; border-radius: 12px; padding: 24px; margin-top: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
        ".stat-item { text-align: center; }\n"
        ".stat-value { display: block; font-size: 1.8em; font-weight: bold; color: #c53030; }\n"
        ".stat-label { font-size: 0.85em; color: #718096; }\n"
        "</style>\n"
    )

def render_header(restaurant: Dict) -> str:
    return (
        "<div class=\"page-header\">\n"
        f"<h1>{restaurant['name']}</h1>\n"
        f"<div class=\"subtitle\">Dal {restaurant['since']} a {restaurant['city']}</div>\n"
        f"<div class=\"motto\">\"{restaurant['motto']}\"</div>\n"
        "</div>\n"
    )

def render_menu_item(item: Dict, special: Optional[Dict], enable_images: bool) -> str:
    price = item["price"]
    if item["is_special"] and special:
        price = calculate_discounted_price(item["price"], special.get("discount_pct"))
    
    allergens_display = truncate_allergens(item.get("allergens", []))
    star_html = " <span class=\"star-badge\">\u2605 Star Dish</span>" if item["rating"] >= STAR_THRESHOLD else ""
    
    item_html = (
        "<div class=\"menu-item\">\n"
        f"<div class=\"item-name\">{item['name']}{star_html}</div>\n"
    )
    
    if item["is_special"]:
        item_html += (
            "<div class=\"item-price\">"
            f"<span class=\"original-price\">\u20ac{item['price']:.2f}</span>"
            f" <span class=\"discount-price\">\u20ac{price:.2f}</span>"
            "</div>\n"
        )
    else:
        item_html += f"<div class=\"item-price\">\u20ac{price:.2f}</div>\n"

    item_html += f"<div class=\"allergens\">Allergeni: {allergens_display}</div>\n"

    if enable_images and item["rating"] >= STAR_THRESHOLD:
        img_slug = item["name"].lower().replace(" ", "_")
        img_prompt = f"Hyper-realistic photo of {item['name']}, Italian restaurant, warm natural lighting, appetizing"
        item_html += (
            f"<div class=\"ai-image\" data-prompt=\"{img_prompt}\">\n"
            f"<img src=\"placeholder_{img_slug}.jpg\">\n"
            "<p class=\"img-caption\">Ispirazione visiva AI</p>\n"
            "</div>\n"
        )

    item_html += "</div>\n"  # close menu-item
    return item_html

def render_category(category: Dict, special: Optional[Dict], enable_images: bool) -> str:
    items = sorted(category["items"], key=lambda x: x["rating"], reverse=True)
    avg_rating = calculate_average_rating(items)
    
    category_html = (
        "<div class=\"category-card\">\n"
        "<div class=\"category-header\">\n"
        f"<h2>{category['name']}</h2>\n"
        f"<span class=\"avg-badge\">{avg_rating:.1f}</span>\n"
        "</div>\n"
    )
    
    for item in items:
        category_html += render_menu_item(item, special, enable_images)

    category_html += "</div>\n"  # close category-card
    return category_html

def render_daily_special(special: Dict, promo: str) -> str:
    disc_price = calculate_discounted_price(special["original_price"], special["discount_pct"])
    savings = round(special["original_price"] - disc_price, 2)

    special_html = (
        "<div class=\"special-banner\">\n"
        "<div class=\"special-title\">Piatto del Giorno</div>\n"
        f"<div class=\"special-dish\">{special['dish']}</div>\n"
        "<div class=\"special-pricing\">\n"
        f"<span class=\"original-price\">\u20ac{special['original_price']:.2f}</span>\n"
        f"<span class=\"discount-price\">\u20ac{disc_price:.2f}</span>\n"
        f"<span class=\"savings\">Risparmi \u20ac{savings:.2f}!</span>\n"
        "</div>\n"
    )
    
    if promo:
        special_html += f"<div class=\"promo-code\">Usa il codice: <strong>{promo}</strong></div>\n"
    
    special_html += "</div>\n"
    return special_html

def render_stats_footer(total_items: int, total_stars: int, overall_avg: float, star_names: List[str]) -> str:
    return (
        "<div class=\"stats-footer\">\n"
        f"<div class=\"stat-item\"><span class=\"stat-value\">{total_items}</span>\n"
        "<span class=\"stat-label\">Piatti</span></div>\n"
        f"<div class=\"stat-item\"><span class=\"stat-value\">{total_stars}</span>\n"
        "<span class=\"stat-label\">Star Dishes</span></div>\n"
        f"<div class=\"stat-item\"><span class=\"stat-value\">{overall_avg:.1f}</span>\n"
        "<span class=\"stat-label\">Media</span></div>\n"
        f"<div class=\"stat-item\"><span class=\"stat-value\">{', '.join(star_names)}</span>\n"
        "<span class=\"stat-label\">I Nostri Migliori</span></div>\n"
        "</div>\n"
    )

# ── Orchestrator ─────────────────────────────────────────────────────────────

def generate_restaurant_page(menu_data: Dict) -> str:
    restaurant = menu_data["restaurant"]
    categories = menu_data["categories"]
    special = menu_data.get("daily_special")
    promo = menu_data.get("promo_code", "")
    
    html = "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
    html += f"<title>{restaurant['name']} — Menu</title>\n"
    html += render_css()
    html += "</head>\n<body>\n"
    html += render_header(restaurant)

    total_items = 0
    total_stars = 0
    all_ratings = []

    for category in categories:
        category_html = render_category(category, special, True)
        html += category_html
        total_items += len(category["items"])
        all_ratings.extend(item["rating"] for item in category["items"])
        total_stars += sum(1 for item in category["items"] if item["rating"] >= STAR_THRESHOLD)

    if special:
        html += render_daily_special(special, promo)

    overall_avg = sum(all_ratings) / len(all_ratings) if all_ratings else 0
    star_names = get_star_dishes(categories)
    html += render_stats_footer(total_items, total_stars, overall_avg, star_names)

    html += "</body>\n</html>\n"
    return html

# ── Direct execution (for manual testing) ────────────────────────────────────
if __name__ == "__main__":
    output = generate_restaurant_page(SAMPLE_MENU)
    with open("output_refactored.html", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Generated {len(output)} chars -> output_refactored.html")