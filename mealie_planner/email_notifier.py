import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import requests
import pytz

from .config import FAMILY_RECIPIENT_EMAILS, RDA, STAPLES_LIST_ID, APP_URL, TIMEZONE
from .recipe_crawler import RecipeCrawler
from .recipe_nutrition import RecipeNutrition

class EmailNotifier:
    def __init__(self, mealie_client, gemini_client):
        self.client = mealie_client
        self.gemini = gemini_client
        self.crawler = RecipeCrawler(mealie_client, gemini_client)
        self.nutrition = RecipeNutrition(mealie_client, gemini_client)

    def send_email(self, subject, html_content):
        """Send an email using SMTP settings."""
        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASSWORD')
        from_email = os.getenv('SMTP_FROM_EMAIL')
        from_name = os.getenv('SMTP_FROM_NAME', 'Mealie Planner')

        if not smtp_user or not smtp_pass:
            print("SMTP settings are missing. Cannot send email.")
            return False

        # Fetch recipients dynamically from all registered Mealie users
        recipients = []
        try:
            users = self.client.get_users()
            recipients = [u.get('email') for u in users if u.get('email')]
            if recipients:
                print(f"[Email] Dynamically loaded recipients from Mealie: {recipients}")
        except Exception as e:
            print(f"[Email] Could not fetch Mealie users, falling back to static list: {e}")
            recipients = FAMILY_RECIPIENT_EMAILS

        if not recipients:
            print("No recipient emails found. Cannot send email.")
            return False

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{from_name} <{from_email}>"
        msg['To'] = ", ".join(recipients)

        msg.attach(MIMEText(html_content, 'html'))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_email, recipients, msg.as_string())
            print(f"Successfully sent email: '{subject}' to {recipients}")
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False

    def parse_recipe_details_for_ai(self, raw_details):
        """Extract and format ingredients and instructions for the AI prompt from raw details."""
        if not raw_details:
            return None
        ingredients = []
        for ing in raw_details.get('recipeIngredient', []):
            note = ing.get('note') or ""
            orig = ing.get('originalText') or ""
            ing_text = f"{note} {orig}".strip()
            if ing_text:
                ingredients.append(ing_text)
                
        instructions = [i.get('text', '') for i in raw_details.get('recipeInstructions', []) if i.get('text')]
        
        return {
            "name": raw_details.get("name"),
            "description": raw_details.get("description"),
            "ingredients": ingredients,
            "instructions": instructions
        }

    def generate_daily_ai_summary(self, day_name, breakfast, lunch, dinner_title, recipe_details=None, prep_note=None, tomorrow_title=None, tomorrow_recipe_details=None, tomorrow_prep_note=None):
        """Call Gemini to generate a brief, practical daily kitchen briefing of the day's meals."""
        prompt = f"""You are a professional culinary assistant writing a brief, practical daily kitchen briefing.
Write a clean, appetizing, but grounded menu summary and preparation guide for today ({day_name}).

Today's Menu:
- Breakfast: {breakfast}
- Lunch: {lunch}
- Dinner: {dinner_title}

Today's Dinner details:
- Recipe description: {recipe_details.get('description', '') if recipe_details else ''}
- Ingredients: {', '.join(recipe_details.get('ingredients', [])) if recipe_details else ''}
- Instructions: {" ".join(recipe_details.get('instructions', []))[:1000] if recipe_details else ''}
- Manual Prep Note: {prep_note or ''}
"""
        if tomorrow_title:
            prompt += f"""
Tomorrow's Dinner details:
- Name: {tomorrow_title}
- Tomorrow's Instructions: {" ".join(tomorrow_recipe_details.get('instructions', []))[:1000] if tomorrow_recipe_details else ''}
- Tomorrow's Manual Prep Note: {tomorrow_prep_note or ''}
"""

        prompt += """
Guidelines for the briefing:
1. **Breakfast & Lunch**: Briefly state what is planned.
2. **Today's Dinner & Practical Advice**: Describe today's dinner, focusing on flavor expectations, assembly, and practical watch-outs (e.g. cooking tips, doneness cues, griddle control, or prep steps).
3. **Next-Day Prep**: Look ONLY at "Tomorrow's Dinner details" (instructions or prep notes) to see if there are prep tasks that should be started *today* (like thawing meat, marinating overnight, or prepping components ahead). If so, explicitly advise doing them today for tomorrow's dinner. Do NOT associate today's manual prep notes or today's salad prep with tomorrow's dinner name. If no next-day prep is needed for tomorrow, omit this entirely.
4. **Style/Tone**: Practical, grounded, and concise. No greetings, names ("Nathan", "Kristin"), emojis, or markdown. Keep it under 110 words in a single cohesive paragraph.
"""
        try:
            summary = self.gemini.call(prompt, expect_json=False, temperature=0.4).strip()
            return summary
        except Exception as e:
            print(f"[Email] Failed to generate AI summary: {e}")
            prep_str = f" Prep: {prep_note}" if prep_note else ""
            return f"Today we have {breakfast} for breakfast, {lunch} for lunch, and {dinner_title} for dinner.{prep_str}"

    def generate_weekly_themes_summary(self, meal_plans, start_date_str, end_date_str):
        """Call Gemini to generate a brief summary and thematic analysis of the upcoming week's meals."""
        dinners = []
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        for i in range(7):
            curr = start_date + timedelta(days=i)
            d_str = curr.strftime("%Y-%m-%d")
            day_name = curr.strftime("%A")
            dinner_item = next((p for p in meal_plans if p['date'] == d_str and p['entryType'] == 'dinner'), None)
            title = "Eating Out"
            if dinner_item:
                title = dinner_item.get('title') or ""
                if dinner_item.get('recipeId') and not title:
                    try:
                        r = self.client.get_recipe_details(dinner_item['recipeId'])
                        title = r['name']
                    except:
                        title = "Recipe Details Unavailable"
            dinners.append(f"- {day_name}: {title}")
            
        dinners_str = "\n".join(dinners)
        
        prompt = f"""You are a professional menu planner and culinary trend analyst.
Analyze the upcoming weekly dinner menu for the Crosty family and write a brief, sophisticated synopsis (2-3 sentences) of the week's themes, culinary styles, or ingredient trends (e.g. griddle-focused, Mediterranean accents, comfort food classics, or quick weekday stir-fries).

Weekly Dinner Menu:
{dinners_str}

Guidelines:
1. Identify 1 or 2 prominent culinary trends, themes, or core ingredients repeating in the menu.
2. Keep the tone sophisticated, warm, and highly engaging.
3. Absolutely no greetings, names, markdown formatting, or emojis.
4. Keep it under 60 words.
"""
        try:
            return self.gemini.call(prompt, expect_json=False, temperature=0.5).strip().strip('"').strip("'")
        except Exception as e:
            print(f"[Email] Failed to generate weekly themes summary: {e}")
            return "A diverse week of planned dinners, highlighting fresh ingredients and easy-to-cook recipes."

    def build_daily_briefing_html(self, day_name, date_str, bf, ln, dn_title, dn_recipe, ai_prep_note, today_nutrients, ai_summary, weekly_content_html=None):
        """Build a premium, beautiful HTML email daily briefing."""
        is_blackstone = self.crawler.check_blackstone_compatibility(dn_recipe) if dn_recipe else False
        
        dn_html = dn_title
        if dn_recipe:
            dn_html = f'<a href="https://mealie.cosmoslab.dev/g/home/r/{dn_recipe.get("slug")}" style="color: #3C5A54; text-decoration: none; font-weight: bold; border-bottom: 1px dotted #3C5A54;">{dn_recipe.get("name")}</a>'

        prep_tip = ""
        if ai_prep_note:
            prep_tip = f"""
            <div style="background-color: #FAF9F6; border-left: 2px solid #C66B3D; padding: 16px 20px; border-radius: 4px; margin: 24px 0; font-size: 14px; color: #5C5247; border: 1px solid #EFECE6; font-family: 'Plus Jakarta Sans', sans-serif;">
              <strong style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 700; color: #C66B3D; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 6px;">Kitchen Preparation</strong>
              <span style="line-height: 1.5; display: block;">{ai_prep_note}</span>
            </div>
            """
        elif is_blackstone:
            prep_tip = """
            <div style="background-color: #F6FAF9; border-left: 2px solid #3C5A54; padding: 16px 20px; border-radius: 4px; margin: 24px 0; font-size: 14px; color: #354743; border: 1px solid #E6EFEF; font-family: 'Plus Jakarta Sans', sans-serif;">
              <strong style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 700; color: #3C5A54; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 6px;">Blackstone Griddle Fired Up</strong>
              <span style="line-height: 1.5; display: block;">Tonight's dinner is compatible with the Blackstone. Consider batch-cooking proteins or vegetables to save prep time later in the week.</span>
            </div>
            """

        nut_text = ""
        for k, v in today_nutrients.items():
            unit = "g"
            if k == "calories": unit = "kcal"
            elif k in ["sodium", "cholesterol"]: unit = "mg"
            
            target = RDA.get(k, 0.0)
            pct = round((v / target) * 100) if target > 0 else 0
            color = "#3C5A54"
            if k == "sodium" and pct > 100: color = "#EF5350"
            elif k == "fiber" and pct < 100: color = "#C66B3D"
            
            nut_text += f"""
            <span style="display: inline-block; margin: 4px 6px; background: #FAF9F6; padding: 6px 12px; border-radius: 4px; font-size: 12px; border: 1px solid #EFECE6; color: #5C5247; font-family: 'Plus Jakarta Sans', sans-serif;">
              <strong style="color: #3C5A54;">{k.capitalize()}</strong>: {v}{unit} &bull; <span style="color: {color}; font-weight: 700;">{pct}%</span>
            </span>
            """

        ai_summary_html = ""
        if ai_summary:
            clean_summary = ai_summary.strip().strip('"').strip("'")
            ai_summary_html = f"""
            <div style="margin: 24px 0; padding: 0 10px;">
              <p style="margin: 0; font-family: 'Playfair Display', Georgia, serif; font-size: 16px; line-height: 1.7; color: #2C2C2C; font-style: italic; text-align: center;">
                "{clean_summary}"
              </p>
            </div>
            <div style="text-align: center; margin: 20px 0;"><span style="color: #D5CEB8; font-size: 14px;">❖ ❖ ❖</span></div>
            """

        html = f"""
        <html>
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,700;1,400&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
            <title>Today's Culinary Briefing</title>
          </head>
          <body style="font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background-color: #F4F0EB; padding: 20px; color: #2C2C2C; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 4px 20px rgba(46, 33, 23, 0.05); border: 1px solid #E6DFD5;">
              
              <!-- Brand Header -->
              <div style="text-align: center; padding: 24px 0 16px 0; border-bottom: 1px double #D5CEB8; margin-bottom: 24px;">
                <span style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 700; color: #C66B3D; text-transform: uppercase; letter-spacing: 2px; display: block; margin-bottom: 6px;">Daily Briefing</span>
                <h1 style="font-family: 'Playfair Display', Georgia, serif; color: #3C5A54; margin: 0; font-size: 28px; font-weight: 700; font-style: italic; line-height: 1.2;">The Crosty Kitchen</h1>
                <p style="font-family: 'Plus Jakarta Sans', sans-serif; color: #8C8273; margin: 8px 0 0 0; font-size: 13px; font-weight: 500; letter-spacing: 0.5px;">{day_name} &bull; {datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")}</p>
              </div>

              <!-- AI Summary Synopsis -->
              {ai_summary_html}

              <!-- Today's Menu -->
              <div style="margin-bottom: 30px; padding: 0 10px;">
                <h2 style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 12px; font-weight: 700; color: #C66B3D; text-transform: uppercase; letter-spacing: 1.5px; text-align: center; margin-bottom: 20px; margin-top: 0;">Today's Menu</h2>
                
                <div style="margin-bottom: 20px; text-align: center;">
                  <span style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 600; color: #8C8273; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 2px;">Breakfast</span>
                  <span style="font-family: 'Playfair Display', Georgia, serif; font-size: 16px; color: #2C2C2C; font-weight: 500;">{bf}</span>
                </div>

                <div style="margin-bottom: 20px; text-align: center;">
                  <span style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 600; color: #8C8273; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 2px;">Lunch</span>
                  <span style="font-family: 'Playfair Display', Georgia, serif; font-size: 16px; color: #2C2C2C; font-weight: 500;">{ln}</span>
                </div>

                <div style="margin-bottom: 20px; text-align: center;">
                  <span style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 600; color: #8C8273; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 2px;">Dinner</span>
                  <span style="font-family: 'Playfair Display', Georgia, serif; font-size: 20px; color: #3C5A54; font-weight: 700; display: block;">{dn_html}</span>
                </div>
              </div>

              <!-- Dinner Prep Instructions -->
              {prep_tip}

              <!-- Today's Nutrition Summary -->
              <div style="margin-top: 30px; border-top: 1px double #D5CEB8; padding-top: 20px;">
                <h3 style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 11px; font-weight: 700; color: #8C8273; text-transform: uppercase; letter-spacing: 1.5px; text-align: center; margin-bottom: 16px; margin-top: 0;">Daily Nutritional Analysis</h3>
                <div style="text-align: center; line-height: 2;">
                  {nut_text}
                </div>
              </div>

              <!-- Appended Weekly Summary Content (Saturday only) -->
              {weekly_content_html or ""}
              
              <p style="font-size: 13px; color: #8C8273; text-align: center; margin-top: 35px; border-top: 1px solid #EFECE6; padding-top: 20px; font-family: 'Plus Jakarta Sans', sans-serif;">
                Need to change something? Go to <a href="{APP_URL}" style="color: #3C5A54; text-decoration: none; font-weight: 600; border-bottom: 1px dotted #3C5A54;">Your Dashboard</a> to edit dates, swap dinners, and sync your list instantly.
              </p>
            </div>
          </body>
        </html>
        """
        return html

    def send_daily_reminder_email(self, date_str=None):
        """Generate and send the daily meal briefing email. Defaults to today's date."""
        if not date_str:
            date_str = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
            
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            day_name = dt.strftime("%A")
            tomorrow_dt = dt + timedelta(days=1)
            tomorrow_str = tomorrow_dt.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"[Email] Error parsing date: {e}")
            return False
            
        # Fetch meal plans for today and tomorrow
        plans = self.client.get_meal_plan(date_str, tomorrow_str)
        if not plans:
            print(f"[Email] No scheduled meals for {date_str}.")
            return False
            
        bf = next((p['title'] for p in plans if p['date'] == date_str and p['entryType'] == 'breakfast'), "Staples")
        ln = next((p['title'] for p in plans if p['date'] == date_str and p['entryType'] == 'lunch'), "Leftovers")
        
        dinner_item = next((p for p in plans if p['date'] == date_str and p['entryType'] == 'dinner'), None)
        dn_title = "Eating Out"
        dn_recipe = None
        ai_prep_note = ""
        
        if dinner_item:
            ai_prep_note = dinner_item.get('text') or ""
            if dinner_item.get('recipeId'):
                try:
                    dn_recipe = self.client.get_recipe_details(dinner_item['recipeId'])
                    dn_title = dn_recipe['name']
                except Exception as e:
                    print(f"[Email] Error fetching recipe details: {e}")
                    dn_title = "Recipe Details Unavailable"
            elif dinner_item.get('title'):
                dn_title = dinner_item['title']

        # Tomorrow's dinner details for next-day prep notes
        tomorrow_dinner_item = next((p for p in plans if p['date'] == tomorrow_str and p['entryType'] == 'dinner'), None)
        tomorrow_title = "None scheduled"
        tomorrow_recipe = None
        tomorrow_prep_note = ""
        if tomorrow_dinner_item:
            tomorrow_prep_note = tomorrow_dinner_item.get('text') or ""
            if tomorrow_dinner_item.get('recipeId'):
                try:
                    tomorrow_recipe = self.client.get_recipe_details(tomorrow_dinner_item['recipeId'])
                    tomorrow_title = tomorrow_recipe['name']
                except:
                    tomorrow_title = "Recipe Details Unavailable"
            elif tomorrow_dinner_item.get('title'):
                tomorrow_title = tomorrow_dinner_item['title']

        # Generate AI summary
        parsed_recipe_info = self.parse_recipe_details_for_ai(dn_recipe) if dn_recipe else None
        parsed_tomorrow_recipe_info = self.parse_recipe_details_for_ai(tomorrow_recipe) if tomorrow_recipe else None
        ai_summary = self.generate_daily_ai_summary(
            day_name=day_name,
            breakfast=bf,
            lunch=ln,
            dinner_title=dn_title,
            recipe_details=parsed_recipe_info,
            prep_note=ai_prep_note,
            tomorrow_title=tomorrow_title,
            tomorrow_recipe_details=parsed_tomorrow_recipe_info,
            tomorrow_prep_note=tomorrow_prep_note
        )
        
        # Nutrition for today
        daily_nutrition, _ = self.nutrition.calculate_nutrition_for_range(date_str, date_str)
        today_nutrients = daily_nutrition.get(date_str, {})
        
        # Build HTML
        html = self.build_daily_briefing_html(
            day_name=day_name,
            date_str=date_str,
            bf=bf,
            ln=ln,
            dn_title=dn_title,
            dn_recipe=dn_recipe,
            ai_prep_note=ai_prep_note,
            today_nutrients=today_nutrients,
            ai_summary=ai_summary
        )
        
        subject = f"🍽️ Today's Meal Plan: {dn_title} ({day_name})"
        return self.send_email(subject, html)

    def send_saturday_report_email(self, start_date_str, end_date_str, exclude_text, freezer_items, low_staples_ids, special_requests=""):
        """Send summary of generated meal plan, staples, and weekly average nutrients, prefixed with Saturday's daily briefing."""
        try:
            print(f"[Email] Generating combined Saturday report email for {start_date_str}...")
            meal_plans = self.client.get_meal_plan(start_date_str, end_date_str)
            daily_nutrients, averages = self.nutrition.calculate_nutrition_for_range(start_date_str, end_date_str)
            
            # 1. Resolve low staples names
            staples = self.client.get_shopping_list_items(STAPLES_LIST_ID)
            staple_id_map = {item['id'].replace('-', ''): item['note'] for item in staples}
            low_staples_names = []
            for s_id in low_staples_ids:
                note = staple_id_map.get(s_id.replace('-', ''))
                if note:
                    low_staples_names.append(note)

            # 2. Build scheduled meals rows for the weekly calendar
            meal_rows = ""
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            for i in range(7):
                curr = start_date + timedelta(days=i)
                d_str = curr.strftime("%Y-%m-%d")
                day_name = curr.strftime("%A")
                
                bf = next((p['title'] for p in meal_plans if p['date'] == d_str and p['entryType'] == 'breakfast'), "Staples")
                ln = next((p['title'] for p in meal_plans if p['date'] == d_str and p['entryType'] == 'lunch'), "Leftovers")
                
                # Dinner recipe name
                dinner_item = next((p for p in meal_plans if p['date'] == d_str and p['entryType'] == 'dinner'), None)
                dn = "Eating Out"
                if dinner_item:
                    if dinner_item.get('recipeId'):
                        try:
                            r = self.client.get_recipe_details(dinner_item['recipeId'])
                            dn = f'<a href="https://mealie.cosmoslab.dev/g/home/r/{r["slug"]}" style="color: #C66B3D; text-decoration: none; border-bottom: 1px dotted #C66B3D; font-weight:bold;">{r["name"]}</a>'
                        except:
                            dn = "Recipe Details Unavailable"
                    elif dinner_item.get('title'):
                        dn = dinner_item['title']
                        
                meal_rows += f"""
                <tr style="border-bottom: 1px solid #EFECE6;">
                  <td style="padding: 12px 10px; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px; font-weight: bold; width: 120px; color: #3C5A54;">{day_name}</td>
                  <td style="padding: 12px 10px; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px; color: #5C5247;">{bf}</td>
                  <td style="padding: 12px 10px; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px; color: #5C5247;">{ln}</td>
                  <td style="padding: 12px 10px; font-family: 'Playfair Display', Georgia, serif; font-size: 14px; font-weight: bold; color: #C66B3D;">{dn}</td>
                </tr>
                """

            # 3. Build nutrition table rows for weekly average
            nut_rows = ""
            for k, rda_val in RDA.items():
                avg_val = averages.get(k, 0.0)
                pct = round((avg_val / rda_val) * 100) if rda_val > 0 else 0
                status_color = "#3C5A54"
                if k == "sodium" and pct > 100:
                    status_color = "#EF5350"
                elif k == "fiber" and pct < 100:
                    status_color = "#C66B3D"
                    
                unit = "g"
                if k == "calories": unit = "kcal"
                elif k in ["sodium", "cholesterol"]: unit = "mg"
                
                nut_rows += f"""
                <tr style="border-bottom: 1px solid #EFECE6;">
                  <td style="padding: 12px 10px; text-transform: capitalize; color: #5C5247; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px;">{k}</td>
                  <td style="padding: 12px 10px; font-weight: bold; color: #2C2C2C; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px;">{avg_val} {unit}</td>
                  <td style="padding: 12px 10px; color: #8C8273; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px;">{rda_val} {unit}</td>
                  <td style="padding: 12px 10px; font-weight: bold; color: {status_color}; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px;">{pct}%</td>
                </tr>
                """

            # Clean up freezer & special requests text
            freezer_str = freezer_items if freezer_items else "None specified"
            special_requests_str = special_requests if special_requests else "None"
            staples_str = f"<br/>&bull; <strong>Low Staples Added</strong>: {', '.join(low_staples_names)}" if low_staples_names else ""
            exclude_text_str = exclude_text if exclude_text else "None"

            # Generate weekly thematic analysis
            weekly_themes = self.generate_weekly_themes_summary(meal_plans, start_date_str, end_date_str)

            # Assemble the appended weekly content HTML
            weekly_content_html = f"""
            <div style="margin-top: 35px; border-top: 2px double #D5CEB8; padding-top: 25px;">
              <h2 style="color: #3C5A54; font-family: 'Playfair Display', Georgia, serif; font-style: italic; font-size: 20px; margin-top: 0; text-align: center; letter-spacing: 0.5px;">Weekly Plan & Shopping Summary</h2>
              <p style="font-size: 14px; line-height: 1.5; color: #8C8273; text-align: center; margin-bottom: 25px; font-family: 'Plus Jakarta Sans', sans-serif;">
                The active shopping list in Mealie has been populated with ingredients for the week of <strong>{start_date_str} to {end_date_str}</strong>.
              </p>

              <!-- Weekly Themes Synopsis -->
              <div style="background-color: #FAF9F6; border-left: 2px solid #3C5A54; padding: 16px 20px; border-radius: 4px; margin: 20px 0; font-size: 14px; color: #5C5247; border: 1px solid #EFECE6; font-family: 'Plus Jakarta Sans', sans-serif;">
                <strong style="color: #3C5A54; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 6px;">Week in Review & Culinary Themes</strong>
                <span style="line-height: 1.5; font-style: italic; display: block;">"{weekly_themes}"</span>
              </div>

              <h3 style="color: #3C5A54; border-bottom: 1px solid #EFECE6; padding-bottom: 6px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif; margin-top: 30px;">📅 Weekly Calendar</h3>
              <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
                <thead>
                  <tr style="background-color: #FAF9F6; text-align: left; border-bottom: 2px solid #EFECE6;">
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">Day</th>
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">Breakfast</th>
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">Lunch</th>
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">Dinner</th>
                  </tr>
                </thead>
                <tbody>
                  {meal_rows}
                </tbody>
              </table>
     
              <h3 style="color: #3C5A54; border-bottom: 1px solid #EFECE6; padding-bottom: 6px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif; margin-top: 30px;">🥦 Weekly Nutritional Analysis (Family Average)</h3>
              <p style="font-size: 13px; color: #8C8273; margin-top: 0; margin-bottom: 15px; font-family: 'Plus Jakarta Sans', sans-serif;">Calculated daily average per person, including estimated breakfast staples & leftovers.</p>
              <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
                <thead>
                  <tr style="background-color: #FAF9F6; text-align: left; border-bottom: 2px solid #EFECE6;">
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">Nutrient</th>
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">Daily Avg</th>
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">RDA Target</th>
                    <th style="padding: 10px; color: #3C5A54; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; font-family: 'Plus Jakarta Sans', sans-serif;">% Target</th>
                  </tr>
                </thead>
                <tbody>
                  {nut_rows}
                </tbody>
              </table>
     
              <div style="background-color: #FAF9F6; border-left: 2px solid #C66B3D; padding: 16px 20px; border-radius: 4px; margin-top: 30px; font-size: 13px; color: #5C5247; border: 1px solid #EFECE6; font-family: 'Plus Jakarta Sans', sans-serif;">
                <strong style="color: #C66B3D; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 6px;">Submission Context</strong>
                <span style="display:inline-block; margin-top: 5px;">&bull; <strong>Meal Opt-Outs</strong>: {exclude_text_str}</span><br/>
                <span>&bull; <strong>Freezer/Pantry/Fridge Items</strong>: {freezer_str}{staples_str}</span><br/>
                <span>&bull; <strong>Special Requests</strong>: {special_requests_str}</span>
              </div>
            </div>
            """

            # 4. Fetch Saturday's Menu for the prefix Daily Briefing
            sat_bf = next((p['title'] for p in meal_plans if p['date'] == start_date_str and p['entryType'] == 'breakfast'), "Staples")
            sat_ln = next((p['title'] for p in meal_plans if p['date'] == start_date_str and p['entryType'] == 'lunch'), "Leftovers")
            sat_dn_item = next((p for p in meal_plans if p['date'] == start_date_str and p['entryType'] == 'dinner'), None)
            sat_dn_title = "Eating Out"
            sat_recipe = None
            sat_prep_note = ""
            if sat_dn_item:
                sat_prep_note = sat_dn_item.get('text') or ""
                if sat_dn_item.get('recipeId'):
                    try:
                        sat_recipe = self.client.get_recipe_details(sat_dn_item['recipeId'])
                        sat_dn_title = sat_recipe['name']
                    except:
                        sat_dn_title = "Recipe Details Unavailable"
                elif sat_dn_item.get('title'):
                    sat_dn_title = sat_dn_item['title']

            # Sunday (tomorrow) details for Saturday's daily briefing prefix next-day prep notes
            sun_dt_str = (start_date + timedelta(days=1)).strftime("%Y-%m-%d")
            sun_dn_item = next((p for p in meal_plans if p['date'] == sun_dt_str and p['entryType'] == 'dinner'), None)
            sun_dn_title = "Eating Out"
            sun_recipe = None
            sun_prep_note = ""
            if sun_dn_item:
                sun_prep_note = sun_dn_item.get('text') or ""
                if sun_dn_item.get('recipeId'):
                    try:
                        sun_recipe = self.client.get_recipe_details(sun_dn_item['recipeId'])
                        sun_dn_title = sun_recipe['name']
                    except:
                        sun_dn_title = "Recipe Details Unavailable"
                elif sun_dn_item.get('title'):
                    sun_dn_title = sun_dn_item['title']

            # 5. Generate AI Summary for Saturday, including tomorrow's prep details
            parsed_recipe_info = self.parse_recipe_details_for_ai(sat_recipe) if sat_recipe else None
            parsed_sun_recipe_info = self.parse_recipe_details_for_ai(sun_recipe) if sun_recipe else None
            sat_ai_summary = self.generate_daily_ai_summary(
                day_name="Saturday",
                breakfast=sat_bf,
                lunch=sat_ln,
                dinner_title=sat_dn_title,
                recipe_details=parsed_recipe_info,
                prep_note=sat_prep_note,
                tomorrow_title=sun_dn_title,
                tomorrow_recipe_details=parsed_sun_recipe_info,
                tomorrow_prep_note=sun_prep_note
            )

            # 6. Saturday Nutrition
            sat_nutrients = daily_nutrients.get(start_date_str, {})

            # 7. Build Combined HTML
            html = self.build_daily_briefing_html(
                day_name="Saturday",
                date_str=start_date_str,
                bf=sat_bf,
                ln=sat_ln,
                dn_title=sat_dn_title,
                dn_recipe=sat_recipe,
                ai_prep_note=sat_prep_note,
                today_nutrients=sat_nutrients,
                ai_summary=sat_ai_summary,
                weekly_content_html=weekly_content_html
            )

            self.send_email(f"🛒 Mealie Shopping List & Plan Ready ({start_date_str})", html)
        except Exception as e:
            print(f"[Email] Failed to generate or send Saturday report email: {e}")
            import traceback
            traceback.print_exc()

def send_daily_reminder_email(date_str=None):
    from .mealie_client import MealieClient
    from .gemini_client import GeminiClient
    client = MealieClient()
    gemini = GeminiClient()
    notifier = EmailNotifier(client, gemini)
    return notifier.send_daily_reminder_email(date_str)
