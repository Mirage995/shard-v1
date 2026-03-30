"""refactored_agent.py — Refactored Restaurant Menu Page Generator."""

from legacy_agent import SAMPLE_MENU, MAX_ALLERGENS_SHOWN

_STAR_THRESHOLD = 4.7
ENABLE_IMAGES = True


class Restaurant:
    """Represents a restaurant with its basic information."""

    def __init__(self, name, since, city, motto):
        self.name = name
        self.since = since
        self.city = city
        self.motto = motto


class MenuItem:
    """Represents a menu item with its details and methods for price calculation."""

    def __init__(self, name, price, rating, is_special, allergens):
        self.name = name
        self.price = price
        self.rating = rating
        self.is_special = is_special
        self.allergens = allergens


def calculate_discounted_price(item, daily_special):
    """Calculates the discounted price if the item is special and a daily special exists."""
    if item.is_special and daily_special:
        disc = daily_special.get("discount_pct", 0)
        return round(item.price * (1 - disc / 100), 2)
    return item.price


def get_truncated_allergens(allergens):
    """Truncates the allergen list to MAX_ALLERGENS_SHOWN."""
    if len(allergens) > MAX_ALLERGENS_SHOWN:
        return ", ".join(allergens[:MAX_ALLERGENS_SHOWN]) + f" +{len(allergens) - MAX_ALLERGENS_SHOWN}"
    return ", ".join(allergens)


def prepare_menu_data(menu_data):
    """Extracts and prepares data from the menu dictionary."""
    restaurant_data = menu_data["restaurant"]
    restaurant = Restaurant(restaurant_data["name"], restaurant_data["since"], restaurant_data["city"],
                            restaurant_data["motto"])
    categories = []
    for cat_data in menu_data["categories"]:
        items = [MenuItem(item["name"], item["price"], item["rating"], item["is_special"], item["allergens"]) for item
                 in cat_data["items"]]
        categories.append({"name": cat_data["name"], "items": items})
    daily_special = menu_data.get("daily_special")
    promo_code = menu_data.get("promo_code", "")
    return restaurant, categories, daily_special, promo_code


def calculate_category_average(items):
    """Calculates the average rating for a category."""
    return sum(item.rating for item in items) / len(items) if items else 0


def render_menu_item_html(item, discounted_price, is_star):
    """Renders the HTML for a single menu item."""
    star_html = " <span class=\"star-badge\">\u2605 Star Dish</span>" if is_star else ""
    allergens_display = get_truncated_allergens(item.allergens)

    html = "<div class=\"menu-item\">\n"
    html += f"<div class=\"item-name\">{item.name}{star_html}</div>\n"

    if item.is_special:
        html += "<div class=\"item-price\">"
        html += f"<span class=\"original-price\">\u20ac{item.price:.2f}</span>"
        html += f" <span class=\"discount-price\">\u20ac{discounted_price:.2f}</span>"
        html += "</div>\n"
    else:
        html += f"<div class=\"item-price\">\u20ac{item.price:.2f}</div>\n"

    html += f"<div class=\"allergens\">Allergeni: {allergens_display}</div>\n"

    if ENABLE_IMAGES and is_star:
        img_slug = item.name.lower().replace(" ", "_")
        img_prompt = f"Hyper-realistic photo of {item.name}, Italian restaurant, warm natural lighting, appetizing"
        html += f"<div class=\"ai-image\" data-prompt=\"{img_prompt}\">\n"
        html += f"<img src=\"placeholder_{img_slug}.jpg\">\n"
        html += "<p class=\"img-caption\">Ispirazione visiva AI</p>\n"
        html += "</div>\n"

    html += "</div>\n"
    return html


def render_category_html(category, daily_special):
    """Renders the HTML for a menu category."""
    items = sorted(category["items"], key=lambda x: x.rating, reverse=True)
    avg = calculate_category_average(items)

    html = "<div class=\"category-card\">\n"
    html += "<div class=\"category-header\">\n"
    html += f"<h2>{category['name']}</h2>\n"
    html += f"<span class=\"avg-badge\">{avg:.1f}</span>\n"
    html += "</div>\n"

    for item in items:
        discounted_price = calculate_discounted_price(item, daily_special)
        is_star = item.rating >= _STAR_THRESHOLD
        html += render_menu_item_html(item, discounted_price, is_star)

    html += "</div>\n"
    return html


def render_daily_special_html(special, promo_code):
    """Renders the HTML for the daily special banner."""
    disc_price = round(special["original_price"] * (1 - special["discount_pct"] / 100), 2)
    savings = round(special["original_price"] - disc_price, 2)

    html = "<div class=\"special-banner\">\n"
    html += "<div class=\"special-title\">Piatto del Giorno</div>\n"
    html += f"<div class=\"special-dish\">{special['dish']}</div>\n"
    html += "<div class=\"special-pricing\">\n"
    html += f"<span class=\"original-price\">\u20ac{special['original_price']:.2f}</span>\n"
    html += f"<span class=\"discount-price\">\u20ac{disc_price:.2f}</span>\n"
    html += f"<span class=\"savings\">Risparmi \u20ac{savings:.2f}!</span>\n"
    html += "</div>\n"
    if promo_code:
        html += f"<div class=\"promo-code\">Usa il codice: <strong>{promo_code}</strong></div>\n"
    html += "</div>\n"
    return html


