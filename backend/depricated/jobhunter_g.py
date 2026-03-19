import os
import time
import random
import logging
import re
import argparse
import pandas as pd
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError

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
JOBS_PER_PAGE_GUESS = 50 
MAX_PAGES = 300 

def parse_arguments():
    parser = argparse.ArgumentParser(description="WaterlooWorks Job Scraper")
    parser.add_argument("-o", "--output", type=str, default="scraped_jobs.xlsx", help="Output filename")
    return parser.parse_args()

def human_delay(min_seconds=1.5, max_seconds=3.5):
    time.sleep(random.uniform(min_seconds, max_seconds))

def handle_keep_alive(page):
    try:
        modal = page.locator("#keepMeLoggedInModal")
        if modal.is_visible():
            logger.warning("🚨 Session Popup detected! Extending session...")
            btn = modal.locator("button", has_text=re.compile("Keep|Log|Continue", re.IGNORECASE))
            if btn.is_visible():
                btn.first.click()
            else:
                modal.locator("button").first.click()
            modal.wait_for(state="hidden", timeout=5000)
            logger.info("✅ Session extended.")
            return True
    except Exception:
        pass
    return False

def perform_login(page, context):
    logger.info("🔒 Initiating Login Sequence...")
    page.goto(ENTRY_URL)
    human_delay(2, 3)
    if "notLoggedIn" in page.url:
        page.get_by_role("link", name="Log Into WaterlooWorks").click()
        human_delay(1, 2)
        page.get_by_role("link", name="Students/Alumni/Staff").click()
        human_delay(2, 4)
    if page.locator("input#userNameInput").is_visible():
        page.fill("input#userNameInput", USERNAME)
        if page.is_visible("span#nextButton"):
            page.click("span#nextButton")
            human_delay(1, 2)
        page.fill("input#passwordInput", PASSWORD)
        page.click("span#submitButton")
        page.wait_for_url(f"**/{DASHBOARD_URL_PART}", timeout=0) 
        logger.info("✅ Login successful!")
    context.storage_state(path=AUTH_FILE)

def navigate_to_jobs(page):
    logger.info("🧭 Navigating via Menu...")
    try:
        page.get_by_role("link", name="Co-op Jobs").click()
        human_delay(1, 2)
        target_link = page.get_by_role("link", name="Full-Cycle Service", exact=True)
        target_link.wait_for(state="visible") 
        target_link.click()
        logger.info("✅ Arrived at Job List page.")
        human_delay(3, 5)
    except Exception as e:
        logger.error(f"❌ Navigation failed: {e}")

def apply_filters(page):
    """
    Applies filters using the specific HTML structure provided.
    """
    logger.info("🌪️ Applying 'Level' Filters...")
    
    try:
        # 1. FIND AND CLICK THE BUTTON
        level_btn = page.locator("button.drop-down__btn").filter(has_text="Level").first
        
        if not level_btn.is_visible():
            logger.warning("⚠️ Could not find 'Level' button.")
            return

        logger.info("Found 'Level' button. Clicking...")
        level_btn.click()
        
        # Wait for dropdown (Using the search input as confirmation)
        try:
            page.locator("input[placeholder='Options Filter']").wait_for(state="visible", timeout=5000)
        except:
            logger.warning("⚠️ Dropdown did not open.")
            return

        # 2. TOGGLE JUNIOR / INTERMEDIATE
        target_levels = ["Junior", "Intermediate"]
        
        for level in target_levels:
            row = page.locator("li.drop-down__item").filter(has_text=level).first
            
            if row.is_visible():
                is_on = row.locator("i.toggle-on").is_visible()
                
                if not is_on:
                    logger.info(f"🔘 '{level}' is OFF. Clicking to turn ON...")
                    row.locator("label.toggle--single").click()
                    time.sleep(0.5)
                else:
                    logger.info(f"✅ '{level}' is already ON.")
            else:
                logger.warning(f"⚠️ Could not find filter row for '{level}'")

        # 3. TRIGGER RELOAD
        logger.info("🔄 Closing dropdown to trigger reload...")
        page.locator("body").click(position={"x": 0, "y": 0})
        
        logger.info("⏳ Waiting for table to refresh...")
        time.sleep(5)
        
    except Exception as e:
        logger.error(f"❌ Error applying filters: {e}")

