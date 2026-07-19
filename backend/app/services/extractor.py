"""
Chapter List Extractor using Selenium
Automatically extracts chapter lists from book pages to eliminate manual HTML editing
"""

# import sys
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import re
import os

# Lấy đường dẫn tuyệt đối của thư mục chứa file script.py hiện tại (thư mục original)
# current_dir = os.path.dirname(os.path.abspath(__file__))

# # Đẩy thư mục này lên vị trí đầu tiên trong danh sách tìm kiếm của Python
# if current_dir not in sys.path:
#     sys.path.insert(0, current_dir)
    
from app.database import get_database
from app.config import TRUYENWIKI, get_cookies

# print("Đang dùng db_manager tại:", db_manager.__file__)
class ChapterListExtractor:
    def __init__(self):
        self.driver = None
        self.db = get_database()
        
    def _setup_selenium(self):
        """Setup Selenium WebDriver with appropriate options"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in background
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        return driver
    
    def _inject_cookies(self):
        """Inject cookies for authentication"""
        if not self.driver:
            return
        
        self.driver.get(TRUYENWIKI['book_domain'])
        
        cookie_map = get_cookies()
        domain = TRUYENWIKI['cookie_domain']
        for name, value in cookie_map.items():
            if value:
                try:
                    self.driver.add_cookie({
                        'name': name, 
                        'value': value, 
                        'domain': domain
                    })
                except Exception as e:
                    print(f"⚠️ Could not add cookie {name}: {e}")
    
    def extract_chapter_list(self, book_url: str) -> list:
        """
        Extract chapter list from a book page
        
        Returns:
            List of dictionaries with chapter info: 
            [{'title': 'Chapter Title', 'url': '/chapter/123'}, ...]
        """
        if not self.driver:
            self.driver = self._setup_selenium()
            self._inject_cookies()
        
        try:
            print(f"🔍 Loading book page: {book_url}")
            self.driver.get(book_url)
            all_chapters = []
            # Wait for page to load - adjust selector based on actual site structure
            wait = WebDriverWait(self.driver, 20)
            
            # Try common selectors for chapter lists - you'll need to adjust these
            # based on the actual website structure
            chapter_selectors = [
                "ul.chapter-list a",           # Common pattern
                "div.chapter-list a",          
                "li.chapter-name a",           # Your current pattern
                ".list-chapter a",
                "#chapter-list a",
                "a[href*='chapter']",          # Fallback: any link with 'chapter' in URL
            ]
            
            # chapter_elements = []
            # used_selector = None
            
            # for selector in chapter_selectors:
            #     try:
            #         elements = wait.until(
            #             EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
            #         )
            #         if elements and len(elements) > 0:
            #             chapter_elements = elements
            #             used_selector = selector
            #             print(f"✅ Found chapter list using selector: {selector}")
            #             break
            #     except TimeoutException:
            #         continue
            
            # if not chapter_elements:
            #     # Try to find any list-like structure as fallback
            #     print("⚠️ Trying fallback methods...")
            #     fallback_selectors = [
            #         "div[class*='chapter'] a",
            #         "li[class*='chapter'] a",
            #         "a[title*='Chương']",
            #         "a:contains('Chương')"  # This might not work directly, need JS
            #     ]
                
            #     for selector in fallback_selectors:
            #         try:
            #             if "contains" in selector:
            #                 # Use XPath for text contains
            #                 elements = self.driver.find_elements(
            #                     By.XPATH, "//a[contains(text(), 'Chương')]"
            #                 )
            #             else:
            #                 elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            
            #             if elements and len(elements) > 0:
            #                 chapter_elements = elements
            #                 used_selector = selector
            #                 print(f"✅ Found chapters with fallback selector: {selector}")
            #                 break
            #         except Exception:
            #             continue
            
            # if not chapter_elements:
            #     raise Exception("Could not find chapter list with any known selector")
            
            # # Extract chapter information
            # chapters = []
            # seen_urls = set()  # Avoid duplicates
            
            # for i, element in enumerate(chapter_elements, 1):
            #     try:
            #         # Get chapter URL
            #         chapter_url = element.get_attribute('href')
            #         if not chapter_url:
            #             continue
                    
            #         # Skip if we've already seen this URL (avoid duplicates)
            #         if chapter_url in seen_urls:
            #             continue
            #         seen_urls.add(chapter_url)
                    
            #         # Get chapter title - try multiple attributes
            #         chapter_title = (
            #             element.get_attribute('title') or 
            #             element.text.strip() or
            #             element.get_attribute('data-title') or
            #             f"Chương {i}"  # Fallback
            #         )
                    
            #         # Clean up title
            #         chapter_title = re.sub(r'\s+', ' ', chapter_title).strip()
            #         if not chapter_title:
            #             chapter_title = f"Chương {i}"
                    
            #         chapters.append({
            #             'title': chapter_title,
            #             'url': chapter_url,
            #             'order': i
            #         })
                    
            #     except Exception as e:
            #         print(f"⚠️ Error processing chapter element {i}: {e}")
            #         continue
            
            # print(f"📚 Extracted {len(chapters)} chapters from {book_url}")
            
            # Handle pagination if needed
            # This would require detecting pagination controls and iterating through pages
            # For now, assuming all chapters are on one page
            # --- Pagination Logic based on data-start ---
            current_start = 0
            while True:
                found_on_page = False
                for selector in chapter_selectors:
                    try:
                        elements = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector)))
                        if elements:
                            for el in elements:
                                url = el.get_attribute('href')
                                title = el.text.strip() or "Untitled Chapter"
                                if url:
                                    all_chapters.append({'order': len(all_chapters)+1, 'title': title, 'url': url})
                            found_on_page = True
                            break
                    except TimeoutException:
                        continue
                
                try:
                    pagination_links = self.driver.find_elements(By.CSS_SELECTOR, ".volume-list ul.pagination a")
                    next_start = current_start + 501 
                    
                    target_link = None
                    for link in pagination_links:
                        if link.get_attribute('data-start') == str(next_start):
                            target_link = link
                            break
                    
                    if target_link:
                        print(f"📄 Loading next page (start={next_start})...")
                        target_link.click()
                        current_start = next_start
                        time.sleep(random.randint(2, 4))
                    else:
                        break
                except NoSuchElementException:
                    break
                
                if len(all_chapters) > 10000: 
                    break
            if not all_chapters:
                return False, "No chapters found on the page"
            # Save to DB => No save to db, use save_chapters_to_db function instead to handle this after extraction
            # self.db.add_chapters(book_id, all_chapters)
            # self.db.update_book(book_id, download_status='ready_for_download', total_chargers=len(all_chapters))
            
            print(f"✅ Successfully extracted {len(all_chapters)} chapters.")
            # return True, f"Extracted {len(all_chapters)} chapters"
            return all_chapters
            
        except Exception as e:
            print(f"❌ Failed to extract chapter list from {book_url}: {e}")
            return []
    
    def save_chapters_to_db(self, book_id: int, chapters: list):
        """Save extracted chapters to database"""
        if not chapters:
            print("⚠️ No chapters to save")
            return
        
        # Clear existing chapters for this book (if updating)
        # Optional: you might want to keep existing ones and only add new ones
        conn = self.db._get_connection()
        conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
        conn.commit()
        
        # Add new chapters
        for chapter in chapters:
            self.db.add_chapter(
                book_id=book_id,
                chapter_order=chapter['order'],
                chapter_title=chapter['title'],
                chapter_url=chapter['url']
            )
        
        print(f"💾 Saved {len(chapters)} chapters to database for book ID {book_id}")
    
    def update_book_html_template(self, book_id: int, chapters: list, 
                                 folder_path: str = "./data/book_source"):
        """
        Update the HTML template file with the extracted chapter list
        This creates/updates the file that wikicv_docx.py reads from
        """
        print(f"🔄 Updating HTML template for book ID {book_id} with {len(chapters)} chapters")
        book = self.db.get_book(book_id)
        if not book:
            print(f"❌ Book not found with ID: {book_id}")
            return
        
        seo_filename = f"{book_id}_{book['seo_title_full']}"
        html_path = os.path.join(folder_path, seo_filename)
        
        try:
            # Read existing file or create new one
            if os.path.exists(html_path):
                with open(html_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Replace chapter list section or append if not found
                soup = BeautifulSoup(content, 'html.parser')
                
                # Look for existing chapter list container
                chapter_container = soup.find('div', {'id': 'chapter-list'}) or \
                                  soup.find('ul', {'class': 'chapter-list'}) or \
                                  soup.find('div', {'class': 'list-chapter'})
                
                if chapter_container:
                    # Clear existing content
                    chapter_container.clear()
                else:
                    # Create new container
                    chapter_container = soup.new_tag('div', **{'id': 'chapter-list'})
                    if soup.body:
                        soup.body.append(chapter_container)
                    else:
                        # If no body, wrap everything
                        wrapper = soup.new_tag('body')
                        wrapper.append(soup.contents)
                        soup.html.append(wrapper)
                        wrapper.append(chapter_container)
                
                # Add chapter list
                chapter_list_tag = soup.new_tag('ul', **{'class': 'chapter-list'})
                for chapter in chapters:
                    li_tag = soup.new_tag('li')
                    a_tag = soup.new_tag('a', href=chapter['url'])
                    a_tag.string = chapter['title']
                    li_tag.append(a_tag)
                    chapter_list_tag.append(li_tag)
                
                chapter_container.append(chapter_list_tag)
                
                # Write back to file
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(str(soup.prettify()))
                    
            else:
                # Create new HTML file with chapter list
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(f'''<!DOCTYPE html>
<html lang="vi">
<head>
    <title>{book['title']}</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body>
    <h1>{book['title']}</h1>
    <div id="chapter-list">
        <ul class="chapter-list">
''')
                    for chapter in chapters:
                        f.write(f'            <li><a href="{chapter["url"]}">{chapter["title"]}</a></li>\n')
                    f.write('        </ul>\n    </div>\n</body>\n</html>''')
            
            print(f"📄 Updated HTML template: {html_path}")
            
        except Exception as e:
            print(f"❌ Failed to update HTML template {html_path}: {e}")
    
    def process_book_chapters(self, book_url: str, book_title: str) -> bool:
        """
        Main method to process a book: extract chapters and update everything
        
        Returns:
            True if successful, False otherwise
        """
        print(f"\n📖 Processing book: {book_title}")
        print(f"🔗 URL: {book_url}")
        
        try:
            # Extract chapters from website
            chapters = self.extract_chapter_list(book_url)
            
            if not chapters:
                print(f"❌ No chapters extracted for {book_title}")
                return False
            
            # Get or create book in database
            book = self.db.get_book_by_title(book_title)
            if book:
                book_id = book['id']
                print(f"📚 Found existing book in DB: {book_title} (ID: {book_id})")
            else:
                # Add new book to database
                book_id = self.db.add_book(
                    title=book_title,
                    book_url=book_url
                )
                print(f"📚 Added new book to DB: {book_title} (ID: {book_id})")
            
            # Save chapters to database
            self.save_chapters_to_db(book_id, chapters)
            
            # Update HTML template file
            # self.update_book_html_template(book_id, chapters)
            
            # Update book status to indicate chapters are ready
            self.db.update_book_status(
                book_id=book_id,
                download_status='ready_for_download',
                total_chapters=len(chapters)
            )
            
            print(f"✅ Successfully processed {book_title}")
            print(f"   📊 Chapters found: {len(chapters)}")
            print(f"   💾 Saved to database and HTML template updated")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to process book {book_title}: {e}")
            return False
    
    def close(self):
        """Close the WebDriver"""
        if self.driver:
            self.driver.quit()
            self.driver = None

def extract_chapters_for_book(book_url: str, book_title: str) -> bool:
    """
    Convenience function to extract chapters for a single book
    
    Args:
        book_url: URL of the book's main page
        book_title: Title of the book
        
    Returns:
        True if successful
    """
    extractor = ChapterListExtractor()
    try:
        return extractor.process_book_chapters(book_url, book_title)
    finally:
        extractor.close()

# Example usage:
if __name__ == "__main__":
    # Test with a sample book URL and title
    # Replace with actual values when testing
    test_url = input("Enter the book URL to extract chapters from: ")
    test_title = input("Enter the book title: ")
    
    success = extract_chapters_for_book(test_url, test_title)
    if success:
        print("✅ Chapter extraction completed successfully")
    else:
        print("❌ Chapter extraction failed")