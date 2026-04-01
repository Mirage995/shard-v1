"""refactored_agent.py — Refactored version of legacy_agent.py."""

import re
from legacy_agent import SAMPLE_MENU

_STAR_THRESHOLD = 4.7
MAX_ALLERGENS_SHOWN = 2
ENABLE_IMAGES = True


class RestaurantDataProcessor:
    """Processes restaurant menu data."""

    def __init__(self, menu_data):
        self.menu_data = menu_data
        self.restaurant = menu_data.get("restaurant", {})
        self.categories = menu_data.get("categories", [])
        self.daily_special = menu_data.get("daily_special")
        self.promo_code = menu_data.get("promo_code", "")
        self.total_items = 0
        self.total_stars = 0
        self.all_ratings = []
        self.discount_cache = {}

    def process_menu(self):
        """Processes the menu data, sorting and calculating values."""
        processed_categories = []
        for cat in self.categories:
            items = sorted(cat["items"], key=lambda x: x["rating"], reverse=True)
            avg = sum(i["rating"] for i in items) / len(items) if items else 0
            processed_items = []
            for item in items:
                self.total_items += 1
                self.all_ratings.append(item["rating"])
                price = self._calculate_price(item)
                is_star = item["rating"] >= _STAR_THRESHOLD
                if is_star:
                    self.total_stars += 1
                allergens_display = self._format_allergens(item.get("allergens", []))
                processed_items.append({
                    "item": item,
                    "price": price,
                    "is_star": is_star,
                    "allergens_display": allergens_display,
                })
            processed_categories.append({
                "category": cat,
                "items": processed_items,
                "average_rating": avg,
            })
        return processed_categories

    def _calculate_price(self, item):
        """Calculates the price of a menu item, considering discounts."""
        price = item["price"]
        if item["is_special"] and self.daily_special:
            disc = self.daily_special.get("discount_pct", 0)
            price = round(item["price"] * (1 - disc / 100), 2)
            self.discount_cache[item["name"]] = price
        return price

    def _format_allergens(self, allergens):
        """Formats the allergen list for display."""
        if len(allergens) > MAX_ALLERGENS_SHOWN:
            a_display = ", ".join(allergens[:MAX_ALLERGENS_SHOWN]) + f" +{len(allergens) - MAX_ALLERGENS_SHOWN}"
        else:
            a_display = ", ".join(allergens)
        return a_display

    def get_overall_average_rating(self):
        """Calculates the overall average rating."""
        return sum(self.all_ratings) / len(self.all_ratings) if self.all_ratings else 0

    def get_star_dish_names(self):
        """Retrieves the names of star dishes."""
        star_names = []
        for c in self.categories:
            for it in c["items"]:
                if it["rating"] >= 4.7:
                    star_names.append(it["name"])
        return star_names

    def get_daily_special_data(self):
        """Calculates daily special discount and savings."""
        if self.daily_special:
            disc_price = round(self.daily_special["original_price"] * (1 - self.daily_special["discount_pct"] / 100), 2)
            savings = round(self.daily_special["original_price"] - disc_price, 2)
            return {
                "discounted_price": disc_price,
                "savings": savings
            }
        return None


