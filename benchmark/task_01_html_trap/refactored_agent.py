"""refactored_agent.py — Refactored Restaurant Menu Page Generator."""

import html
from legacy_agent import SAMPLE_MENU

# ── Globals ──────────────────────────────────────────────────────────────
MAX_ALLERGENS_SHOWN = 2
ENABLE_IMAGES = True
STAR_RATING_THRESHOLD = 4.7


# ── Business Logic ───────────────────────────────────────────────────────

def prepare_menu_data(menu_data):
    """Prepare and process menu data for rendering."""
    restaurant = menu_data.get("restaurant", {})
    categories = menu_data.get("categories", [])
    daily_special = menu_data.get("daily_special")
    promo_code = menu_data.get("promo_code", "")

    processed_categories = [
        prepare_category(cat, daily_special) for cat in categories
    ]

    overall_stats = calculate_overall_stats(processed_categories)

    return {
        "restaurant": restaurant,
        "categories": processed_categories,
        "daily_special": daily_special,
        "promo_code": promo_code,
        "overall_stats": overall_stats,
    }


def prepare_category(category, daily_special):
    """Prepare a single category, sorting items and calculating average rating."""
    items = category.get("items", [])
    processed_items = [prepare_menu_item(item, daily_special) for item in items]
    sorted_items = sorted(processed_items, key=lambda x: x["rating"], reverse=True)
    avg_rating = calculate_average_rating(sorted_items)

    return {
        "name": category.get("name", ""),
        "items": sorted_items,
        "avg_rating": avg_rating,
    }


def prepare_menu_item(item, daily_special):
    """Prepare a single menu item, calculating price and truncating allergens."""
    price_info = calculate_price(item, daily_special)
    allergens_display = format_allergens(item.get("allergens", []))
    rating = item.get("rating", 0)
    is_star = rating >= STAR_RATING_THRESHOLD

    return {
        "name": item.get("name", ""),
        "price": item.get("price", 0),
        "rating": rating,
        "is_special": item.get("is_special", False),
        "allergens_display": allergens_display,
        "is_star": is_star,
        "original_price": price_info["original_price"],
        "discount_price": price_info["discount_price"],
    }


def calculate_price(item, daily_special):
    """Calculate the price of a menu item, considering daily specials."""
    original_price = item.get("price", 0)
    discount_price = original_price

    if item.get("is_special") and daily_special:
        discount_pct = daily_special.get("discount_pct", 0)
        discount_price = round(original_price * (1 - discount_pct / 100), 2)

    return {"original_price": original_price, "discount_price": discount_price}


def format_allergens(allergens):
    """Format the allergen list, truncating if necessary."""
    if len(allergens) > MAX_ALLERGENS_SHOWN:
        return ", ".join(allergens[:MAX_ALLERGENS_SHOWN]) + f" +{len(allergens) - MAX_ALLERGENS_SHOWN}"
    else:
        return ", ".join(allergens)


def calculate_average_rating(items):
    """Calculate the average rating for a list of items."""
    if not items:
        return 0

    total_rating = sum(item["rating"] for item in items)
    return total_rating / len(items)


def calculate_overall_stats(categories):
    """Calculate overall statistics for the menu."""
    total_items = 0
    total_stars = 0
    all_ratings = []
    star_names = []

    for cat in categories:
        for item in cat.get("items", []):
            total_items += 1
            rating = item.get("rating")
            if isinstance(rating, (int, float)):
                all_ratings.append(rating)
            if item.get("rating", 0) >= 4.7:
                star_names.append(item.get("name", ""))
                total_stars += 1

    overall_avg = sum(all_ratings) / len(all_ratings) if all_ratings else 0

    return {
        "total_items": total_items,
        "overall_avg": overall_avg,
        "star_names": sorted(star_names, key=lambda x: SAMPLE_MENU["categories"][0]["items"][0]["name"] != x),
        "total_stars": total_stars,
    }


# ── HTML Rendering ─────────────────────────────────────────────────────────

def render_restaurant_page(menu_data):
    """Render the complete HTML page from prepared menu data."""
    restaurant = menu_data.get("restaurant", {})
    categories = menu_data.get("categories", [])
    daily_special = menu_data.get("daily_special")
    promo_code = menu_data.get("promo_code", "")
    overall_stats = menu_data.get("overall_stats", {})

    html_content = render_html_header(restaurant)
    html_content += render_categories(categories, daily_special)
    html_content += render_daily_special(daily_special, promo_code)
    html_content += render_stats_footer(overall_stats)
    html_content += render_html_footer()
    return html_content


