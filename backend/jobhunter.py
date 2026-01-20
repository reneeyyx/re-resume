import os
import time
import random
import logging
import re
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# --- 1. SETUP LOGGING ---
logger = logging.getLogger("JobHunter")
logger.setLevel(logging.INFO)
f_handler = logging.FileHandler('jobhunter.log', encoding='utf-8')
f_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
f_handler.setFormatter(f_format)
c_handler = logging.StreamHandler()
c_handler.setFormatter(f_format)
logger.addHandler(f_handler)
logger.addHandler(c_handler)

# --- 2. CONFIGURATION ---
load_dotenv()
USERNAME = os.getenv("WW_USERNAME")
PASSWORD = os.getenv("WW_PASSWORD")
AUTH_FILE = "auth.json"
ENTRY_URL = "https://waterlooworks.uwaterloo.ca/waterloo.htm"
DASHBOARD_URL_PART = "myAccount/dashboard.htm"

# SETTINGS
MAX_PAGES = 1

def human_delay(min_seconds=1.5, max_seconds=3.5):
    time.sleep(random.uniform(min_seconds, max_seconds))

def perform_login(page, context):
    logger.info("🔒 Initiating Login Sequence...")
    page.goto(ENTRY_URL)
    human_delay(2, 3)

    if "notLoggedIn" in page.url:
        logger.info("⚠️ Detected 'Not Logged In' page. Applying fix...")
        page.get_by_role("link", name="Log Into WaterlooWorks").click()
        human_delay(1, 2)
        page.get_by_role("link", name="Students/Alumni/Staff").click()
        human_delay(2, 4)

    if page.locator("input#userNameInput").is_visible():
        logger.info("📝 Login Form detected. Entering credentials...")
        page.fill("input#userNameInput", USERNAME)
        if page.is_visible("span#nextButton"):
            page.click("span#nextButton")
            human_delay(1, 2)
        page.fill("input#passwordInput", PASSWORD)
        page.click("span#submitButton")
        logger.warning("⚠️ SMS 2FA REQUIRED. Check phone!")
        page.wait_for_url(f"**/{DASHBOARD_URL_PART}", timeout=0) 
        logger.info("✅ Login successful!")

    context.storage_state(path=AUTH_FILE)
    logger.info("💾 Session saved.")

def navigate_to_jobs(page):
    logger.info("🧭 Navigating via Menu...")
    try:
        page.get_by_role("link", name="Co-op Jobs").click()
        #page.get_by_role("link", name="Contract, Part-Time and Volunteer Jobs").click()
        human_delay(1, 2)
        target_link = page.get_by_role("link", name="Full-Cycle Service", exact=True)
        target_link.wait_for(state="visible") 
        target_link.click()
        logger.info("✅ Arrived at Job List page.")
        human_delay(3, 5)
    except Exception as e:
        logger.error(f"❌ Navigation failed: {e}")

