# resume_parser.py

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from docx import Document
import os
from PIL import Image
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- REQUIRED CONFIGURATION (YOU MUST ADJUST THESE PATHS) ---
# IMPORTANT: Uncomment these lines (remove the '#') and set them
# to the EXACT paths where Tesseract-OCR and Poppler are installed on YOUR system.

# Path to the tesseract.exe executable
# Example for Windows: r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# Example for Linux/macOS: r'/usr/local/bin/tesseract' (or wherever you installed it)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe' # <-- CHANGE THIS PATH!

# Path to the 'bin' directory of your Poppler installation
# Example for Windows: r'C:\poppler\poppler-23.08.0\Library\bin' (adjust version)
# Example for Linux (might not need this if poppler is in PATH): r'/usr/bin'
poppler_path = r'C:\path\to\poppler-xx\bin' # <-- CHANGE THIS PATH! (e.g., C:\Users\Acer\Downloads\poppler-23.08.0\Library\bin)


def extract_text_from_pdf(pdf_path):
    logger.info(f"Attempting to extract text from PDF: {pdf_path}")
    text = ""
    if not os.path.exists(pdf_path):
        logger.error(f"Error: PDF file not found at '{pdf_path}'.")
        return ""

    try:
        # Attempt direct text extraction with pdfplumber first
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # If pdfplumber didn't find any text, try OCR
        if not text.strip(): # Check if text is effectively empty (only whitespace)
            logger.warning(f"No direct text found in '{pdf_path}'. Attempting OCR...")
            try:
                if not os.path.exists(poppler_path) or not os.path.isdir(poppler_path):
                     logger.error(f"Poppler 'bin' directory not found at '{poppler_path}'. Cannot perform PDF-to-Image conversion for OCR.")
                     return ""
                
                # Convert PDF pages to images using Poppler
                # Ensure poppler_path points to the 'bin' directory containing pdftoppm, etc.
                images = convert_from_path(pdf_path, poppler_path=poppler_path) 
                for i, image in enumerate(images):
                    logger.info(f"  - OCR processing page {i+1} of '{pdf_path}'...")
                    page_ocr_text = pytesseract.image_to_string(image)
                    if page_ocr_text:
                        text += page_ocr_text + "\n"
                if not text.strip():
                    logger.warning(f"OCR also failed to extract text from '{pdf_path}'.")
            except pytesseract.TesseractNotFoundError:
                logger.error("ERROR: Tesseract OCR engine not found. Ensure it's installed and 'pytesseract.pytesseract.tesseract_cmd' path is correct in resume_parser.py.")
                return ""
            except Exception as e:
                logger.error(f"ERROR: An error occurred during OCR/pdf2image processing for '{pdf_path}': {e}")
                if "PDF page is not an image" in str(e) or "Unable to open document" in str(e) or "is not recognized" in str(e):
                    logger.error("  - This might indicate an issue with Poppler installation or 'poppler_path' setting.")
                return ""

    except Exception as e: # Catch other potential errors from pdfplumber (e.g., malformed PDF)
        logger.error(f"ERROR: An error occurred during PDF processing for '{pdf_path}': {e}")
        return ""
    
    return text.strip()


def extract_text_from_docx(docx_path):
    logger.info(f"Attempting to extract text from DOCX: {docx_path}")
    text = ""
    if not os.path.exists(docx_path):
        logger.error(f"Error: DOCX file not found at '{docx_path}'.")
        return ""

    try:
        document = Document(docx_path)
        for para in document.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        logger.error(f"Error processing DOCX '{docx_path}': {e}")
        return ""
    return text.strip()


def extract_text_from_resume(file_path):
    """Main function to extract text from PDF or DOCX."""
    logger.info(f"Attempting to extract text from: {file_path}")
    extracted_content = ""
    if file_path.lower().endswith(".pdf"):
        extracted_content = extract_text_from_pdf(file_path)
    elif file_path.lower().endswith(".docx"):
        extracted_content = extract_text_from_docx(file_path)
    else:
        logger.error(f"Error: Unsupported file type for '{file_path}'. Only .pdf and .docx are supported.")
        extracted_content = ""
    
    if not extracted_content:
        logger.warning(f"No text extracted from {file_path}.")
    else:
        # Corrected line: Apply replace before f-string formatting to avoid SyntaxError
        preview_text = extracted_content[:200].replace('\n', ' ').replace('\r', '')
        logger.info(f"Successfully extracted text from {file_path} (first 200 chars: '{preview_text}...')")
    return extracted_content


if __name__ == "__main__":
    # Example usage for direct testing of this file.
    print("--- Testing resume_parser.py directly ---")
    
    # --- IMPORTANT: Create a 'test_resumes' folder in your project root ---
    # And place a test PDF/DOCX resume there.
    # Update this path to point to your actual test resume file.
    test_resume_file_path = "test_resumes/AvishekCV.pdf" # Make sure this file exists for testing!
    # test_resume_file_path = "test_resumes/sample_resume.docx" # Uncomment and use if you have a DOCX

    # Create a dummy test_resumes folder if it doesn't exist
    os.makedirs("test_resumes", exist_ok=True)

    if os.path.exists(test_resume_file_path):
        print(f"Extracting text from: {test_resume_file_path}")
        extracted_text = extract_text_from_resume(test_resume_file_path)
        print(f"\n--- EXTRACTED TEXT (First 1000 chars) ---")
        # Print extracted text to verify (replace newlines for better console readability)
        print(extracted_text[:1000].replace('\n', ' ').replace('\r', '') if extracted_text else 'No text extracted!')
        print("------------------------------------\n")
    else:
        print(f"Test resume file not found at {test_resume_file_path}. Please create this file for testing.")
        print("Remember to configure pytesseract.pytesseract.tesseract_cmd and poppler_path at the top of resume_parser.py")