def render_html_header(restaurant):
    """Render the HTML header section."""
    name = restaurant.get("name", "")
    since = restaurant.get("since", "")
    city = restaurant.get("city", "")
    motto = restaurant.get("motto", "")

    html_content = "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
    html_content += f"<title>{name} — Menu</title>\n"
    html_content += "<style>\n"
    html_content += "body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; color: #2d3748; }\n"
    html_content += ".page-header { text-align: center; padding: 30px 0; border-bottom: 3px solid #e53e3e; margin-bottom: 30px; }\n"
    html_content += ".page-header h1 { font-size: 2.4em; color: #c53030; margin: 0; }\n"
    html_content += ".page-header .subtitle { color: #718096; font-size: 1.1em; margin-top: 8px; }\n"
    html_content += ".page-header .motto { font-style: italic; color: #a0aec0; margin-top: 4px; }\n"
    html_content += ".category-card { background: white; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
    html_content += ".category-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 2px solid #fed7d7; padding-bottom: 12px; }\n"
    html_content += ".category-header h2 { margin: 0; color: #c53030; }\n"
    html_content += ".avg-badge { background: #fff5f5; color: #c53030; padding: 4px 12px; border-radius: 20px; font-weight: bold; }\n"
    html_content += ".menu-item { padding: 12px 0; border-bottom: 1px solid #edf2f7; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }\n"
    html_content += ".menu-item:last-child { border-bottom: none; }\n"
    html_content += ".item-name { font-weight: 600; font-size: 1.1em; flex: 1; }\n"
    html_content += ".star-badge { background: #fefcbf; color: #975a16; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; margin-left: 8px; }\n"
    html_content += ".item-price { font-weight: bold; color: #2d3748; }\n"
    html_content += ".original-price { text-decoration: line-through; color: #a0aec0; margin-right: 8px; }\n"
    html_content += ".discount-price { color: #e53e3e; font-size: 1.15em; }\n"
    html_content += ".allergens { font-size: 0.85em; color: #a0aec0; width: 100%; }\n"
    html_content += ".ai-image { margin-top: 8px; width: 100%; }\n"
    html_content += ".ai-image img { max-width: 300px; border-radius: 8px; }\n"
    html_content += ".ai-image .img-caption { font-size: 0.8em; color: #a0aec0; font-style: italic; }\n"
    html_content += ".special-banner { background: linear-gradient(135deg, #fff5f5 0%, #fed7d7 100%); border-radius: 12px; padding: 24px; margin-bottom: 24px; text-align: center; border: 2px solid #feb2b2; }\n"
    html_content += ".special-title { font-size: 0.9em; text-transform: uppercase; letter-spacing: 2px; color: #c53030; margin-bottom: 8px; }\n"
    html_content += ".special-dish { font-size: 1.6em; font-weight: bold; color: #2d3748; margin-bottom: 12px; }\n"
    html_content += ".special-pricing { font-size: 1.2em; margin-bottom: 12px; }\n"
    html_content += ".savings { color: #38a169; font-weight: bold; }\n"
    html_content += ".promo-code { background: #c53030; color: white; display: inline-block; padding: 8px 20px; border-radius: 8px; font-weight: bold; letter-spacing: 1px; }\n"
    html_content += ".stats-footer { display: flex; justify-content: space-around; background: white; border-radius: 12px; padding: 24px; margin-top: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
    html_content += ".stat-item { text-align: center; }\n"
    html_content += ".stat-value { display: block; font-size: 1.8em; font-weight: bold; color: #c53030; }\n"
    html_content += ".stat-label { font-size: 0.85em; color: #718096; }\n"
    html_content += "</style>\n</head>\n<body>\n"

    html_content += "<div class=\"page-header\">\n"
    html_content += f"<h1>{name}</h1>\n"
    html_content += f"<div class=\"subtitle\">Dal {since} a {city}</div>\n"
    html_content += f"<div class=\"motto\">\"{motto}\"</div>\n"
    html_content += "</div>\n"
    return html_content


def render_categories(categories, special):
    """Render the categories section."""
    html_content = ""
    for cat in categories:
        name = cat.get("name", "")
        avg_rating = cat.get("avg_rating", 0)
        html_content += "<div class=\"category-card\">\n"
        html_content += "<div class=\"category-header\">\n"
        html_content += f"<h2>{name}</h2>\n"
        html_content += f"<span class=\"avg-badge\">{avg_rating:.1f}</span>\n"
        html_content += "</div>\n"

        for item in cat.get("items", []):
            html_content += render_menu_item(item, special)
        html_content += "</div>\n"
    return html_content


