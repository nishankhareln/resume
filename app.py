# app.py

import os
import logging
import time # Import the time module for delays
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional, Literal
from dotenv import load_dotenv
import nest_asyncio
from google.api_core import exceptions as google_exceptions

from langchain.prompts import PromptTemplate
from langchain_core.runnables import RunnableSequence
from langchain.output_parsers import PydanticOutputParser

import fitz # PyMuPDF
from PIL import Image # Pillow for image manipulation
import pytesseract # Python wrapper for Tesseract OCR

# --- Configure pytesseract path if Tesseract is not in your PATH ---
# IMPORTANT: Uncomment and set this path if Tesseract is not automatically found.
# This is usually required on Windows if Tesseract is not installed to its default location
# or if your system's PATH variable doesn't include it.
# For Windows example:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# For macOS (if installed via brew, usually in PATH, but can be set if needed) example:
# pytesseract.pytesseract.tesseract_cmd = '/usr/local/bin/tesseract'


nest_asyncio.apply() # Apply nest_asyncio for compatibility with async operations in some environments

load_dotenv() # Load environment variables from .env file (e.g., GEMINI_API_KEY)

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Environment Variable Check ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Pydantic Models for Data Structure ---

class Experience(BaseModel):
    company: str
    title: str
    dates: str
    responsibilities: List[str]

class ResumeInfo(BaseModel):
    name: Optional[str] = "Unknown"
    email: Optional[str] = "Unknown"
    phone_number: Optional[str] = "Unknown"
    linkedin_url: Optional[str] = "Unknown"
    job_title: Optional[str] = "Unknown"
    summary: Optional[str] = "Not provided"
    skills: List[str] = Field(default_factory=list)
    work_experience: List[Experience] = Field(default_factory=list)
    # >>> START OF CHANGE 1 <<<
    experience_years: Optional[int] = Field(None, description="Total years of professional work experience calculated from work_experience entries.")
    # >>> END OF CHANGE 1 <<<
    education: List[str] = Field(default_factory=list)
    optimized_search_keywords: List[str] = Field(default_factory=list)

class ExperienceRequirement(BaseModel):
    minimum_years_experience_required: Optional[int] = Field(None, description="Minimum years of experience required as an integer. Null if not explicitly stated and cannot be reliably inferred as a number.")
    inferred_level: Literal[
        "entry-level", "junior", "mid-level", "senior", "lead", "principal", "staff", "director", "expert", "associate", "intern", "graduate", "unknown"
    ] = Field("unknown", description="Inferred seniority level based on job description.")


class JobCategory(BaseModel):
    category: str

# --- LLM and Embeddings Model Initialization ---

def get_llm_model():
    """Initializes and returns a ChatGoogleGenerativeAI (Gemini) LLM instance.
    Model is configurable via the GEMINI_MODEL env var. Defaults to
    gemini-1.5-flash, which has a more permissive free-tier daily limit than
    gemini-2.0-flash (the 2.0 model often returns `limit: 0` on the free tier)."""
    if not GEMINI_API_KEY:
        logger.critical("GEMINI_API_KEY is not set. Cannot initialize LLM model.")
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.3,
            google_api_key=GEMINI_API_KEY,
            max_retries=2,
        )
        logger.info(f"ChatGoogleGenerativeAI model initialized with {model_name}.")
        return llm
    except ImportError:
        logger.critical("langchain_google_genai not installed. Please run: pip install langchain-google-genai")
        raise
    except google_exceptions.NotFound as e:
        logger.critical(f"Model '{model_name}' not found or accessible: {e}. Try setting GEMINI_MODEL=gemini-1.5-flash in your .env.")
        raise
    except Exception as e:
        logger.critical(f"Error initializing ChatGoogleGenerativeAI: {e}")
        raise

