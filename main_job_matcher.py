import logging
from typing import List, Dict, Optional, Tuple
from sklearn.metrics.pairwise import cosine_similarity
from app import ResumeInfo, extract_experience_from_job_description, categorize_job_with_llm
from job_portal import get_jobs_from_api
from merojob_client import get_jobs_from_merojob

logger = logging.getLogger(__name__)

preferred_tab_order = [
    "Software Development / IT", "Data Science / Analytics", "Engineering",
    "Business / Management / Product", "Finance / Accounting / Consulting",
    "Marketing / Public Relations / Advertising", "Healthcare / Medical",
    "Human Resources", "Legal", "Arts / Design / Creative",
    "Customer Service / Support", "Retail / Sales", "Hospitality / Food Service",
    "Education / Training", "Transportation / Logistics / Supply Chain",
    "Construction / Trades", "Government / Public Service / Non-Profit",
    "Environmental / Agriculture", "Science / Lab", "Research / Academia",
    "Media / Communications", "Sports / Fitness / Recreation", "Administration / Clerical",
    "Manufacturing / Production", "Law Enforcement / Security", "Other / General"
]

def generate_embedding(text: str, embeddings_model_instance) -> Optional[List[float]]:
    """Generates an embedding for the given text using the provided embeddings_model instance."""
    if embeddings_model_instance is None:
        logger.error("Embeddings model not initialized. Cannot generate embedding.")
        return None
    try:
        embedding = embeddings_model_instance.embed_documents([text])[0]
        return embedding
    except Exception as e:
        logger.error(f"Error generating embedding for text: '{text[:50]}...'. Error: {e}")
        return None

def calculate_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """Calculates cosine similarity between two embeddings."""
    if embedding1 is None or embedding2 is None:
        return 0.0
    try:
        return cosine_similarity([embedding1], [embedding2])[0][0]
    except Exception as e:
        logger.error(f"Error calculating similarity: {e}")
        return 0.0

def process_jobs(
    resume_info: ResumeInfo,
    llm_model_instance,
    embeddings_model_instance,
    country: str = "us",
) -> Tuple[List[Dict], Dict[str, List[Dict]]]:
    """
    Processes resume info, fetches jobs, calculates similarity, and categorizes them.
    Requires initialized LLM and Embeddings model instances.

    Args:
        country: "us" -> JSearch RapidAPI (default, existing behavior).
                 "np" -> merojob.com public API (Nepali jobs).
    """
    if llm_model_instance is None or embeddings_model_instance is None:
        logger.error("LLM or Embeddings model is not initialized in main_job_matcher. Cannot perform job matching.")
        return [], {}

    logger.info(f"Starting job processing (country={country})...")

    search_keywords = resume_info.optimized_search_keywords
    if not search_keywords and resume_info.job_title:
        search_keywords = [resume_info.job_title]

    if not search_keywords:
        logger.warning("Could not determine effective search keywords from your resume.")
        return [], {}

    if country == "np":
        fetched_jobs = get_jobs_from_merojob(search_keywords, max_results=30)
    else:
        fetched_jobs = get_jobs_from_api(search_keywords)

    if not fetched_jobs:
        logger.info("No jobs were fetched for your search criteria.")
        return [], {}

    logger.info(f"Generating embeddings for {len(fetched_jobs)} fetched jobs and resume...")

    resume_text_for_embedding = f"{resume_info.summary} {' '.join(resume_info.skills)} {' '.join([exp.title for exp in resume_info.work_experience])}"
    resume_embedding = generate_embedding(resume_text_for_embedding, embeddings_model_instance)

    if resume_embedding is None:
        logger.error("Failed to generate embedding for your resume. Cannot proceed with matching.")
        return [], {}

    matched_jobs = []
    categorized_matched_jobs = {category: [] for category in preferred_tab_order}

    for job in fetched_jobs:
        job_description = job.get('description', '')
        job_title = job.get('title', '')
        if not job_description and not job_title:
            continue

        job_embedding = generate_embedding(f"{job_title} {job_description}", embeddings_model_instance)

        if job_embedding is None:
            logger.warning(f"Skipping job '{job_title}' due to failed embedding generation.")
            continue

        similarity_score = calculate_similarity(resume_embedding, job_embedding)

        # --- REVISED Experience filtering logic ---
        job_experience_req = extract_experience_from_job_description(job_description, llm_model_instance)
        
        job['parsed_experience_req'] = job_experience_req.dict() # Store parsed experience for display and debugging

        resume_years = resume_info.experience_years if resume_info.experience_years is not None else 0
        job_min_years = job_experience_req.minimum_years_experience_required


        logger.debug(f"Job: '{job_title}', Resume Years: {resume_years}, Job Min Years: {job_min_years}, Job Inferred Level: {job_experience_req.inferred_level}")

        # Filter 1: If job explicitly requires more years than resume has
        if job_min_years is not None and resume_years < job_min_years:
            logger.debug(f"Filtering out '{job_title}' (Resume {resume_years}yrs < Job Min {job_min_years}yrs)")
            continue

        # Filter 2: Specific for 0-year experience candidates
        if resume_years == 0:
            # If a job requires ANY explicit years (e.g., 1+ years) or is high seniority, filter it out
            if (job_min_years is not None and job_min_years > 0) or \
               job_experience_req.inferred_level in ["junior", "mid-level", "senior", "lead", "principal", "staff", "director", "expert"]:
                logger.debug(f"Filtering out '{job_title}' (0-exp resume, but job requires {job_min_years}yrs or is {job_experience_req.inferred_level})")
                continue
        
        # Filter 3: General check for too much experience mismatch (e.g., junior applying for senior role)
        # This is a bit more subjective but helps prune
        # Example: If resume is < 3 years and job is explicitly senior/lead, filter
        if resume_years < 3 and job_experience_req.inferred_level in ["senior", "lead", "principal", "staff", "director", "expert"]:
             logger.debug(f"Filtering out '{job_title}' (Resume {resume_years}yrs, but job is {job_experience_req.inferred_level})")
             continue


        # --- End of REVISED Experience filtering logic ---

        if similarity_score < 0.70: # Keeping similarity threshold
            logger.debug(f"Skipping job '{job_title}' due to low similarity ({similarity_score:.2f})")
            continue

        job['similarity_score'] = similarity_score
        matched_jobs.append(job)

        category = categorize_job_with_llm(job_title, llm_model_instance)
        if category in categorized_matched_jobs:
            categorized_matched_jobs[category].append(job)
        else:
            categorized_matched_jobs[category] = [job]
            if category not in preferred_tab_order: # Dynamically add new categories
                preferred_tab_order.append(category)

    matched_jobs.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)
    for category, jobs_list in categorized_matched_jobs.items():
        jobs_list.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)

    logger.info(f"Finished job processing. Found {len(matched_jobs)} matched jobs.")
    return matched_jobs, categorized_matched_jobs