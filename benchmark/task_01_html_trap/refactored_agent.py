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
    if not isinstance(menu_data, dict):
        return {
            "restaurant": {"name": "Error", "since": "", "city": "", "motto": "Invalid menu data"},
            "categories": [],
            "daily_special": None,
            "promo_code": "",
            "overall_stats": {"total_items": 0, "overall_avg": 0, "star_names": [], "total_stars": 0},
        }

    restaurant = menu_data.get("restaurant", {})
    if not isinstance(restaurant, dict):
        restaurant = {}

    categories = []
    if isinstance(menu_data.get("categories"), list):
        for cat in menu_data.get("categories", []):
            if isinstance(cat, dict):
                categories.append(prepare_category(cat, menu_data))

    daily_special = menu_data.get("daily_special")
    if daily_special is not None and not isinstance(daily_special, dict):
        daily_special = None
    promo_code = menu_data.get("promo_code", "")
    if not isinstance(promo_code, str):
        promo_code = ""

    restaurant_name = restaurant.get("name", "Unnamed Restaurant")
    restaurant_since = restaurant.get("since", "")
    restaurant_city = restaurant.get("city", "")
    restaurant_motto = restaurant.get("motto", "")

    restaurant_data = {
        "name": restaurant_name,
        "since": restaurant_since,
        "city": restaurant_city,
        "motto": restaurant_motto,
    }

    overall_stats = calculate_overall_stats(menu_data)

    return {
        "restaurant": restaurant_data,
        "categories": categories,
        "daily_special": daily_special,
        "promo_code": promo_code,
        "overall_stats": overall_stats,
    }


def prepare_category(category, menu_data):
    """Prepare a single category, sorting items and calculating average rating."""
    if not isinstance(category, dict):
        return {"name": "Invalid Category", "items": [], "avg_rating": 0}

    items = category.get("items", [])
    if not isinstance(items, list):
        items = []

    prepared_items = []
    for item in items:
        if isinstance(item, dict):
            prepared_items.append(prepare_menu_item(item, menu_data))

    prepared_items = sorted(prepared_items, key=lambda x: x.get("rating", 0), reverse=True)
    name = category.get("name", "Unnamed Category")
    if not isinstance(name, str):
        name = "Unnamed Category"

    avg_rating = calculate_average_rating(prepared_items)

    return {
        "name": name,
        "items": prepared_items,
        "avg_rating": avg_rating,
    }


def prepare_menu_item(item, menu_data):
    """Prepare a single menu item, calculating price and truncating allergens."""
    if not isinstance(item, dict):
        return {
            "name": "Invalid Item",
            "price": 0,
            "rating": 0,
            "is_special": False,
            "allergens_display": "",
            "is_star": False,
            "original_price": 0,
            "discount_price": 0,
        }

    price_info = calculate_price(item, menu_data)
    allergens_display = format_allergens(item.get("allergens", []))
    rating = item.get("rating", 0)
    if not isinstance(rating, (int, float)):
        rating = 0
    if rating < 0:
        rating = 0
    is_star = rating >= STAR_RATING_THRESHOLD
    name = item.get("name", "Unnamed Item")
    if not isinstance(name, str):
        name = "Unnamed Item"

    return {
        "name": name,
        "price": item.get("price", 0),
        "rating": rating,
        "is_special": item.get("is_special", False),
        "allergens_display": allergens_display,
        "is_star": is_star,
        "original_price": price_info["original_price"],
        "discount_price": price_info["discount_price"],
    }


def calculate_price(item, menu_data):
    """Calculate the price of a menu item, considering daily specials."""
    original_price = item.get("price", 0)
    if not isinstance(original_price, (int, float)):
        original_price = 0
    if original_price < 0:
        original_price = 0
    if original_price > 1e10:
        original_price = 1e10

    discount_price = original_price
    if item.get("is_special") and daily_special_exists(menu_data):
        daily_special = menu_data.get("daily_special", {})
        discount_pct = daily_special.get("discount_pct", 0)
        if not isinstance(discount_pct, (int, float)):
            discount_pct = 0
        if discount_pct < 0:
            discount_pct = 0
        if discount_pct > 100:
            discount_pct = 100

        try:
            discount_price = round(original_price * (1 - discount_pct / 100), 2)
        except (OverflowError, ValueError):
            discount_price = 0

        if discount_price < 0:
            discount_price = 0
    return {"original_price": original_price, "discount_price": discount_price}


