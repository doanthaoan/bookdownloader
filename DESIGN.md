# Vietnamese Novel Download Tool - Design Document

## Overview
This project is a Python-based toolkit designed to download Vietnamese novels from a personal book website and save them as formatted documents (HTML and DOCX) on a local computer. The system automates the process of fetching book chapters, handling authentication, and organizing downloaded content.

## Core Components

### 1. Book List Manager (`truyen_taodanhsach.py`)
- Manages book inventory using Excel files
- Generates SEO-friendly filenames for books
- Creates template HTML files for new books
- Tracks book and chapter download status
- Handles duplicate detection and file creation

### 2. Chapter Downloader (`wikicv_docx.py`)
- Uses Selenium WebDriver to handle dynamic content
- Authenticates using injected cookies for accessing purchased content
- Waits for JavaScript-rendered content to load completely
- Extracts chapter titles and content from web pages
- Saves content in both HTML and DOCX formats
- Implements checkpoint saving and resume capability
- Features anti-bot measures with randomized delays

### 3. Configuration (`config.py` + `.env`)
- Manages website configuration and authentication tokens
- Stores sensitive credentials in environment variables
- Uses python-dotenv for secure configuration management

### 4. Supporting Components
- `truyendichngay.py`: Alternative implementation for different domains (to be removed)
- Folder Structure:
  - `book_source/`: Contains book URLs and HTML templates
  - `truyen/`: Stores downloaded DOCX and HTML files
  - `logs/`: Tracks success and failure logs for each book

## Data Flow
1. User updates `book_source/danhsach.xlsx` with new book information (ID, name, status, URL)
2. Run `truyen_taodanhsach.py` to:
   - Detect new books
   - Generate SEO-friendly filenames
   - Create template HTML files in `book_source/`
   - Update tracking in `book_source/danh_sach_truyen_seo.xlsx`
3. User manually fills chapter lists in HTML files (current step - planned for automation)
4. Run `wikicv_docx.py` to:
   - Load book's chapter list from HTML file
   - Authenticate using injected cookies
   - Navigate to each chapter URL
   - Wait for dynamic content to load
   - Extract and save chapter content to HTML/DOCX
   - Track progress with resume capability
   - Log successes and failures

## Technical Stack
- Python 3.x
- Core Libraries: 
  - Selenium (WebDriver with authentication)
  - BeautifulSoup4 (HTML parsing)
  - python-docx (DOCX generation)
  - pandas (Excel handling)
  - python-dotenv (environment variables)
  - colorama (colored terminal output)
  - webdriver-manager (ChromeDriver management)
  - unidecode (Unicode handling)
  - re (regular expressions)

## Key Features
- Automatic authentication via cookie injection
- Dynamic content handling with Selenium waits
- Progress tracking and resume capability
- Checkpoint saving (every 10 chapters)
- Anti-bot measures with randomized delays
- Comprehensive logging system
- Error handling and recovery
- Duplicate detection and prevention