def render_stats_footer_html(total_items, total_stars, overall_avg, star_names):
    """Renders the HTML for the statistics footer."""
    html = "<div class=\"stats-footer\">\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{total_items}</span>\n"
    html += "<span class=\"stat-label\">Piatti</span></div>\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{total_stars}</span>\n"
    html += "<span class=\"stat-label\">Star Dishes</span></div>\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{overall_avg:.1f}</span>\n"
    html += "<span class=\"stat-label\">Media</span></div>\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{', '.join(star_names)}</span>\n"
    html += "<span class=\"stat-label\">I Nostri Migliori</span></div>\n"
    html += "</div>\n"
    return html


def collect_menu_stats(categories):
    """Collects statistics from the menu data."""
    total_items = 0
    all_ratings = []
    total_stars = 0
    star_names = []

    for cat in categories:
        for item in cat["items"]:
            total_items += 1
            all_ratings.append(item.rating)
            if item.rating >= _STAR_THRESHOLD:
                total_stars += 1
                star_names.append(item.name)

    overall_avg = sum(all_ratings) / len(all_ratings) if all_ratings else 0

    return total_items, total_stars, overall_avg, star_names


def render_page_header(restaurant):
    """Renders the HTML for the page header."""
    html = "<div class=\"page-header\">\n"
    html += f"<h1>{restaurant.name}</h1>\n"
    html += f"<div class=\"subtitle\">Dal {restaurant.since} a {restaurant.city}</div>\n"
    html += f"<div class=\"motto\">\"{restaurant.motto}\"</div>\n"
    html += "</div>\n"
    return html


def render_html_skeleton(restaurant):
    """Renders the basic HTML structure and CSS."""
    html = "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
    html += f"<title>{restaurant.name} — Menu</title>\n"
    html += "<style>\n"
    html += "body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; color: #2d3748; }\n"
    html += ".page-header { text-align: center; padding: 30px 0; border-bottom: 3px solid #e53e3e; margin-bottom: 30px; }\n"
    html += ".page-header h1 { font-size: 2.4em; color: #c53030; margin: 0; }\n"
    html += ".page-header .subtitle { color: #718096; font-size: 1.1em; margin-top: 8px; }\n"
    html += ".page-header .motto { font-style: italic; color: #a0aec0; margin-top: 4px; }\n"
    html += ".category-card { background: white; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
    html += ".category-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 2px solid #fed7d7; padding-bottom: 12px; }\n"
    html += ".category-header h2 { margin: 0; color: #c53030; }\n"
    html += ".avg-badge { background: #fff5f5; color: #c53030; padding: 4px 12px; border-radius: 20px; font-weight: bold; }\n"
    html += ".menu-item { padding: 12px 0; border-bottom: 1px solid #edf2f7; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }\n"
    html += ".menu-item:last-child { border-bottom: none; }\n"
    html += ".item-name { font-weight: 600; font-size: 1.1em; flex: 1; }\n"
    html += ".star-badge { background: #fefcbf; color: #975a16; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; margin-left: 8px; }\n"
    html += ".item-price { font-weight: bold; color: #2d3748; }\n"
    html += ".original-price { text-decoration: line-through; color: #a0aec0; margin-right: 8px; }\n"
    html += ".discount-price { color: #e53e3e; font-size: 1.15em; }\n"
    html += ".allergens { font-size: 0.85em; color: #a0aec0; width: 100%; }\n"
    html += ".ai-image { margin-top: 8px; width: 100%; }\n"
    html += ".ai-image img { max-width: 300px; border-radius: 8px; }\n"
    html += ".ai-image .img-caption { font-size: 0.8em; color: #a0aec0; font-style: italic; }\n"
    html += ".special-banner { background: linear-gradient(135deg, #fff5f5 0%, #fed7d7 100%); border-radius: 12px; padding: 24px; margin-bottom: 24px; text-align: center; border: 2px solid #feb2b2; }\n"
    html += ".special-title { font-size: 0.9em; text-transform: uppercase; letter-spacing: 2px; color: #c53030; margin-bottom: 8px; }\n"
    html += ".special-dish { font-size: 1.6em; font-weight: bold; color: #2d3748; margin-bottom: 12px; }\n"
    html += ".special-pricing { font-size: 1.2em; margin-bottom: 12px; }\n"
    html += ".savings { color: #38a169; font-weight: bold; }\n"
    html += ".promo-code { background: #c53030; color: white; display: inline-block; padding: 8px 20px; border-radius: 8px; font-weight: bold; letter-spacing: 1px; }\n"
    html += ".stats-footer { display: flex; justify-content: space-around; background: white; border-radius: 12px; padding: 24px; margin-top: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
    html += ".stat-item { text-align: center; }\n"
    html += ".stat-value { display: block; font-size: 1.8em; font-weight: bold; color: #c53030; }\n"
    html += ".stat-label { font-size: 0.85em; color: #718096; }\n"
    html += "</style>\n</head>\n<body>\n"
    return html


def generate_restaurant_page(menu_data):
    """Generates a complete HTML page from menu data."""

    restaurant, categories, daily_special, promo_code = prepare_menu_data(menu_data)

    html = render_html_skeleton(restaurant)
    html += render_page_header(restaurant)

    for category in categories:
        html += render_category_html(category, daily_special)

    if daily_special:
        html += render_daily_special_html(daily_special, promo_code)

    total_items, total_stars, overall_avg, star_names = collect_menu_stats(categories)

    html += render_stats_footer_html(total_items, total_stars, overall_avg, star_names)

    html += "</body>\n</html>\n"
    return html


if __name__ == "__main__":
    output = generate_restaurant_page(SAMPLE_MENU)
    with open("output_refactored.html", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Generated {len(output)} chars -> output_refactored.html")