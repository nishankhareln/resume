import requests
import json
from typing import List, Dict
import logging
from dotenv import load_dotenv
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get API credentials from environment variables
JSEARCH_RAPIDAPI_KEY = os.getenv("JSEARCH_RAPIDAPI_KEY")
JSEARCH_RAPIDAPI_HOST = os.getenv("JSEARCH_RAPIDAPI_HOST")

# No longer needed as we're hardcoding to "us"
# COUNTRY_CODE_MAP = {
#     "United States": "us",
#     "India": "in",
# }

# Removed country_code and location parameters, hardcoding to "us"
def get_jobs_from_api(keywords: List[str], max_results: int = 50) -> List[Dict]:
    if not JSEARCH_RAPIDAPI_KEY or not JSEARCH_RAPIDAPI_HOST:
        logger.error("JSEARCH_RAPIDAPI_KEY or JSEARCH_RAPIDAPI_HOST is not set. Cannot fetch jobs.")
        return []

    # Hardcode country to "us"
    country_code = "us"
    logger.info(f"Fetching jobs for country: {country_code}, keywords: {keywords}")
    
    url = f"https://{JSEARCH_RAPIDAPI_HOST}/search"
    headers = {
        "x-rapidapi-host": JSEARCH_RAPIDAPI_HOST,
        "x-rapidapi-key": JSEARCH_RAPIDAPI_KEY,
        "content-type": "application/json"
    }

    # Use only the first 3 keywords to avoid overly specific queries
    keyword_query = " ".join(keywords[:3])
    
    # Query will now just be keywords, for broader US search
    query = keyword_query 

    querystring = {
        "query": query,
        "page": "1",
        "num_pages": "1",
        "country": country_code, # Hardcoded
        "language": "en"
    }

    logger.info(f"Constructed API query: {querystring['query']}")

    jobs = []
    try:
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        try:
            data = response.json()
            logger.info(f"Raw API response: {json.dumps(data, indent=2)}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}. Raw response: {response.text}")
            return []

        if data and 'data' in data and isinstance(data['data'], list):
            for job in data['data']:
                jobs.append({
                    "title": job.get("job_title", "N/A"),
                    "company": job.get("employer_name", "N/A"),
                    "location": f"{job.get('job_city', 'N/A')}, {job.get('job_country', 'N/A')}",
                    "description": job.get("job_description", "No description available."),
                    "salary": job.get("job_salary", "N/A"),
                    "posted_at": job.get("job_posted_at_datetime_utc", "N/A"),
                    "apply_link": job.get("job_apply_link", "#")
                })
                if len(jobs) >= max_results:
                    break
            logger.info(f"Successfully fetched {len(jobs)} jobs from JSearch API.")
        else:
            logger.warning(f"No 'data' key or empty data returned from JSearch API. Response: {data}")
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error fetching jobs: {e.response.status_code} - {e.response.text}")
        if e.response.status_code == 401:
            logger.error("Authentication failed. Check JSEARCH_RAPIDAPI_KEY in .env file.")
        elif e.response.status_code == 429:
            logger.error("Rate limit exceeded. Check RapidAPI quota for JSearch API.")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error fetching jobs: {e}")
    except requests.exceptions.Timeout:
        logger.error("Timeout error fetching jobs.")
    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred while fetching jobs: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred in get_jobs_from_api: {e}")

    return jobs