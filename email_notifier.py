import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import requests
import pytz

from config import FAMILY_RECIPIENT_EMAILS, RDA, STAPLES_LIST_ID, APP_URL, TIMEZONE
from mealie_client import MealieClient
from recipe_nutrition import calculate_nutrition_for_range
from recipe_crawler import check_blackstone_compatibility

def send_email(subject, html_content):
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
        client = MealieClient()
        users = client.get_users()
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

def parse_recipe_details_for_ai(raw_details):
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

def generate_daily_ai_summary(day_name, breakfast, lunch, dinner_title, recipe_details=None, prep_note=None):
    """Call Gemini to generate a brief, friendly daily summary of meals and dinner prep tasks."""
    prompt = f"""You are a helpful, friendly AI kitchen assistant for the Crosty family (Nathan & Kristin).
Generate a brief, warm, and highly actionable daily briefing synopsis for today ({day_name}).

Today's Meals:
- Breakfast: {breakfast}
- Lunch: {lunch}
- Dinner: {dinner_title}
"""
    if recipe_details:
        prompt += f"""
Dinner Recipe Info:
- Name: {recipe_details.get('name')}
- Description: {recipe_details.get('description', '')}
- Ingredients: {', '.join(recipe_details.get('ingredients', []))}
- Instructions: {" ".join(recipe_details.get('instructions', []))[:1000]}
"""
    if prep_note:
        prompt += f"\nSpecific Prep Note for Today's Dinner: {prep_note}\n"

    prompt += """
Write a short synopsis (2-4 sentences max) explaining:
1. A quick, appetizing summary of what they are eating today (breakfast, lunch, dinner).
2. Exactly what needs to be done to prepare tonight's dinner, highlighting any early prep, marinade time, defrosting, or Blackstone griddle batch-cooking/cleanup opportunities identified in the prep notes.

Keep the tone warm, enthusiastic, and concise. Avoid generic fluff. Do not output markdown formatting like bolding or list bullet points, just write it as a natural, cohesive paragraph of text that can be embedded directly in an email body.
"""
    try:
        from gemini_client import call_gemini
        summary = call_gemini(prompt, expect_json=False, temperature=0.5).strip()
        return summary
    except Exception as e:
        print(f"[Email] Failed to generate AI summary: {e}")
        # Return a simple fallback summary
        prep_str = f" Prep: {prep_note}" if prep_note else ""
        return f"Today we have {breakfast} for breakfast, {lunch} for lunch, and {dinner_title} for dinner.{prep_str}"