def get_embeddings_model():
    """Initializes and returns an embeddings model.

    Backend is selected by env var EMBEDDING_BACKEND:
      - "local" (default): sentence-transformers, runs offline, free, no quota.
                Model name from LOCAL_EMBEDDING_MODEL env var
                (default: sentence-transformers/all-MiniLM-L6-v2, 384-dim).
      - "google": Gemini embeddings API. Requires GEMINI_API_KEY and quota.
                Model name from GEMINI_EMBEDDING_MODEL env var
                (default: models/gemini-embedding-001, 3072-dim).

    The returned object exposes embed_documents(texts) and embed_query(text)
    in both backends, so callers (main_job_matcher.py) don't need to care which
    one is active.
    """
    backend = (os.getenv("EMBEDDING_BACKEND") or "local").lower()

    if backend == "local":
        try:
            from local_embeddings import LocalEmbeddings
            return LocalEmbeddings()
        except ImportError as e:
            logger.critical(
                "sentence-transformers not installed. Run: "
                "pip install sentence-transformers  (or set EMBEDDING_BACKEND=google)"
            )
            raise
        except Exception as e:
            logger.critical(f"Error initializing local embeddings: {e}")
            raise

    # backend == "google"
    if not GEMINI_API_KEY:
        logger.critical("GEMINI_API_KEY is not set. Cannot initialize Google Embeddings model.")
        raise ValueError("GEMINI_API_KEY environment variable is not set.")
    model_name = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
    if not model_name.startswith("models/"):
        model_name = f"models/{model_name}"
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        embeddings = GoogleGenerativeAIEmbeddings(
            model=model_name,
            google_api_key=GEMINI_API_KEY,
        )
        logger.info(f"GoogleGenerativeAIEmbeddings model initialized with {model_name}.")
        return embeddings
    except ImportError:
        logger.critical("langchain_google_genai not installed. Please run: pip install langchain-google-genai")
        raise
    except Exception as e:
        logger.critical(f"Error initializing GoogleGenerativeAIEmbeddings: {e}")
        raise

# --- PDF Text Extraction Function (with OCR Fallback and Robust Cleanup) ---

def extract_text_from_pdf(pdf_file) -> str:
    """
    Extracts text from a PDF file. Attempts direct extraction first,
    then falls back to OCR if direct extraction yields no or sparse text.
    Handles temporary file storage and robust cleanup, including retries for
    file access errors common on Windows.
    """
    logger.info(f"--- 1. Attempting to extract text from: {pdf_file.name} ---")
    extracted_text = ""
    pdf_path = None
    try:
        temp_dir = "temp"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        # Save the uploaded file to a temporary path
        pdf_path = os.path.join(temp_dir, pdf_file.name)
        with open(pdf_path, "wb") as f:
            f.write(pdf_file.getbuffer())

        logger.info(f"Attempting direct text extraction from PDF: {pdf_path}")
        doc = fitz.open(pdf_path) # Open the PDF with PyMuPDF
        
        # Try direct text extraction first
        for page in doc:
            extracted_text += page.get_text()
        doc.close() # Close the document immediately after reading for direct text extraction

        # If direct extraction yields little to no text, attempt OCR
        if not extracted_text.strip() or len(extracted_text.strip()) < 50:
            logger.warning("Direct PDF text extraction yielded sparse or no text. Attempting OCR fallback.")
            ocr_text = ""
            # Re-open the document specifically for OCR processing to ensure a fresh state
            doc_ocr = fitz.open(pdf_path) 
            for page_num in range(len(doc_ocr)):
                page = doc_ocr.load_page(page_num)
                # Render page to a high-resolution image (300 DPI is a good balance for OCR)
                # Adjust matrix values if 300 DPI is too slow or memory intensive for very large PDFs
                pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Perform OCR on the rendered image
                try:
                    page_ocr_text = pytesseract.image_to_string(img)
                    ocr_text += page_ocr_text + "\n"
                except pytesseract.TesseractNotFoundError:
                    logger.error("Tesseract OCR engine is not installed or not in your system's PATH. Cannot perform OCR. Please install Tesseract (e.g., from tesseract-ocr.github.io/tessdoc/Installation.html).")
                    # If Tesseract isn't found, we can't do OCR, so return whatever text was directly extracted (if any)
                    return extracted_text.strip()
                except Exception as ocr_e:
                    logger.error(f"Error during OCR for page {page_num} of {pdf_file.name}: {ocr_e}")
                    # Log the error but continue attempting OCR on subsequent pages
            doc_ocr.close() # Close the document opened for OCR

            # If OCR produced text, use it; otherwise, stick with original extracted_text (which might be empty)
            if ocr_text.strip():
                extracted_text = ocr_text
                logger.info("OCR fallback successful. Text extracted via OCR.")
            else:
                logger.warning("OCR also failed to extract significant text. The PDF might be truly empty, corrupted, or not readable by OCR.")

        # Log a preview of the final extracted text (either direct or OCR)
        preview_text_cleaned = extracted_text[:200].replace('\n', ' ').strip()
        if preview_text_cleaned:
            logger.info(f"Successfully extracted text from {pdf_file.name} (first 200 chars: '{preview_text_cleaned}...')")
        else:
            logger.warning(f"Extracted text from {pdf_file.name} is empty or too short after all extraction attempts.")
        
        return extracted_text
    
    except Exception as e:
        logger.error(f"Critical error processing PDF {pdf_file.name}: {e}")
        return ""
    finally:
        # --- Robust Temporary PDF File Cleanup ---
        # This 'finally' block ensures the temporary file is removed, even if errors
        # occurred during PDF processing. It includes a retry mechanism for
        # 'file in use' errors which are common on Windows.
        if pdf_path and os.path.exists(pdf_path):
            max_retries = 5
            for i in range(max_retries):
                try:
                    os.remove(pdf_path)
                    logger.debug(f"Removed temporary PDF file: {pdf_path}")
                    break # Exit loop if deletion is successful
                except OSError as e:
                    # Specific check for 'file in use' error (common on Windows)
                    if "being used by another process" in str(e):
                        logger.warning(f"Attempt {i+1}/{max_retries}: File {pdf_path} is still in use. Retrying in 0.1 seconds...")
                        time.sleep(0.1) # Wait a bit before retrying
                    else:
                        logger.error(f"Error removing temporary PDF file {pdf_path}: {e}")
                        break # Break for other types of OSError (e.g., permissions)
                except Exception as e:
                    logger.error(f"Unexpected error during temporary PDF file removal {pdf_path}: {e}")
                    break # Break for any other unexpected error
            else: # This 'else' block executes if the 'for' loop completes without a 'break'
                logger.error(f"Failed to remove temporary PDF file {pdf_path} after {max_retries} attempts. It might be permanently locked by another process.")