def format_allergens(allergens):
    """Format the allergen list, truncating if necessary."""
    if not isinstance(allergens, list):
        return ""

    valid_allergens = []
    for a in allergens:
        if isinstance(a, str):
            valid_allergens.append(a)
        else:
            valid_allergens.append(str(a))

    if len(valid_allergens) > MAX_ALLERGENS_SHOWN:
        return ", ".join(valid_allergens[:MAX_ALLERGENS_SHOWN]) + f" +{len(valid_allergens) - MAX_ALLERGENS_SHOWN}"
    else:
        return ", ".join(valid_allergens)


def calculate_average_rating(items):
    """Calculate the average rating for a list of items."""
    if not items:
        return 0
    valid_ratings = [i.get("rating", 0) for i in items if isinstance(i, dict) and isinstance(i.get("rating", 0), (int, float))]
    if not valid_ratings:
        return 0
    return sum(valid_ratings) / len(valid_ratings)


def calculate_overall_stats(menu_data):
    """Calculate overall statistics for the menu."""
    total_items = 0
    all_ratings_sum = 0
    all_ratings_count = 0
    star_names = []

    if not isinstance(menu_data, dict) or not isinstance(menu_data.get("categories"), list):
        return {
            "total_items": 0,
            "overall_avg": 0,
            "star_names": [],
            "total_stars": 0,
        }

    for c in menu_data["categories"]:
        if not isinstance(c, dict) or not isinstance(c.get("items"), list):
            continue
        for it in c["items"]:
            if not isinstance(it, dict):
                continue
            total_items += 1
            rating = it.get("rating")
            if isinstance(rating, (int, float)):
                all_ratings_sum += rating
                all_ratings_count += 1
            if it.get("rating", 0) >= STAR_RATING_THRESHOLD:
                name = it.get("name")
                if isinstance(name, str):
                    star_names.append(name)

    overall_avg = all_ratings_sum / all_ratings_count if all_ratings_count else 0
    total_stars = len(star_names)
    return {
        "total_items": total_items,
        "overall_avg": overall_avg,
        "star_names": sorted(star_names),
        "total_stars": total_stars,
    }


def get_star_dish_names(categories):
    """Get a list of names of dishes with rating >= 4.7."""
    star_names = []
    for c in categories:
        if isinstance(c, dict):
            for it in c.get("items", []):
                if isinstance(it, dict) and it.get("rating", 0) >= STAR_RATING_THRESHOLD:
                    name = it.get("name")
                    if isinstance(name, str):
                        star_names.append(html.escape(name))
    return star_names


def daily_special_exists(menu_data):
    """Check if daily special exists in menu data."""
    return isinstance(menu_data, dict) and "daily_special" in menu_data and isinstance(menu_data.get("daily_special"), dict) and menu_data["daily_special"] is not None


# ── HTML Rendering ─────────────────────────────────────────────────────────

def render_restaurant_page(menu_data):
    """Render the complete HTML page from prepared menu data."""
    r = menu_data["restaurant"]
    cats = menu_data["categories"]
    special = menu_data["daily_special"]
    promo = menu_data["promo_code"]
    stats = menu_data["overall_stats"]

    html_content = render_html_header(r)
    html_content += render_categories(cats, special, promo, menu_data)
    html_content += render_daily_special(special, promo)
    html_content += render_stats_footer(stats)
    html_content += render_html_footer()
    return html_content


def render_html_header(restaurant):
    """Render the HTML header section."""
    name = html.escape(restaurant.get('name', ''))
    since = html.escape(str(restaurant.get('since', '')))
    city = html.escape(restaurant.get('city', ''))
    motto = html.escape(restaurant.get('motto', ''))

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


