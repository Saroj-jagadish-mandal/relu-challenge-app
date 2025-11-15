"""
ReluConsultancy Hiring Challenge: Shoalhaven DA Scraper
Submission File: relu_submission.py (FINAL PRODUCTION VERSION)
(Combined file for Google Colab and .py upload)

This script executes the 6-step plan:
1. Navigate and Agree
2. Go to DA Tracking
3. Select Advanced Search
4. Set Date Range and Search
5. Scrape All Results (Two-Loop Strategy: List -> Detail)
6. Clean and Save to CSV (Handled by models.py and _save_to_csv)

To Run in Google Colab (first cell):
!pip install playwright pydantic pandas beautifulsoup4
!playwright install

To Run Locally:
1. pip install playwright pydantic pandas beautifulsoup4
2. playwright install
3. python relu_submission.py
"""

import asyncio
import logging
import re
import pandas as pd
from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

# ==============================================================================
# 1. CONFIGURATION (config.py)
# ==============================================================================

SELECTORS = {
    # Step 1: Agree
    "agree_button": "#ctl00_cphContent_ctl01_btnOk", # Confirmed

    # Step 2: DA Tracking Tab
    "da_tracking_tab": "text='DA Tracking'", # Confirmed

    # Step 3: Advanced Search Tab
    "advanced_search_tab": "text='Advanced Search'", # Confirmed

    # Step 4: Date Range & Search
    "from_date_input": "input[name='ctl00_cphContent_ctl00_ctl03_dateInput_text']", # Confirmed
    "to_date_input": "input[name='ctl00_cphContent_ctl00_ctl05_dateInput_text']",   # Confirmed
    "search_button": "#ctl00_cphContent_ctl00_btnSearch", # Confirmed

    # Step 5: Results List Page & Paginate
    "results_table": "#ct100_cphContent_ct101_ct101_RadGrid1_ctl00", # Confirmed
    "result_row": "tr.rgRow, tr.rgAltRow", # Confirmed
    "da_number_in_row": "td:nth-child(2)", # Confirmed
    "da_link_in_row": "td:first-child a", # Confirmed
    "submitted_date_in_row": "td:nth-child(3)", # Confirmed
    "next_page_button": "input[title='Next Page']", # Confirmed
    
    # Selector for the whole pagination bar
    "pager_bar": "td.rgPagerCell", # Confirmed

    # --- Step 6: Detail Page Fields ---
    "detail_page_expand_button": "a[href='javascript:expandCollapse(\"expand\")']", # Confirmed
    "details_container": "#lblDetails", # Confirmed
    "decision": "#lblDecision", # Confirmed
    "categories": "#lblCat", # Confirmed
    "property_address": "#lblProp", # Confirmed
    "progress": "#lblProg", # Confirmed
    "documents": "#lblDocs", # Confirmed
    "contact_council": "#lbl91", # Confirmed
    "applicant": "#lblPeople", # Confirmed
    "fees": "#lblFees", # Confirmed
}

# --- Constants ---
BASE_URL = "https://www3.shoalhaven.nsw.gov.au/masterviewUI/modules/ApplicationMaster/Default.aspx"
DETAIL_URL_BASE = "https://www3.shoalhaven.nsw.gov.au/masterviewUI/modules/ApplicationMaster/"
SEARCH_FROM_DATE = "01/09/2025"
SEARCH_TO_DATE = "30/09/2025"
OUTPUT_FILE = "results.csv"

# --- Final Production Settings ---
TEST_MODE_LIMIT = None # Set to None to scrape all records
HEADLESS_MODE = True  # --- SET TO TRUE FOR SUBMISSION ---
EXPECTED_PAGE_SIZE = 10 # Used for pagination logic

# ==============================================================================
# 2. DATA MODELS (models.py)
# ==============================================================================

