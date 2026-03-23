"""legacy_agent.py — The HTML Trap.

A deliberately tangled restaurant menu page generator.
Business logic, HTML rendering, CSS, and state management
are all fused into one monstrous function.

IT WORKS PERFECTLY. The HTML output is the ground truth.
The challenge: refactor this without changing a single byte of output.
"""

# ── Globals (some useful, some vestigial) ────────────────────────────────────
_render_count = 0
ENABLE_IMAGES = True
_STAR_THRESHOLD = 4.7
MAX_ALLERGENS_SHOWN = 2
_discount_cache = {}
_IMG_QUALITY = "standard"  # unused but referenced in comments
PROMO_ACTIVE = True  # checked nowhere

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


# ── The monster ──────────────────────────────────────────────────────────────

def generate_restaurant_page(menu_data):
    """Generate a complete HTML page from menu data.

    This function does EVERYTHING:
      - sorts items by rating
      - calculates discounts and averages
      - decides star badges
      - truncates allergen lists
      - builds the entire HTML string with inline CSS
      - generates DALL-E image placeholders for star dishes

    Returns: a single HTML string.
    """
    global _render_count, _discount_cache
    _render_count += 1
    _discount_cache = {}

    r = menu_data["restaurant"]
    cats = menu_data["categories"]
    special = menu_data.get("daily_special")
    promo = menu_data.get("promo_code", "")

    # ── CSS (inline, because of course) ───────────────────────────────────
    html = "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
    html += f"<title>{r['name']} — Menu</title>\n"
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

    # ── Header ────────────────────────────────────────────────────────────
    html += "<div class=\"page-header\">\n"
    html += f"<h1>{r['name']}</h1>\n"
    html += f"<div class=\"subtitle\">Dal {r['since']} a {r['city']}</div>\n"
    html += f"<div class=\"motto\">\"{r['motto']}\"</div>\n"
    html += "</div>\n"

    # ── Accumulators (tangled with rendering below) ───────────────────────
    total_items = 0
    total_stars = 0
    all_ratings = []

    # ── Categories ────────────────────────────────────────────────────────
    for cat in cats:
        # Sort by rating descending (business logic)
        items = sorted(cat["items"], key=lambda x: x["rating"], reverse=True)

        # Category average (business logic)
        avg = sum(i["rating"] for i in items) / len(items)

        html += "<div class=\"category-card\">\n"
        html += "<div class=\"category-header\">\n"
        html += f"<h2>{cat['name']}</h2>\n"
        html += f"<span class=\"avg-badge\">{avg:.1f}</span>\n"
        html += "</div>\n"

        for item in items:
            total_items += 1
            all_ratings.append(item["rating"])

            # ── Price calculation (business logic in rendering loop) ──
            price = item["price"]
            if item["is_special"] and special:
                disc = special.get("discount_pct", 0)
                price = round(item["price"] * (1 - disc / 100), 2)
                _discount_cache[item["name"]] = price

            # ── Star logic (duplicated in footer!) ────────────────────
            is_star = item["rating"] >= _STAR_THRESHOLD
            if is_star:
                total_stars += 1
                star_html = " <span class=\"star-badge\">\u2605 Star Dish</span>"
            else:
                star_html = ""

            # ── Allergen truncation (business logic) ──────────────────
            allergens = item.get("allergens", [])
            if len(allergens) > MAX_ALLERGENS_SHOWN:
                a_display = ", ".join(allergens[:MAX_ALLERGENS_SHOWN]) + f" +{len(allergens) - MAX_ALLERGENS_SHOWN}"
            else:
                a_display = ", ".join(allergens)

            # ── Item HTML ─────────────────────────────────────────────
            html += "<div class=\"menu-item\">\n"
            html += f"<div class=\"item-name\">{item['name']}{star_html}</div>\n"

            if item["is_special"]:
                html += "<div class=\"item-price\">"
                html += f"<span class=\"original-price\">\u20ac{item['price']:.2f}</span>"
                html += f" <span class=\"discount-price\">\u20ac{price:.2f}</span>"
                html += "</div>\n"
            else:
                html += f"<div class=\"item-price\">\u20ac{price:.2f}</div>\n"

            html += f"<div class=\"allergens\">Allergeni: {a_display}</div>\n"

            # ── DALL-E placeholder (only for star dishes) ─────────────
            if ENABLE_IMAGES and is_star:
                img_slug = item["name"].lower().replace(" ", "_")
                img_prompt = f"Hyper-realistic photo of {item['name']}, Italian restaurant, warm natural lighting, appetizing"
                html += f"<div class=\"ai-image\" data-prompt=\"{img_prompt}\">\n"
                html += f"<img src=\"placeholder_{img_slug}.jpg\">\n"
                html += "<p class=\"img-caption\">Ispirazione visiva AI</p>\n"
                html += "</div>\n"

            html += "</div>\n"  # close menu-item

        html += "</div>\n"  # close category-card

    # ── Daily special banner ──────────────────────────────────────────────
    if special:
        disc_price = round(special["original_price"] * (1 - special["discount_pct"] / 100), 2)
        savings = round(special["original_price"] - disc_price, 2)

        html += "<div class=\"special-banner\">\n"
        html += "<div class=\"special-title\">Piatto del Giorno</div>\n"
        html += f"<div class=\"special-dish\">{special['dish']}</div>\n"
        html += "<div class=\"special-pricing\">\n"
        html += f"<span class=\"original-price\">\u20ac{special['original_price']:.2f}</span>\n"
        html += f"<span class=\"discount-price\">\u20ac{disc_price:.2f}</span>\n"
        html += f"<span class=\"savings\">Risparmi \u20ac{savings:.2f}!</span>\n"
        html += "</div>\n"
        if promo:
            html += f"<div class=\"promo-code\">Usa il codice: <strong>{promo}</strong></div>\n"
        html += "</div>\n"

    # ── Stats footer (DUPLICATED star logic — intentional mess) ───────────
    overall_avg = sum(all_ratings) / len(all_ratings) if all_ratings else 0

    # Re-scan for star names (we already counted them above, but here we go again)
    star_names = []
    for c in cats:
        for it in c["items"]:
            if it["rating"] >= 4.7:  # hardcoded, not using _STAR_THRESHOLD!
                star_names.append(it["name"])

    html += "<div class=\"stats-footer\">\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{total_items}</span>\n"
    html += "<span class=\"stat-label\">Piatti</span></div>\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{total_stars}</span>\n"
    html += "<span class=\"stat-label\">Star Dishes</span></div>\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{overall_avg:.1f}</span>\n"
    html += "<span class=\"stat-label\">Media</span></div>\n"
    html += f"<div class=\"stat-item\"><span class=\"stat-value\">{', '.join(star_names)}</span>\n"
    html += "<span class=\"stat-label\">I Nostri Migliori</span></div>\n"
    html += "</div>\n"

    # ── Close ─────────────────────────────────────────────────────────────
    html += "</body>\n</html>\n"
    return html


# ── Direct execution (for manual testing) ────────────────────────────────────
if __name__ == "__main__":
    output = generate_restaurant_page(SAMPLE_MENU)
    with open("output_legacy.html", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Generated {len(output)} chars -> output_legacy.html")