def render_categories(categories, special, promo, menu_data):
    """Render the categories section."""
    html_content = ""
    daily_special_exists_flag = daily_special_exists(menu_data)
    for cat in categories:
        html_content += "<div class=\"category-card\">\n"
        html_content += "<div class=\"category-header\">\n"
        name = html.escape(cat['name'])
        html_content += f"<h2>{name}</h2>\n"
        html_content += f"<span class=\"avg-badge\">{cat['avg_rating']:.1f}</span>\n"
        html_content += "</div>\n"

        for item in cat["items"]:
            html_content += render_menu_item(item, special, promo, menu_data, daily_special_exists_flag)
        html_content += "</div>\n"
    return html_content


def render_menu_item(item, special, promo, menu_data, daily_special_exists_flag):
    """Render a single menu item."""
    if item["is_star"]:
        star_html = " <span class=\"star-badge\">\u2605 Star Dish</span>"
    else:
        star_html = ""

    name = html.escape(item['name'])
    allergens_display = html.escape(item['allergens_display'])

    html_content = "<div class=\"menu-item\">\n"
    html_content += f"<div class=\"item-name\">{name}{star_html}</div>\n"

    if item["is_special"] and daily_special_exists_flag:
        html_content += "<div class=\"item-price\">"
        html_content += f"<span class=\"original-price\">\u20ac{item['original_price']:.2f}</span>"
        html_content += f" <span class=\"discount-price\">\u20ac{item['discount_price']:.2f}</span>"
        html_content += "</div>\n"
    else:
        html_content += f"<div class=\"item-price\">\u20ac{item['price']:.2f}</div>\n"

    html_content += f"<div class=\"allergens\">Allergeni: {allergens_display}</div>\n"

    if ENABLE_IMAGES and item["is_star"]:
        img_slug = html.escape(item["name"].lower().replace(" ", "_"))
        img_prompt = f"Hyper-realistic photo of {item['name']}, Italian restaurant, warm natural lighting, appetizing"
        escaped_img_prompt = html.escape(img_prompt, quote=True)
        html_content += f"<div class=\"ai-image\" data-prompt=\"{escaped_img_prompt}\">\n"
        html_content += f"<img src=\"placeholder_{img_slug}.jpg\">\n"
        html_content += "<p class=\"img-caption\">Ispirazione visiva AI</p>\n"
        html_content += "</div>\n"

    html_content += "</div>\n"
    return html_content


def render_daily_special(special, promo):
    """Render the daily special banner."""
    if not special:
        return ""

    dish = special.get('dish', '')
    original_price = special.get('original_price', 0)
    discount_pct = special.get('discount_pct', 0)

    if not isinstance(dish, str):
        dish = ''
    if not isinstance(original_price, (int, float)):
        original_price = 0
    if not isinstance(discount_pct, (int, float)):
        discount_pct = 0

    dish = html.escape(dish)

    try:
        disc_price = round(original_price * (1 - discount_pct / 100), 2)
        savings = round(original_price - disc_price, 2)
    except (TypeError, ValueError):
        disc_price = 0
        savings = 0

    html_content = "<div class=\"special-banner\">\n"
    html_content += "<div class=\"special-title\">Piatto del Giorno</div>\n"
    html_content += f"<div class=\"special-dish\">{dish}</div>\n"
    html_content += "<div class=\"special-pricing\">\n"
    html_content += f"<span class=\"original-price\">\u20ac{original_price:.2f}</span>\n"
    html_content += f"<span class=\"discount-price\">\u20ac{disc_price:.2f}</span>\n"
    html_content += f"<span class=\"savings\">Risparmi \u20ac{savings:.2f}!</span>\n"
    html_content += "</div>\n"
    if promo:
        promo_code = html.escape(promo)
        html_content += f"<div class=\"promo-code\">Usa il codice: <strong>{promo_code}</strong></div>\n"
    html_content += "</div>\n"
    return html_content


def render_stats_footer(stats):
    """Render the statistics footer."""
    html_content = "<div class=\"stats-footer\">\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{stats['total_items']}</span>\n"
    html_content += "<span class=\"stat-label\">Piatti</span></div>\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{stats['total_stars']}</span>\n"
    html_content += "<span class=\"stat-label\">Star Dishes</span></div>\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{stats['overall_avg']:.1f}</span>\n"
    html_content += "<span class=\"stat-label\">Media</span></div>\n"
    html_content += f"<div class=\"stat-item\"><span class=\"stat-value\">{', '.join(sorted(stats['star_names']))}</span>\n"
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