class DevelopmentApplication(BaseModel):
    """
    Defines the data schema for the final CSV (Step 7).
    All fields are Optional to handle missing data.
    """
    
    # These must match the CSV headers from Step 7
    DA_Number: Optional[str] = None
    Detail_URL: Optional[str] = None
    Description: Optional[str] = None
    Submitted_Date: Optional[str] = None
    Decision: Optional[str] = None
    Categories: Optional[str] = None
    Property_Address: Optional[str] = None
    Applicant: Optional[str] = None
    Progress: Optional[str] = None
    Fees: Optional[str] = None
    Documents: Optional[str] = None
    Contact_Council: Optional[str] = None

    @field_validator('Fees')
    @classmethod
    def clean_fees(cls, v: Optional[str]) -> Optional[str]:
        """
        Applies the data cleaning rule for 'Fees' from Step 6.
        """
        if v and v.strip() == "No fees recorded against this application.":
            return "Not required"
        return v.strip() if v else None

    @field_validator('Contact_Council')
    @classmethod
    def clean_contact(cls, v: Optional[str]) -> Optional[str]:
        """
        Applies the data cleaning rule for 'Contact Council' from Step 6.
        """
        if v and v.strip() == "Application Is Not on exhibition, please call Council on 1300 293 111 if you require assistance.":
            return "Not required"
        return v.strip() if v else None
        
    @field_validator('Description', 'Submitted_Date', 'Decision', 'Categories', 
                     'Property_Address', 'Applicant', 'Progress', 'Documents')
    @classmethod
    def clean_other_fields(cls, v: Optional[str]) -> Optional[str]:
        """
        Ensures all other text fields are properly stripped of whitespace.
        """
        return v.strip() if v else None

    def to_dict(self):
        """Helper function to convert the model to a dictionary for Pandas."""
        return self.model_dump(exclude_unset=True)

# ==============================================================================
# 3. MAIN SCRAPER LOGIC (main.py)
# ==============================================================================

# --- Setup Professional Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