class HTMLRenderer:
    """Renders HTML from processed data."""

    def __init__(self):
        self.html = ""

    def render_page(self, data_processor):
        """Renders the complete HTML page."""
        self._render_doctype()
        self._render_head(data_processor.restaurant)
        self._render_body(data_processor)
        return self.html

    def _render_doctype(self):
        self.html += "<!DOCTYPE html>\n"

    def _render_head(self, restaurant):
        self.html += "<html>\n<head>\n<meta charset=\"utf-8\">\n"
        self.html += f"<title>{restaurant.get('name', '')} — Menu</title>\n"
        self._render_styles()
        self.html += "</head>\n"

    def _render_styles(self):
        self.html += "<style>\n"
        self.html += "body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; color: #2d3748; }\n"
        self.html += ".page-header { text-align: center; padding: 30px 0; border-bottom: 3px solid #e53e3e; margin-bottom: 30px; }\n"
        self.html += ".page-header h1 { font-size: 2.4em; color: #c53030; margin: 0; }\n"
        self.html += ".page-header .subtitle { color: #718096; font-size: 1.1em; margin-top: 8px; }\n"
        self.html += ".page-header .motto { font-style: italic; color: #a0aec0; margin-top: 4px; }\n"
        self.html += ".category-card { background: white; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
        self.html += ".category-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 2px solid #fed7d7; padding-bottom: 12px; }\n"
        self.html += ".category-header h2 { margin: 0; color: #c53030; }\n"
        self.html += ".avg-badge { background: #fff5f5; color: #c53030; padding: 4px 12px; border-radius: 20px; font-weight: bold; }\n"
        self.html += ".menu-item { padding: 12px 0; border-bottom: 1px solid #edf2f7; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }\n"
        self.html += ".menu-item:last-child { border-bottom: none; }\n"
        self.html += ".item-name { font-weight: 600; font-size: 1.1em; flex: 1; }\n"
        self.html += ".star-badge { background: #fefcbf; color: #975a16; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; margin-left: 8px; }\n"
        self.html += ".item-price { font-weight: bold; color: #2d3748; }\n"
        self.html += ".original-price { text-decoration: line-through; color: #a0aec0; margin-right: 8px; }\n"
        self.html += ".discount-price { color: #e53e3e; font-size: 1.15em; }\n"
        self.html += ".allergens { font-size: 0.85em; color: #a0aec0; width: 100%; }\n"
        self.html += ".ai-image { margin-top: 8px; width: 100%; }\n"
        self.html += ".ai-image img { max-width: 300px; border-radius: 8px; }\n"
        self.html += ".ai-image .img-caption { font-size: 0.8em; color: #a0aec0; font-style: italic; }\n"
        self.html += ".special-banner { background: linear-gradient(135deg, #fff5f5 0%, #fed7d7 100%); border-radius: 12px; padding: 24px; margin-bottom: 24px; text-align: center; border: 2px solid #feb2b2; }\n"
        self.html += ".special-title { font-size: 0.9em; text-transform: uppercase; letter-spacing: 2px; color: #c53030; margin-bottom: 8px; }\n"
        self.html += ".special-dish { font-size: 1.6em; font-weight: bold; color: #2d3748; margin-bottom: 12px; }\n"
        self.html += ".special-pricing { font-size: 1.2em; margin-bottom: 12px; }\n"
        self.html += ".savings { color: #38a169; font-weight: bold; }\n"
        self.html += ".promo-code { background: #c53030; color: white; display: inline-block; padding: 8px 20px; border-radius: 8px; font-weight: bold; letter-spacing: 1px; }\n"
        self.html += ".stats-footer { display: flex; justify-content: space-around; background: white; border-radius: 12px; padding: 24px; margin-top: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }\n"
        self.html += ".stat-item { text-align: center; }\n"
        self.html += ".stat-value { display: block; font-size: 1.8em; font-weight: bold; color: #c53030; }\n"
        self.html += ".stat-label { font-size: 0.85em; color: #718096; }\n"
        self.html += "</style>\n"

    def _render_body(self, data_processor):
        self.html += "<body>\n"
        self._render_header(data_processor.restaurant)
        self._render_categories(data_processor.process_menu())
        self._render_daily_special(data_processor)
        self._render_stats_footer(data_processor)
        self.html += "</body>\n</html>\n"

    def _render_header(self, restaurant):
        self.html += "<div class=\"page-header\">\n"
        self.html += f"<h1>{restaurant.get('name', '')}</h1>\n"
        self.html += f"<div class=\"subtitle\">Dal {restaurant.get('since', '')} a {restaurant.get('city', '')}</div>\n"
        self.html += f"<div class=\"motto\">\"{restaurant.get('motto', '')}\"</div>\n"
        self.html += "</div>\n"

    def _render_categories(self, processed_categories):
        for cat_data in processed_categories:
            self.html += "<div class=\"category-card\">\n"
            self.html += "<div class=\"category-header\">\n"
            self.html += f"<h2>{cat_data['category'].get('name', '')}</h2>\n"
            self.html += f"<span class=\"avg-badge\">{cat_data['average_rating']:.1f}</span>\n"
            self.html += "</div>\n"
            for item_data in cat_data["items"]:
                self._render_menu_item(item_data)
            self.html += "</div>\n"

    def _render_menu_item(self, item_data):
        item = item_data["item"]
        star_html = " <span class=\"star-badge\">\u2605 Star Dish</span>" if item_data["is_star"] else ""

        self.html += "<div class=\"menu-item\">\n"
        self.html += f"<div class=\"item-name\">{item.get('name', '')}{star_html}</div>\n"

        if item["is_special"]:
            self.html += "<div class=\"item-price\">"
            self.html += f"<span class=\"original-price\">\u20ac{item.get('price', 0.0):.2f}</span>"
            self.html += f" <span class=\"discount-price\">\u20ac{item_data['price']:.2f}</span>"
            self.html += "</div>\n"
        else:
            self.html += f"<div class=\"item-price\">\u20ac{item_data['price']:.2f}</div>\n"

        self.html += f"<div class=\"allergens\">Allergeni: {item_data.get('allergens_display', '')}</div>\n"

        if ENABLE_IMAGES and item_data["is_star"]:
            img_slug = item.get('name', '').lower().replace(" ", "_")
            img_prompt = f"Hyper-realistic photo of {item.get('name', '')}, Italian restaurant, warm natural lighting, appetizing"
            self.html += f"<div class=\"ai-image\" data-prompt=\"{img_prompt}\">\n"
            self.html += f"<img src=\"placeholder_{img_slug}.jpg\">\n"
            self.html += "<p class=\"img-caption\">Ispirazione visiva AI</p>\n"
            self.html += "</div>\n"

        self.html += "</div>\n"

    def _render_daily_special(self, data_processor):
        special = data_processor.menu_data.get("daily_special")
        promo = data_processor.menu_data.get("promo_code", "")
        special_data = data_processor.get_daily_special_data()

        if special and special_data:
            self.html += "<div class=\"special-banner\">\n"
            self.html += "<div class=\"special-title\">Piatto del Giorno</div>\n"
            self.html += f"<div class=\"special-dish\">{special.get('dish', '')}</div>\n"
            self.html += "<div class=\"special-pricing\">\n"
            self.html += f"<span class=\"original-price\">\u20ac{special.get('original_price', 0.0):.2f}</span>\n"
            self.html += f"<span class=\"discount-price\">\u20ac{special_data.get('discounted_price', 0.0):.2f}</span>\n"
            self.html += f"<span class=\"savings\">Risparmi \u20ac{special_data.get('savings', 0.0):.2f}!</span>\n"
            self.html += "</div>\n"
            if promo:
                self.html += f"<div class=\"promo-code\">Usa il codice: <strong>{promo}</strong></div>\n"
            self.html += "</div>\n"

    def _render_stats_footer(self, data_processor):
        overall_avg = data_processor.get_overall_average_rating()
        star_names = data_processor.get_star_dish_names()

        self.html += "<div class=\"stats-footer\">\n"
        self.html += f"<div class=\"stat-item\"><span class=\"stat-value\">{data_processor.total_items}</span>\n"
        self.html += "<span class=\"stat-label\">Piatti</span></div>\n"
        self.html += f"<div class=\"stat-item\"><span class=\"stat-value\">{data_processor.total_stars}</span>\n"
        self.html += "<span class=\"stat-label\">Star Dishes</span></div>\n"
        self.html += f"<div class=\"stat-item\"><span class=\"stat-value\">{overall_avg:.1f}</span>\n"
        self.html += "<span class=\"stat-label\">Media</span></div>\n"
        self.html += f"<div class=\"stat-item\"><span class=\"stat-value\">{', '.join(star_names)}</span>\n"
        self.html += "<span class=\"stat-label\">I Nostri Migliori</span></div>\n"
        self.html += "</div>\n"


def generate_restaurant_page(menu_data):
    """Generates the restaurant page using the refactored code."""
    data_processor = RestaurantDataProcessor(menu_data)
    renderer = HTMLRenderer()
    return renderer.render_page(data_processor)


if __name__ == "__main__":
    output = generate_restaurant_page(SAMPLE_MENU)
    with open("output_refactored.html", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Generated {len(output)} chars -> output_refactored.html")