def extract_text_sections(html_content):
    """
    Robustly extracts text fields even if they are nested deep in the HTML.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    def get_clean_text(label_keyword):
        # 1. Find the label span (e.g. "Job Summary:")
        # We use a lambda to find it even if there's whitespace around it
        label_span = soup.find("span", class_="label", string=lambda t: t and label_keyword in t)
        
        if not label_span:
            return "Not Found"

        # 2. Find the container div (class="tag__key-value-list")
        # This div contains both the label AND the content <p>
        container = label_span.find_parent("div", class_="tag__key-value-list")
        
        if container:
            # 3. Create a copy so we don't destroy the original soup (if we needed it for other fields)
            # (Though here we are just parsing, so destroying container is fine)
            
            # Remove the label span itself so we don't extract "Job Summary: Job Summary..."
            label_span.decompose()
            
            # 4. Convert <br> tags to newlines so bullet points are preserved
            for br in container.find_all("br"):
                br.replace_with("\n")
            
            # 5. Extract text, stripping whitespace
            text = container.get_text(separator="\n", strip=True)
            
            # Clean up excessive newlines
            return re.sub(r'\n\s*\n', '\n\n', text)
            
        return "Not Found"

    summary = get_clean_text("Job Summary")
    resp = get_clean_text("Job Responsibilities")
    skills = get_clean_text("Required Skills")
    
    return summary, resp, skills

def scrape_current_page(page, page_num):
    logger.info(f"📄 Scanning Page {page_num}...")
    
    try:
        page.wait_for_selector("table tbody tr", timeout=20000)
    except:
        logger.error("❌ Table not found. Skipping page.")
        return []
    
    rows = page.locator("table tbody tr")
    count = rows.count()
    logger.info(f"🔎 Found {count} jobs on this page.")
    
    page_data = []

    for i in range(count):
        row = page.locator("table tbody tr").nth(i)
        
        if not row.locator("a").first.is_visible(): continue

        job_link = row.locator("a").first
        job_title = job_link.inner_text().strip()

        if not job_title: continue

        logger.info(f"[Pg {page_num} | Job {i+1}/{count}] {job_title}")
        
        job_link.scroll_into_view_if_needed()
        human_delay(0.5, 1)
        job_link.click()

        close_btn = page.get_by_role("button", name="Close")
        
        try:
            close_btn.wait_for(state="visible", timeout=8000)
            
            # POLLING FIX FOR ID
            job_id = "N/A"
            header_loc = page.locator("div.dashboard-header__posting-title")
            
            for attempt in range(10): 
                if header_loc.is_visible():
                    text = header_loc.inner_text()
                    match = re.search(r'(\d{6})', text)
                    if match:
                        job_id = match.group(1)
                        break
                try:
                    body_id = page.locator("tr", has_text="Job ID").locator("td").last
                    if body_id.is_visible() and re.search(r'\d{6}', body_id.inner_text()):
                        job_id = re.search(r'(\d{6})', body_id.inner_text()).group(1)
                        break
                except: pass
                time.sleep(0.5)
            
            # Extract Content
            html = page.content()
            summary, resp, skills = extract_text_sections(html)
            
            # Fallback Check: If summary is "Not Found", verify if we are scraping too fast
            if summary == "Not Found" and job_id != "N/A":
                logger.warning(f"⚠️ Text empty for {job_title}. Retrying extraction...")
                time.sleep(1) # Give it one more second
                html = page.content()
                summary, resp, skills = extract_text_sections(html)

            page_data.append({
                "Job ID": job_id,
                "Job Title": job_title,
                "Summary": summary,
                "Responsibilities": resp,
                "Skills": skills
            })

        except Exception as e:
            logger.warning(f"⚠️ Popup error: {e}")

        if close_btn.is_visible():
            close_btn.click()
        else:
            page.keyboard.press("Escape")
            
        human_delay(1, 2)

    return page_data

def scrape_all_pages(page):
    logger.info("Attempting to switch to 'All Jobs' view...")
    try:
        all_jobs_btn = page.get_by_role("button", name="All Jobs")
        if all_jobs_btn.is_visible():
            all_jobs_btn.click()
            human_delay(4, 6) 
    except: pass

    # --- LOG TOTAL RESULTS ---
    try:
        result_div = page.locator("div.table--view__pagination--data", has_text="results")
        if result_div.is_visible():
            text = result_div.inner_text().replace('\n', ' ')
            match = re.search(r'(\d+)\s*results', text)
            if match:
                logger.info(f"📊 TOTAL JOBS FOUND: {match.group(1)}")
    except: pass

    all_jobs_master = []
    current_page = 1

    while current_page <= MAX_PAGES:
        data = scrape_current_page(page, current_page)
        all_jobs_master.extend(data)
        
        logger.info("👀 Checking for next page...")
        next_btn = page.locator("a[aria-label='Go to next page']")
        
        if next_btn.is_visible():
            classes = next_btn.get_attribute("class") or ""
            if "disabled" in classes:
                logger.info("🛑 'Next' button is disabled. End of list.")
                break
            else:
                logger.info(f"➡️ Clicking Next... Moving to Page {current_page + 1}")
                next_btn.click()
                time.sleep(5) 
                current_page += 1
        else:
            logger.info("🛑 'Next' button not found. End of list.")
            break

    # --- SAVE ---
    if all_jobs_master:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"scraped_jobs_{ts}.xlsx"
        
        df = pd.DataFrame(all_jobs_master)
        df['Job ID'] = df['Job ID'].astype(str)
        df.to_excel(output_file, index=False)
        
        logger.info(f"🎉 DONE! Saved {len(all_jobs_master)} jobs to: {output_file}")
    else:
        logger.warning("⚠️ No jobs extracted.")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = None
        
        if os.path.exists(AUTH_FILE):
            logger.info("📂 Loading session...")
            context = browser.new_context(storage_state=AUTH_FILE)
            page = context.new_page()
            try:
                page.goto(f"https://waterlooworks.uwaterloo.ca/{DASHBOARD_URL_PART}")
                human_delay(2, 3)
                if "notLoggedIn" in page.url: raise Exception("Expired")
            except:
                context.close()
                context = browser.new_context()
                page = context.new_page()
                perform_login(page, context)
        else:
            context = browser.new_context()
            page = context.new_page()
            perform_login(page, context)

        if "jobs.htm" not in page.url:
            navigate_to_jobs(page)
            
        scrape_all_pages(page)
        
        logger.info("✅ Closing browser.")
        browser.close()

if __name__ == "__main__":
    main()