class ShoalhavenScraper:
    """
    Encapsulates all logic for the Shoalhaven DA scraper.
    """
    
    def __init__(self):
        self.selectors: Dict[str, str] = SELECTORS
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.scraped_data: List[DevelopmentApplication] = []
        # Stores (DA_Number, Detail_URL, Submitted_Date)
        self.detail_page_links: List[Tuple[str, str, Optional[str]]] = []

    async def run(self) -> None:
        """Main entry point to run the entire scraping process."""
        async with async_playwright() as p:
            try:
                self.browser = await p.chromium.launch(
                    headless=HEADLESS_MODE
                ) 
                self.page = await self.browser.new_page()
                log.info(f"Browser launched (headless={HEADLESS_MODE}).")
                
                await self._navigate_and_search()
                await self._scrape_list_pages()
                await self._scrape_detail_pages()
                await self._save_to_csv()
                
            except Exception as e:
                log.critical(f"A critical error occurred: {e}", exc_info=True)
            finally:
                if not HEADLESS_MODE:
                    log.info("Script finished. Closing browser in 5 seconds...")
                    await asyncio.sleep(5)
                if self.browser:
                    await self.browser.close()
                    log.info("Browser closed.")

    async def _navigate_and_search(self) -> None:
        """Executes Steps 1-4: Navigate, Agree, Set Date, and Search."""
        log.info(f"Navigating to {BASE_URL}...")
        await self.page.goto(BASE_URL)
        
        # Step 1: Agree
        log.info("Waiting for Agree button...")
        await self.page.wait_for_selector(self.selectors["agree_button"], timeout=10000)
        await self.page.click(self.selectors["agree_button"])
        await self.page.wait_for_load_state('networkidle')
        log.info("Agreed to terms.")

        # Step 2: DA Tracking
        await self.page.click(self.selectors["da_tracking_tab"])
        await self.page.wait_for_load_state('networkidle')
        log.info("Clicked DA Tracking tab.")

        # Step 3: Advanced Search
        await self.page.click(self.selectors["advanced_search_tab"])
        log.info("Clicked Advanced Search tab.")

        # --- Wait for date input ---
        try:
            log.info(f"Waiting for date input '{self.selectors['from_date_input']}' to be visible...")
            await self.page.wait_for_selector(
                self.selectors["from_date_input"], 
                state="visible", 
                timeout=10000 
            )
            log.info("Date input is visible.")
        except Exception as e:
            log.error(f"The date input field ({self.selectors['from_date_input']}) did not become visible.")
            raise e 

        # Step 4: Set Date Range and Search
        await self.page.fill(self.selectors["from_date_input"], SEARCH_FROM_DATE)
        await self.page.fill(self.selectors["to_date_input"], SEARCH_TO_DATE)
        await self.page.click(self.selectors["search_button"])
        log.info(f"Search submitted for {SEARCH_FROM_DATE} - {SEARCH_TO_DATE}.")
        
        # --- Wait for the FIRST ROW to be visible ---
        log.info(f"Waiting for first result row ({self.selectors['result_row']}) to appear...")
        try:
            await self.page.wait_for_selector(
                self.selectors["result_row"], 
                state="visible", 
                timeout=30000 # Give it 30s
            )
            log.info("Results table loaded.")
        except Exception as e:
            log.error("The results table rows did not load after clicking search.")
            raise e

    async def _scrape_list_pages(self) -> None:
        """
        Executes Step 5 (Loop 1): Paginates through all results
        and collects DA_Number, Detail_URL, and Submitted_Date.
        """
        log.info("Starting Loop 1: Scraping list pages...")
        page_num = 1
        last_known_da: Optional[str] = None # Fail-safe for intelligent wait
        
        while True:
            log.info(f"Scraping results page {page_num}...")
            
            # --- Wait for rows ---
            try:
                await self.page.wait_for_selector(self.selectors["result_row"], state="visible", timeout=10000)
                
                # Get text of the first DA number on the page
                first_row_da_el = await self.page.query_selector(self.selectors["da_number_in_row"])
                last_known_da = await first_row_da_el.inner_text() if first_row_da_el else None
                
            except Exception as e:
                log.warning(f"Could not find result row on page {page_num}. Assuming end of results. Error: {e}")
                break
            
            rows = await self.page.query_selector_all(self.selectors["result_row"])
            num_rows_found = len(rows)
            log.info(f"Found {num_rows_found} DAs on this page.")
            
            for row in rows:
                da_num_el = await row.query_selector(self.selectors["da_number_in_row"])
                link_el = await row.query_selector(self.selectors["da_link_in_row"])
                date_el = await row.query_selector(self.selectors["submitted_date_in_row"])
                
                da_number = ""
                detail_url = ""
                submitted_date = None
                
                if da_num_el:
                    da_number = (await da_num_el.inner_text()).strip()
                if date_el:
                    submitted_date = (await date_el.inner_text()).strip()
                
                if link_el:
                    href = await link_el.get_attribute("href")
                    detail_url = DETAIL_URL_BASE + href
                
                if da_number and detail_url:
                    # We check for duplicates here to avoid re-scraping the same DA number
                    if not any(d[0] == da_number for d in self.detail_page_links):
                        self.detail_page_links.append((da_number, detail_url, submitted_date))
                
                if TEST_MODE_LIMIT and len(self.detail_page_links) >= TEST_MODE_LIMIT:
                    log.info(f"Test Mode: Reached limit of {TEST_MODE_LIMIT} records.")
                    break 
            
            if TEST_MODE_LIMIT and len(self.detail_page_links) >= TEST_MODE_LIMIT:
                break 

            # --- YOUR PAGINATION STOP LOGIC (as requested) ---
            if num_rows_found < EXPECTED_PAGE_SIZE:
                log.info(f"Found {num_rows_found} DAs, which is less than {EXPECTED_PAGE_SIZE}. This is the last page.")
                break
            # --- END NEW LOGIC ---

            # --- Click Next Page ---
            next_button_selector = self.selectors["next_page_button"]
            next_button_handle = await self.page.query_selector(next_button_selector)
            
            if not next_button_handle:
                log.info("No 'Next Page' button found. Stopping.")
                break 
                
            log.info("Clicking Next Page...")
            try:
                await self.page.click(next_button_selector)
            except Exception as e:
                log.error(f"Failed to click 'Next Page' button on page {page_num}: {e}")
                break 

            # --- Intelligent Wait ---
            log.info("Waiting for page to refresh...")
            try:
                if last_known_da:
                    # Wait for the *text* of the first DA to change
                    await self.page.wait_for_function(
                        f"document.querySelector('{self.selectors['da_number_in_row']}').innerText !== '{last_known_da}'",
                        timeout=10000
                    )
            except Exception as e:
                log.warning(f"Could not confirm page refresh. Error: {e}")
                break
            
            page_num += 1
            
        log.info(f"Loop 1 Complete. Collected {len(self.detail_page_links)} unique DA links.")

    async def _scrape_detail_pages(self) -> None:
        """
        Executes Step 5 (Loop 2): Visits each collected detail URL
        and scrapes the full data.
        """
        log.info(f"Starting Loop 2: Scraping {len(self.detail_page_links)} detail pages...")
        
        for da_number, detail_url, submitted_date in self.detail_page_links:
            app_data = await self._get_detail_page_data(self.page, da_number, detail_url, submitted_date)
            self.scraped_data.append(app_data)
            
        log.info("Loop 2 Complete. All detail pages scraped.")

    def _extract_with_regex(self, pattern: str, text: str) -> Optional[str]:
        """Helper to safely run regex."""
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            clean_text = re.sub(r'<br\s*/?>', ' ', match.group(1))
            return " ".join(clean_text.split()).strip()
        return None

    async def _get_detail_page_data(self, page: Page, da_number: str, url: str, submitted_date: Optional[str]) -> DevelopmentApplication:
        """
        Scrapes a single detail page.
        """
        try:
            log.info(f"Scraping detail page for: {da_number}")
            await page.goto(url)
            await page.wait_for_load_state('networkidle')
            
            expand_button = await page.query_selector(self.selectors["detail_page_expand_button"])
            if expand_button:
                await expand_button.click()
                log.info(f"Clicked 'Expand All' for {da_number}.")
                await page.wait_for_selector(self.selectors["details_container"], state="visible", timeout=5000)
            else:
                log.warning(f"No 'Expand All' link found for {da_number}. Assuming data is already visible.")

            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            def get_text_by_id(selector_key: str) -> Optional[str]:
                selector = self.selectors.get(selector_key) 
                if not selector:
                    log.warning(f"Selector '{selector_key}' not found in config.")
                    return None
                element = soup.select_one(selector)
                # Use .get_text() with a separator to handle multiple lines
                return element.get_text(separator=" ", strip=True) if element else None

            # --- Strategy A: Direct Scrape ---
            decision = get_text_by_id("decision")
            categories = get_text_by_id("categories")
            property_address = get_text_by_id("property_address")
            progress = get_text_by_id("progress")
            documents = get_text_by_id("documents")
            contact_council = get_text_by_id("contact_council")
            applicant = get_text_by_id("applicant") # Confirmed
            fees = get_text_by_id("fees")             # Confirmed
            
            # --- Strategy B: Regex Parse ---
            details_text = get_text_by_id("details_container")
            description = None
            
            if details_text:
                # Find Description, which is between "Description:" and "Submitted:"
                description_match = self._extract_with_regex(r"Description:(.*?)Submitted:", details_text)
                if description_match:
                    description = description_match
                else:
                    # Fallback: if "Submitted:" isn't there, just take everything after "Description:"
                    description_match_fallback = self._extract_with_regex(r"Description:(.*)", details_text)
                    if description_match_fallback:
                        description = description_match_fallback
            
            # --- Create the data object ---
            data = {
                "DA_Number": da_number,
                "Detail_URL": url,
                "Submitted_Date": submitted_date, # This now comes from Loop 1
                "Description": description,
                "Decision": decision,
                "Categories": categories,
                "Property_Address": property_address,
                "Applicant": applicant,
                "Progress": progress,
                "Fees": fees,
                "Documents": documents,
                "Contact_Council": contact_council,
            }
            
            # --- Validate and Clean (Step 6) ---
            return DevelopmentApplication(**data)
            
        except Exception as e:
            log.error(f"Error scraping detail page {url}: {e}", exc_info=True)
            # Return partial data on failure
            return DevelopmentApplication(DA_Number=da_number, Detail_URL=url, Submitted_Date=submitted_date)

    async def _save_to_csv(self) -> None:
        """Saves all scraped data to the final CSV file (Step 7)."""
        if not self.scraped_data:
            log.warning("No applications scraped. CSV will be empty.")
            return

        log.info(f"Saving {len(self.scraped_data)} applications to {OUTPUT_FILE}...")
        
        data_to_save = [app.to_dict() for app in self.scraped_data]
        
        # These headers are specified exactly by Step 7
        headers = [
            "DA_Number", "Detail_URL", "Description", "Submitted_Date",
            "Decision", "Categories", "Property_Address", "Applicant",
            "Progress", "Fees", "Documents", "Contact_Council"
        ]
        
        df = pd.DataFrame(data_to_save)
        df = df[headers] 

        # --- DUPLICATE CHECK REMOVED (as requested) ---
        final_count = len(df)
        
        df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
        log.info(f"Successfully saved {final_count} records to {OUTPUT_FILE}")

# --- 4. Main Execution ---
async def main():
    """Asynchronous main function to run the scraper."""
    scraper = ShoalhavenScraper()
    await scraper.run()

if __name__ == "__main__":
    asyncio.run(main())