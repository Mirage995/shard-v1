"""refactored_agent.py — Refactored HTML Trap."""

from legacy_agent import SAMPLE_MENU

_STAR_THRESHOLD = 4.7
MAX_ALLERGENS_SHOWN = 2
ENABLE_IMAGES = True


class Restaurant:
    def __init__(self, data):
        self.name = data["name"]
        self.since = data["since"]
        self.city = data["city"]
        self.motto = data["motto"]


class Category:
    def __init__(self, data):
        self.name = data["name"]
        self.items = sorted([MenuItem(item) for item in data["items"]], key=lambda x: x.rating, reverse=True)
        self.average_rating = sum(item.rating for item in self.items) / len(self.items) if self.items else 0

    def render_html(self):
        html = "<div class=\"category-card\">\n"
        html += "<div class=\"category-header\">\n"
        html += f"<h2>{self.name}</h2>\n"
        html += f"<span class=\"avg-badge\">{self.average_rating:.1f}</span>\n"
        html += "</div>\n"
        for item in self.items:
            html += item.render_html()
        html += "</div>\n"
        return html


class MenuItem:
    def __init__(self, data):
        self.name = data["name"]
        self.price = data["price"]
        self.rating = data["rating"]
        self.is_special = data["is_special"]
        self.allergens = data.get("allergens", [])
        self.discounted_price = None

    def calculate_discount(self, daily_special):
        if self.is_special and daily_special:
            disc = daily_special.get("discount_pct", 0)
            self.discounted_price = round(self.price * (1 - disc / 100), 2)

    def format_allergens(self):
        if len(self.allergens) > MAX_ALLERGENS_SHOWN:
            return ", ".join(self.allergens[:MAX_ALLERGENS_SHOWN]) + f" +{len(self.allergens) - MAX_ALLERGENS_SHOWN}"
        else:
            return ", ".join(self.allergens)

    def render_html(self):
        star_html = " <span class=\"star-badge\">\u2605 Star Dish</span>" if self.rating >= _STAR_THRESHOLD else ""
        allergens_display = self.format_allergens()

        html = "<div class=\"menu-item\">\n"
        html += f"<div class=\"item-name\">{self.name}{star_html}</div>\n"

        if self.is_special and self.discounted_price is not None:
            html += "<div class=\"item-price\">"
            html += f"<span class=\"original-price\">\u20ac{self.price:.2f}</span>"
            html += f" <span class=\"discount-price\">\u20ac{self.discounted_price:.2f}</span>"
            html += "</div>\n"
        else:
            html += f"<div class=\"item-price\">\u20ac{self.price:.2f}</div>\n"

        html += f"<div class=\"allergens\">Allergeni: {allergens_display}</div>\n"

        if ENABLE_IMAGES and self.rating >= _STAR_THRESHOLD:
            img_slug = self.name.lower().replace(" ", "_")
            img_prompt = f"Hyper-realistic photo of {self.name}, Italian restaurant, warm natural lighting, appetizing"
            html += f"<div class=\"ai-image\" data-prompt=\"{img_prompt}\">\n"
            html += f"<img src=\"placeholder_{img_slug}.jpg\">\n"
            html += "<p class=\"img-caption\">Ispirazione visiva AI</p>\n"
            html += "</div>\n"

        html += "</div>\n"
        return html


class DailySpecial:
    def __init__(self, data):
        self.dish = data["dish"]
        self.original_price = data["original_price"]
        self.discount_pct = data["discount_pct"]
        self.discounted_price = round(self.original_price * (1 - self.discount_pct / 100), 2)
        self.savings = round(self.original_price - self.discounted_price, 2)

    def render_html(self, promo_code=""):
        html = "<div class=\"special-banner\">\n"
        html += "<div class=\"special-title\">Piatto del Giorno</div>\n"
        html += f"<div class=\"special-dish\">{self.dish}</div>\n"
        html += "<div class=\"special-pricing\">\n"
        html += f"<span class=\"original-price\">\u20ac{self.original_price:.2f}</span>\n"
        html += f"<span class=\"discount-price\">\u20ac{self.discounted_price:.2f}</span>\n"
        html += f"<span class=\"savings\">Risparmi \u20ac{self.savings:.2f}!</span>\n"
        html += "</div>\n"
        if promo_code:
            html += f"<div class=\"promo-code\">Usa il codice: <strong>{promo_code}</strong></div>\n"
        html += "</div>\n"
        return html


def prepare_menu_data(menu_data):
    restaurant = Restaurant(menu_data["restaurant"])
    categories = [Category(cat) for cat in menu_data["categories"]]
    daily_special_data = menu_data.get("daily_special")
    daily_special = DailySpecial(daily_special_data) if daily_special_data else None
    promo_code = menu_data.get("promo_code", "")

    for category in categories:
        for item in category.items:
            item.calculate_discount(daily_special_data)

    return restaurant, categories, daily_special, promo_code


def render_html_page(restaurant, categories, daily_special, promo_code):
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

    html += "<div class=\"page-header\">\n"
    html += f"<h1>{restaurant.name}</h1>\n"
    html += f"<div class=\"subtitle\">Dal {restaurant.since} a {restaurant.city}</div>\n"
    html += f"<div class=\"motto\">\"{restaurant.motto}\"</div>\n"
    html += "</div>\n"

    for category in categories:
        html += category.render_html()

    if daily_special:
        html += daily_special.render_html(promo_code)

    return html


def render_stats_footer(categories):
    total_items = sum(len(c.items) for c in categories)
    all_ratings = [item.rating for c in categories for item in c.items]
    overall_avg = sum(all_ratings) / len(all_ratings) if all_ratings else 0
    star_names = sorted([item.name for c in categories for item in c.items if item.rating >= 4.7])

    total_stars = len([item for c in categories for item in c.items if item.rating >= 4.7])

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


def generate_restaurant_page(menu_data):
    restaurant, categories, daily_special, promo_code = prepare_menu_data(menu_data)
    html = render_html_page(restaurant, categories, daily_special, promo_code)
    html += render_stats_footer(categories)
    html += "</body>\n</html>\n"
    return html


if __name__ == "__main__":
    output = generate_restaurant_page(SAMPLE_MENU)
    with open("output_refactored.html", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Generated {len(output)} chars -> output_refactored.html")