def render_menu_item(item, special):
    """Render a single menu item."""
    name = item.get("name", "")
    is_star = item.get("is_star", False)
    if is_star:
        star_html = " <span class=\"star-badge\">\u2605 Star Dish</span>"
    else:
        star_html = ""

    html_content = "<div class=\"menu-item\">\n"
    html_content += f"<div class=\"item-name\">{name}{star_html}</div>\n"

    if item.get("is_special") and special:
        html_content += "<div class=\"item-price\">"
        html_content += f"<span class=\"original-price\">\u20ac{item['original_price']:.2f}</span>"
        html_content += f" <span class=\"discount-price\">\u20ac{item['discount_price']:.2f}</span>"
        html_content += "</div>\n"
    else:
        html_content += f"<div class=\"item-price\">\u20ac{item['price']:.2f}</div>\n"

    allergens_display = item.get("allergens_display", "")
    html_content += f"<div class=\"allergens\">Allergeni: {allergens_display}</div>\n"

    if ENABLE_IMAGES and is_star:
        item_name = item.get("name", "")
        img_slug = item_name.lower().replace(" ", "_")
        img_prompt = f"Hyper-realistic photo of {item_name}, Italian restaurant, warm natural lighting, appetizing"
        html_content += f"<div class=\"ai-image\" data-prompt=\"{img_prompt}\">\n"
        html_content += f"<img src=\"placeholder_{img_slug}.jpg\">\n"
        html_content += "<p class=\"img-caption\">Ispirazione visiva AI</p>\n"
        html_content += "</div>\n"

    html_content += "</div>\n"
    return html_content


def render_daily_special(special, promo):
    """Render the daily special banner."""
    if not special:
        return ""

    original_price = special.get("original_price", 0)
    discount_pct = special.get("discount_pct", 0)
    disc_price = round(original_price * (1 - discount_pct / 100), 2)
    savings = round(original_price - disc_price, 2)

    dish = special.get("dish", "")
    html_content = "<div class=\"special-banner\">\n"
    html_content += "<div class=\"special-title\">Piatto del Giorno</div>\n"
    html_content += f"<div class=\"special-dish\">{dish}</div>\n"
    html_content += "<div class=\"special-pricing\">\n"
    html_content += f"<span class=\"original-price\">\u20ac{original_price:.2f}</span>\n"
    html_content += f"<span class=\"discount-price\">\u20ac{disc_price:.2f}</span>\n"
    html_content += f"<span class=\"savings\">Risparmi \u20ac{savings:.2f}!</span>\n"
    html_content += "</div>\n"
    if promo:
        html_content += f"<div class=\"promo-code\">Usa il codice: <strong>{promo}</strong></div>\n"
    html_content += "</div>\n"
    return html_content


def render_stats_footer(stats):
    """Render the statistics footer."""
    total_items = stats.get("total_items", 0)
    total_stars = stats.get("total_stars", 0)
    overall_avg = stats.get("overall_avg", 0)
    star_names = stats.get("star_names", [])

    html_content = "<div class=\"stats-footer\">\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{total_items}</span>\n"
    html_content += "<span class=\"stat-label\">Piatti</span></div>\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{total_stars}</span>\n"
    html_content += "<span class=\"stat-label\">Star Dishes</span></div>\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{overall_avg:.1f}</span>\n"
    html_content += "<span class=\"stat-label\">Media</span></div>\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{', '.join(star_names)}</span>\n"
    html_content += "<span class=\"stat-label\">I Nostri Migliori</span></div>\n"
    html_content += "</div>\n"
    return html_content


def render_html_footer():
    """Render the closing HTML tags."""
    return "</body>\n</html>\n"


# ── Orchestrator ───────────────────────────────────────────────────────────

def generate_restaurant_page(menu_data):
    """Generate a complete HTML page from menu data."""
    prepared_data = prepare_menu_data(menu_data)
    html_content = render_restaurant_page(prepared_data)
    return html_content


# ── Direct execution (for manual testing) ────────────────────────────────────
if __name__ == "__main__":
    output = generate_restaurant_page(SAMPLE_MENU)
    with open("output_refactored.html", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Generated {len(output)} chars -> output_refactored.html")

__all__ = ['generate_restaurant_page', 'SAMPLE_MENU']