def build_daily_briefing_html(day_name, date_str, bf, ln, dn_title, dn_recipe, ai_prep_note, today_nutrients, ai_summary, weekly_content_html=None):
    """Build a premium, beautiful HTML email daily briefing."""
    is_blackstone = check_blackstone_compatibility(dn_recipe) if dn_recipe else False
    
    dn_html = dn_title
    if dn_recipe:
        dn_html = f'<a href="https://mealie.cosmoslab.dev/g/home/r/{dn_recipe.get("slug")}" style="color: #E76F51; text-decoration: none; font-weight: bold; border-bottom: 1px dotted #E76F51;">{dn_recipe.get("name")}</a>'

    prep_tip = ""
    if ai_prep_note:
        prep_tip = f"""
        <div style="background-color: #FFF3CD; border-left: 4px solid #FFC107; padding: 15px; border-radius: 6px; margin: 20px 0; font-size: 14px; color: #664D03;">
          📝 <strong>Dinner Prep Instructions:</strong> {ai_prep_note}
        </div>
        """
    elif is_blackstone:
        prep_tip = """
        <div style="background-color: #E8F5E9; border-left: 4px solid #2A9D8F; padding: 15px; border-radius: 6px; margin: 20px 0; font-size: 14px; color: #1B5E20;">
          🍳 <strong>Blackstone Griddle Fired Up!</strong> Tonight's dinner is griddle-ready. Consider batch-cooking proteins or veggies for the coming days while it's hot!
        </div>
        """

    nut_text = ""
    for k, v in today_nutrients.items():
        unit = "g"
        if k == "calories": unit = "kcal"
        elif k in ["sodium", "cholesterol"]: unit = "mg"
        
        target = RDA.get(k, 0.0)
        pct = round((v / target) * 100) if target > 0 else 0
        color = "#2A9D8F"
        if k == "sodium" and pct > 100: color = "#EF5350"
        elif k == "fiber" and pct < 100: color = "#E58325"
        
        nut_text += f"""
        <span style="display: inline-block; margin-right: 10px; margin-bottom: 8px; background: #F1F3F5; padding: 6px 12px; border-radius: 6px; font-size: 13px; border: 1px solid #E9ECEF; color: #495057;">
          <strong>{k.capitalize()}</strong>: {v}{unit} (<span style="color: {color}; font-weight: bold;">{pct}%</span>)
        </span>
        """

    ai_summary_html = ""
    if ai_summary:
        ai_summary_html = f"""
        <div style="background: linear-gradient(135deg, #F4F9F9 0%, #EBF4F5 100%); border-left: 5px solid #2A9D8F; padding: 18px; border-radius: 8px; margin: 20px 0; box-shadow: inset 0 1px 3px rgba(0,0,0,0.02);">
          <p style="margin: 0; font-size: 15px; line-height: 1.6; color: #264653; font-style: italic;">
            " {ai_summary} "
          </p>
        </div>
        """

    html = f"""
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Today's Daily Briefing</title>
      </head>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Inter, Helvetica, Arial, sans-serif; background-color: #F8F9FA; padding: 20px; color: #333; margin: 0;">
        <div style="max-width: 650px; margin: 0 auto; background: white; border-radius: 16px; padding: 30px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); border: 1px solid #E9ECEF;">
          
          <!-- Brand Header -->
          <div style="text-align: center; margin-bottom: 25px; background: linear-gradient(135deg, #264653 0%, #2A9D8F 100%); padding: 20px; border-radius: 12px;">
            <h2 style="color: white; margin: 0; font-size: 22px; font-weight: 700; letter-spacing: 0.5px;">🍽️ Today's Daily Briefing</h2>
            <p style="color: #E0F2F1; margin: 5px 0 0 0; font-size: 14px; font-weight: 500;">{day_name}, {datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")}</p>
          </div>

          <!-- AI Summary Synopsis -->
          {ai_summary_html}

          <!-- Today's Menu Grid -->
          <div style="background-color: #F8F9FA; border-radius: 10px; padding: 20px; margin-bottom: 20px; border: 1px solid #E9ECEF;">
            <h3 style="color: #264653; margin-top: 0; font-size: 16px; border-bottom: 1px solid #E9ECEF; padding-bottom: 8px;">📋 Today's Menu</h3>
            <div style="margin: 15px 0; line-height: 1.5;">
              <p style="font-size: 15px; margin: 8px 0; color: #495057;">☕ <strong>Breakfast:</strong> <span style="color: #212529;">{bf}</span></p>
              <p style="font-size: 15px; margin: 8px 0; color: #495057;">🥗 <strong>Lunch:</strong> <span style="color: #212529;">{ln}</span></p>
              <p style="font-size: 16px; margin: 12px 0 0 0; color: #495057;">🥘 <strong>Dinner:</strong> <span style="font-size: 16px; color: #E76F51; font-weight: bold;">{dn_html}</span></p>
            </div>
          </div>

          <!-- Dinner Prep Instructions -->
          {prep_tip}

          <!-- Today's Nutrition Summary -->
          <div style="margin-top: 25px; border-top: 1px solid #E9ECEF; padding-top: 20px;">
            <h4 style="color: #264653; margin: 0 0 12px 0; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">📊 Daily Nutritional Summary (per person)</h4>
            <div style="line-height: 1.8;">
              {nut_text}
            </div>
          </div>

          <!-- Appended Weekly Summary Content (Saturday only) -->
          {weekly_content_html or ""}
          
          <p style="font-size: 13px; color: #868E96; text-align: center; margin-top: 35px; border-top: 1px solid #F1F3F5; padding-top: 20px;">
            Need to change something? Go to <a href="{APP_URL}" style="color: #2A9D8F; text-decoration: none; font-weight: 600;">Your Dashboard</a> to edit dates, swap dinners, and sync your list instantly.
          </p>
        </div>
      </body>
    </html>
    """
    return html