def extract_text_sections(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    def get_clean_text(label_keyword):
        label_span = soup.find("span", class_="label", string=lambda t: t and label_keyword in t)
        if not label_span: return "Not Found"
        container = label_span.find_parent("div", class_="tag__key-value-list")
        if container:
            label_span.decompose()
            for br in container.find_all("br"): br.replace_with("\n")
            text = container.get_text(separator="\n", strip=True)
            return re.sub(r'\n\s*\n', '\n\n', text)
        return "Not Found"
    return get_clean_text("Job Summary"), get_clean_text("Job Responsibilities"), get_clean_text("Required Skills")

def scrape_current_page(page, page_num, existing_ids):
    logger.info(f"📄 Scanning Page {page_num}...")
    handle_keep_alive(page)
    try:
        page.wait_for_selector("table tbody tr", timeout=20000)
    except:
        return []
    
    rows = page.locator("table tbody tr")
    count = rows.count()
    new_data = []

    for i in range(count):
        if i % 5 == 0: handle_keep_alive(page)

        row = page.locator("table tbody tr").nth(i)
        if not row.locator("a").first.is_visible(): continue

        job_link = row.locator("a").first
        job_title = job_link.inner_text().strip()
        if not job_title: continue

        # --- CAPTURE COLUMNS 1-5 ---
        try:
            tds = row.locator("td")
            org      = tds.nth(1).inner_text().strip() 
            division = tds.nth(2).inner_text().strip() 
            openings = tds.nth(3).inner_text().strip() 
            city     = tds.nth(4).inner_text().strip() 
            level    = tds.nth(5).inner_text().strip() 
        except:
            org, division, openings, city, level = "", "", "", "", ""

        logger.info(f"[Pg {page_num} | {i+1}/{count}] {job_title}")
        
        job_link.scroll_into_view_if_needed()
        human_delay(0.5, 1)

        # Click with retry
        click_success = False
        for attempt in range(3):
            try:
                job_link.click(timeout=5000) 
                click_success = True
                break
            except TimeoutError:
                if handle_keep_alive(page):
                    human_delay(1, 2)
                    continue
            except Exception as e:
                if "intercepts pointer events" in str(e):
                    handle_keep_alive(page)
                    human_delay(1, 2)
                else:
                    break
        
        if not click_success:
            continue

        # Wait for Header
        header_loc = page.locator("div.dashboard-header__posting-title")
        
        try:
            header_loc.wait_for(state="visible", timeout=8000)
            
            # Extract ID
            job_id = "N/A"
            text = header_loc.inner_text()
            match = re.search(r'(\d{6})', text)
            if match:
                job_id = match.group(1)
            else:
                try:
                    body_id = page.locator("tr", has_text="Job ID").locator("td").last
                    if body_id.is_visible() and re.search(r'\d{6}', body_id.inner_text()):
                        job_id = re.search(r'(\d{6})', body_id.inner_text()).group(1)
                except: pass

            if job_id != "N/A" and job_id in existing_ids:
                logger.info(f"⏭️ Skipping {job_id} (Duplicate).")
                page.keyboard.press("Escape")
                human_delay(0.5, 1)
                continue
            
            html = page.content()
            summary, resp, skills = extract_text_sections(html)

            if summary == "Not Found" and job_id != "N/A":
                time.sleep(1)
                html = page.content()
                summary, resp, skills = extract_text_sections(html)

            new_data.append({
                "Job ID": job_id,
                "Job Title": job_title,
                "Organization": org,
                "Division": division,
                "Openings": openings,
                "City": city,
                "Level": level,
                "Summary": summary,
                "Responsibilities": resp,
                "Skills": skills
            })

        except Exception as e:
            logger.warning(f"⚠️ Popup error: {e}")

        # --- GHOST BUTTON FIX ---
        page.keyboard.press("Escape")
        time.sleep(0.5)

        try:
            if header_loc.is_visible():
                page.locator("button.modal__btn--close").first.evaluate("el => el.click()")
        except:
            pass
            
        human_delay(1, 2)

    return new_data

def scrape_all_pages(page, output_file):
    all_jobs_df = pd.DataFrame()
    existing_ids = set()
    start_page = 1
    
    # 1. READ EXISTING FILE (To calculate resume point)
    if os.path.exists(output_file):
        try:
            logger.info(f"📂 Found existing file: {output_file}. Resuming...")
            all_jobs_df = pd.read_excel(output_file)
            all_jobs_df['Job ID'] = all_jobs_df['Job ID'].astype(str)
            existing_ids = set(all_jobs_df['Job ID'].tolist())
            num_existing = len(all_jobs_df)
            logger.info(f"📊 Loaded {num_existing} existing jobs.")
            start_page = (num_existing // JOBS_PER_PAGE_GUESS) + 1
            logger.info(f"⏩ Will fast-forward to Page {start_page} after filters...")
        except:
            logger.error("⚠️ Error reading existing file. Starting fresh.")

    logger.info("Attempting to switch to 'All Jobs' view...")
    try:
        page.get_by_role("button", name="All Jobs").click()
        human_delay(4, 6) 
    except: pass
    
    # --- CRITICAL CHANGE: ALWAYS APPLY FILTERS ---
    # Apply filters regardless of whether we are resuming or starting fresh.
    apply_filters(page)
    # ---------------------------------------------

    # 2. FAST FORWARD LOOP
    current_page = 1
    while current_page < start_page:
        logger.info(f"⏩ Skipping Page {current_page}...")
        next_btn = page.locator("a[aria-label='Go to next page']")
        if next_btn.is_visible() and "disabled" not in (next_btn.get_attribute("class") or ""):
            next_btn.click()
            time.sleep(3) # Wait for table load
            current_page += 1
        else:
            logger.warning("🛑 Could not fast-forward further. End of list?")
            break

    # 3. MAIN SCRAPING LOOP
    while current_page <= MAX_PAGES:
        handle_keep_alive(page)
        new_jobs = scrape_current_page(page, current_page, existing_ids)
        
        if new_jobs:
            new_df = pd.DataFrame(new_jobs)
            new_df['Job ID'] = new_df['Job ID'].astype(str)
            all_jobs_df = pd.concat([all_jobs_df, new_df], ignore_index=True)
            
            # Save Columns in logical order
            cols = ["Job ID", "Organization", "Job Title", "Division", "City", "Level", "Openings", "Summary", "Responsibilities", "Skills"]
            all_jobs_df = all_jobs_df[[c for c in cols if c in all_jobs_df.columns]]
            
            all_jobs_df.to_excel(output_file, index=False)
            logger.info(f"💾 SAVED! {len(all_jobs_df)} total jobs.")
            existing_ids.update(new_df['Job ID'].tolist())
        else:
            logger.info(f"ℹ️ Page {current_page} yielded no new jobs.")

        logger.info("👀 Checking for next page...")
        next_btn = page.locator("a[aria-label='Go to next page']")
        if next_btn.is_visible():
            if "disabled" in (next_btn.get_attribute("class") or ""):
                break
            else:
                next_btn.click()
                time.sleep(5) 
                current_page += 1
        else:
            break
    logger.info("🎉 Scraping Complete.")

def main():
    args = parse_arguments()
    output_filename = args.output
    
    if not output_filename.endswith(".xlsx"):
        logger.warning(f"⚠️ Filename '{output_filename}' is invalid. Appending '.xlsx'.")
        output_filename += ".xlsx"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=AUTH_FILE) if os.path.exists(AUTH_FILE) else browser.new_context()
        page = context.new_page()
        try:
            page.goto(f"https://waterlooworks.uwaterloo.ca/{DASHBOARD_URL_PART}")
            if "notLoggedIn" in page.url: perform_login(page, context)
        except: perform_login(page, context)
        if "jobs.htm" not in page.url: navigate_to_jobs(page)
        scrape_all_pages(page, output_filename)
        browser.close()

if __name__ == "__main__":
    main()