# --- LangChain Prompt Templates and Parsers ---
# These are used to structure the input to the LLM and parse its output.

resume_info_parser = PydanticOutputParser(pydantic_object=ResumeInfo)
# >>> START OF CHANGE 2 <<<
resume_extraction_prompt_template = PromptTemplate(
    template="""Analyze the following resume text and extract the key information.
    Focus on accuracy and completeness for each field.
    
    For 'optimized_search_keywords', generate a list of 5-10 highly relevant keywords (e.g., specific technologies, roles, industries) that would be ideal for searching job boards, based on the entire resume content.
    
    For 'experience_years', **STRICTLY calculate the total number of full years of professional work experience by summing the duration of all distinct 'work_experience' entries.**
    - If a role is "Feb 2017 - Present" (current date July 2025), that's 8 years.
    - If a role is "Oct 2024 - Present", that's 0 years (less than a full year).
    - If dates overlap, count the overlapping period only once towards the total.
    - Provide a reasonable estimate if dates are ambiguous, but prioritize explicit durations.
    - If no work experience is listed, or if all listed experience is less than one full year, then output 0.
    
    {format_instructions}

    Resume Text:
    {resume_text}
    """,
    input_variables=["resume_text"],
    partial_variables={"format_instructions": resume_info_parser.get_format_instructions()},
)
# >>> END OF CHANGE 2 <<<

experience_parser = PydanticOutputParser(pydantic_object=ExperienceRequirement)
experience_extraction_prompt_template = PromptTemplate(
    template="""Analyze the following job description to determine the minimum years of experience required and infer the general seniority level.
    
    1.  **Extract Minimum Years (as an integer):**
        * Look for explicit mentions like "X years", "X+ years", "minimum X years", or "X-Y years" (take X).
        * If the job description explicitly says "no experience required", "entry-level", or "internship", set 'minimum_years_experience_required' to 0.
        * If no explicit number is given, but seniority is strongly implied, infer a number based on common industry standards:
            * "entry-level", "intern", "graduate": infer 0 years.
            * "junior", "associate": infer 1 year.
            * "mid-level": infer 3 years.
            * "senior": infer 6 years.
            * "lead", "principal", "staff", "director", "expert": infer 10 years.
        * If no specific number or clear inference is possible, set 'minimum_years_experience_required' to null.

    2.  **Infer Seniority Level:**
        * Choose one from: "entry-level", "junior", "mid-level", "senior", "lead", "principal", "staff", "director", "expert", "associate", "intern", "graduate", "unknown".
        * Base this on explicit titles, common phrases, or the inferred minimum years of experience.
        * Prioritize explicit mentions in the job title/description.

    {format_instructions}

    Job Description:
    {job_description}
    """,
    input_variables=["job_description"],
    partial_variables={"format_instructions": experience_parser.get_format_instructions()},
)