def send_daily_reminder_email(date_str=None):
    """Generate and send the daily meal briefing email. Defaults to today's date."""
    client = MealieClient()
    if not date_str:
        date_str = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
        
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = dt.strftime("%A")
    except Exception as e:
        print(f"[Email] Error parsing date: {e}")
        return False
        
    # Fetch meal plans for today
    plans = client.get_meal_plan(date_str, date_str)
    if not plans:
        print(f"[Email] No scheduled meals for {date_str}.")
        return False
        
    bf = next((p['title'] for p in plans if p['entryType'] == 'breakfast'), "Staples")
    ln = next((p['title'] for p in plans if p['entryType'] == 'lunch'), "Leftovers")
    
    dinner_item = next((p for p in plans if p['entryType'] == 'dinner'), None)
    dn_title = "Eating Out"
    dn_recipe = None
    ai_prep_note = ""
    
    if dinner_item:
        ai_prep_note = dinner_item.get('text') or ""
        if dinner_item.get('recipeId'):
            try:
                dn_recipe = client.get_recipe_details(dinner_item['recipeId'])
                dn_title = dn_recipe['name']
            except Exception as e:
                print(f"[Email] Error fetching recipe details: {e}")
                dn_title = "Recipe Details Unavailable"
        elif dinner_item.get('title'):
            dn_title = dinner_item['title']

    # Generate AI summary
    parsed_recipe_info = parse_recipe_details_for_ai(dn_recipe) if dn_recipe else None
    ai_summary = generate_daily_ai_summary(day_name, bf, ln, dn_title, parsed_recipe_info, ai_prep_note)
    
    # Nutrition for today
    daily_nutrition, _ = calculate_nutrition_for_range(date_str, date_str)
    today_nutrients = daily_nutrition.get(date_str, {})
    
    # Build HTML
    html = build_daily_briefing_html(
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
    return send_email(subject, html)

def send_saturday_report_email(start_date_str, end_date_str, exclude_text, freezer_items, low_staples_ids, special_requests=""):
    """Send summary of generated meal plan, staples, and weekly average nutrients, prefixed with Saturday's daily briefing."""
    try:
        print(f"[Email] Generating combined Saturday report email for {start_date_str}...")
        client = MealieClient()
        meal_plans = client.get_meal_plan(start_date_str, end_date_str)
        daily_nutrients, averages = calculate_nutrition_for_range(start_date_str, end_date_str)
        
        # 1. Resolve low staples names
        staples = client.get_shopping_list_items(STAPLES_LIST_ID)
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
                        r = client.get_recipe_details(dinner_item['recipeId'])
                        dn = f'<a href="https://mealie.cosmoslab.dev/g/home/r/{r["slug"]}" style="color: #E76F51; text-decoration: none; border-bottom: 1px dotted #E76F51; font-weight:bold;">{r["name"]}</a>'
                    except:
                        dn = "Recipe Details Unavailable"
                elif dinner_item.get('title'):
                    dn = dinner_item['title']
                    
            meal_rows += f"""
            <tr style="border-bottom: 1px solid #E9ECEF;">
              <td style="padding: 12px 10px; font-weight: bold; width: 120px; color: #264653;">{day_name}</td>
              <td style="padding: 12px 10px; color: #495057;">{bf}</td>
              <td style="padding: 12px 10px; color: #495057;">{ln}</td>
              <td style="padding: 12px 10px; color: #E76F51; font-weight: bold;">{dn}</td>
            </tr>
            """

        # 3. Build nutrition table rows for weekly average
        nut_rows = ""
        for k, rda_val in RDA.items():
            avg_val = averages.get(k, 0.0)
            pct = round((avg_val / rda_val) * 100) if rda_val > 0 else 0
            status_color = "#2A9D8F"
            if k == "sodium" and pct > 100:
                status_color = "#EF5350"
            elif k == "fiber" and pct < 100:
                status_color = "#E58325"
                
            unit = "g"
            if k == "calories": unit = "kcal"
            elif k in ["sodium", "cholesterol"]: unit = "mg"
            
            nut_rows += f"""
            <tr style="border-bottom: 1px solid #E9ECEF;">
              <td style="padding: 12px 10px; text-transform: capitalize; color: #495057;">{k}</td>
              <td style="padding: 12px 10px; font-weight: bold; color: #212529;">{avg_val} {unit}</td>
              <td style="padding: 12px 10px; color: #6C757D;">{rda_val} {unit}</td>
              <td style="padding: 12px 10px; font-weight: bold; color: {status_color};">{pct}%</td>
            </tr>
            """

        # Clean up freezer & special requests text
        freezer_str = freezer_items if freezer_items else "None specified"
        special_requests_str = special_requests if special_requests else "None"
        staples_str = f"<br/>* <strong>Low Staples Added</strong>: {', '.join(low_staples_names)}" if low_staples_names else ""
        exclude_text_str = exclude_text if exclude_text else "None"

        # Assemble the appended weekly content HTML
        weekly_content_html = f"""
        <div style="margin-top: 35px; border-top: 2px solid #2A9D8F; padding-top: 25px;">
          <h2 style="color: #264653; font-size: 18px; margin-top: 0; text-align: center; text-transform: uppercase; letter-spacing: 1px;">🗓️ Full Weekly Plan & Shopping List Summary</h2>
          <p style="font-size: 14px; line-height: 1.5; color: #6C757D; text-align: center; margin-bottom: 25px;">
            The active shopping list in Mealie has been populated with ingredients for the week of <strong>{start_date_str} to {end_date_str}</strong>.
          </p>

          <h3 style="color: #264653; border-bottom: 2px solid #E9ECEF; padding-bottom: 6px; font-size: 15px; text-transform: uppercase;">📅 Weekly Calendar</h3>
          <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
            <thead>
              <tr style="background-color: #F8F9FA; text-align: left; border-bottom: 2px solid #DEE2E6;">
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">Day</th>
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">Breakfast</th>
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">Lunch</th>
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">Dinner</th>
              </tr>
            </thead>
            <tbody>
              {meal_rows}
            </tbody>
          </table>
 
          <h3 style="color: #264653; border-bottom: 2px solid #E9ECEF; padding-bottom: 6px; font-size: 15px; text-transform: uppercase; margin-top: 30px;">🥦 Weekly Nutritional Analysis (Family Average)</h3>
          <p style="font-size: 13px; color: #6C757D; margin-top: 0; margin-bottom: 15px;">Calculated daily average per person, including estimated breakfast staples & leftovers.</p>
          <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px;">
            <thead>
              <tr style="background-color: #F8F9FA; text-align: left; border-bottom: 2px solid #DEE2E6;">
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">Nutrient</th>
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">Daily Avg</th>
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">RDA Target</th>
                <th style="padding: 10px; color: #495057; font-size: 13px; text-transform: uppercase;">% Target</th>
              </tr>
            </thead>
            <tbody>
              {nut_rows}
            </tbody>
          </table>
 
          <div style="background-color: #F8F9FA; border-left: 4px solid #2A9D8F; padding: 15px; border-radius: 6px; margin-top: 30px; font-size: 13px; color: #495057; border: 1px solid #E9ECEF;">
            <strong style="color: #264653;">📝 Submission Context:</strong><br/>
            <span style="display:inline-block; margin-top: 5px;">* <strong>Meal Opt-Outs</strong>: {exclude_text_str}</span><br/>
            <span>* <strong>Freezer/Pantry/Fridge Items</strong>: {freezer_str}{staples_str}</span><br/>
            <span>* <strong>Special Requests</strong>: {special_requests_str}</span>
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
                    sat_recipe = client.get_recipe_details(sat_dn_item['recipeId'])
                    sat_dn_title = sat_recipe['name']
                except:
                    sat_dn_title = "Recipe Details Unavailable"
            elif sat_dn_item.get('title'):
                sat_dn_title = sat_dn_item['title']

        # 5. Generate AI Summary for Saturday
        parsed_recipe_info = parse_recipe_details_for_ai(sat_recipe) if sat_recipe else None
        sat_ai_summary = generate_daily_ai_summary("Saturday", sat_bf, sat_ln, sat_dn_title, parsed_recipe_info, sat_prep_note)

        # 6. Saturday Nutrition
        sat_nutrients = daily_nutrients.get(start_date_str, {})

        # 7. Build Combined HTML
        html = build_daily_briefing_html(
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

        send_email(f"🛒 Mealie Shopping List & Plan Ready ({start_date_str})", html)
    except Exception as e:
        print(f"[Email] Failed to generate or send Saturday report email: {e}")
        import traceback
        traceback.print_exc()