job_category_parser = PydanticOutputParser(pydantic_object=JobCategory)
job_category_prompt_template = PromptTemplate(
    template="""Categorize the following job title into one of these predefined categories. Choose the single best fit.
    Categories: Software Development / IT, Data Science / Analytics, Engineering, Business / Management / Product, Marketing / Public Relations / Advertising, Finance / Accounting / Consulting, Healthcare / Medical, Education / Training, Law Enforcement / Security, Hospitality / Food Service, Retail / Sales, Customer Service / Support, Human Resources, Legal, Arts / Design / Creative, Transportation / Logistics / Supply Chain, Construction / Trades, Government / Public Service / Non-Profit, Environmental / Agriculture, Science / Lab, Research / Academia, Media / Communications, Sports / Fitness / Recreation, Administration / Clerical, Manufacturing / Production, Other / General.
    If none of the above categories are a perfect fit, use "Other / General".
    {format_instructions}

    Job Title:
    {job_title}
    """,
    input_variables=["job_title"],
    partial_variables={"format_instructions": job_category_parser.get_format_instructions()},
)

# --- LLM Invocation Functions ---

def parse_resume(resume_text: str, llm_model_instance) -> Optional[ResumeInfo]:
    """Parses resume text using the LLM to extract structured ResumeInfo."""
    logger.info("--- 2. Performing AI analysis using Gemini ---")
    if llm_model_instance is None:
        logger.error("LLM model instance is None for resume parsing. Cannot parse resume.")
        return None
    try:
        # Basic check for meaningful text before sending to LLM
        if not resume_text or len(resume_text) < 50: 
            logger.warning("Resume text is too short or empty for AI analysis. Returning None.")
            return None

        resume_extraction_chain = resume_extraction_prompt_template | llm_model_instance | resume_info_parser
        llm_response = resume_extraction_chain.invoke({"resume_text": resume_text})
        logger.info("AI analysis complete for resume.")
        return llm_response
    except ValidationError as e:
        logger.error(f"Pydantic validation error during resume parsing: {e}. Check LLM output format.")
        return None
    except Exception as e:
        logger.error(f"Error during AI resume parsing: {e}. Check API key, model access, or input text.")
        return None

def extract_experience_from_job_description(job_description: str, llm_model_instance) -> ExperienceRequirement:
    """Extracts experience requirements from a job description using the LLM."""
    if llm_model_instance is None:
        logger.error("LLM model instance is None for experience extraction. Returning default ExperienceRequirement.")
        return ExperienceRequirement()
    try:
        experience_extraction_chain = experience_extraction_prompt_template | llm_model_instance | experience_parser
        llm_response = experience_extraction_chain.invoke({"job_description": job_description})
        logger.info(f"Experience Extraction Result: {llm_response.dict()}") # Log the result for debugging
        return llm_response
    except ValidationError as e:
        logger.warning(f"Pydantic validation error extracting experience: {e}. Returning default ExperienceRequirement.")
        return ExperienceRequirement() # Return default if validation fails
    except Exception as e:
        logger.error(f"Error during experience extraction from job description: {e}. Returning default ExperienceRequirement.")
        return ExperienceRequirement()

def categorize_job_with_llm(job_title: str, llm_model_instance) -> str:
    """Categorizes a job title using the LLM into a predefined category."""
    if llm_model_instance is None:
        logger.error("LLM model instance is None for job categorization. Returning 'Other / General'.")
        return "Other / General"
    try:
        job_category_chain = job_category_prompt_template | llm_model_instance | job_category_parser
        llm_response = job_category_chain.invoke({"job_title": job_title})
        logger.info(f"Job Categorization Result for '{job_title}': {llm_response.category}")
        return llm_response.category
    except ValidationError as e:
        logger.warning(f"Pydantic validation error categorizing job: {e}. Returning 'Other / General'.")
        return "Other / General"
    except Exception as e:
        logger.error(f"Error during job categorization: {e}. Returning 'Other / General'.")
        return "Other / General"