import os
import re
import yaml
import json
import logging
import hashlib
from datetime import datetime, timezone, timedelta
import uuid

# Set up logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ingest")

from phase1.app_store import fetch_app_store_reviews
from phase1.play_store import fetch_play_store_reviews

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F700-\U0001F77F"  # alchemical symbols
    "\U0001F780-\U0001F7FF"  # geometric shapes extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows-c
    "\U0001F900-\U0001F9FF"  # supplemental symbols and pictographs
    "\U0001FA00-\U0001FAFF"  # chess symbols, symbols and pictographs extended-a
    "\U00002700-\U000027BF"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed characters
    "]+",
    flags=re.UNICODE,
)

def load_config(config_path="config.yaml") -> dict:
    """Loads configuration from YAML file."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def get_review_hash(title: str, text: str) -> str:
    """Computes a deduplication hash of normalized title + text."""
    combined = f"{title} {text}"
    # Lowercase
    normalized = combined.lower()
    # Strip punctuation
    normalized = re.sub(r'[^\w\s]', '', normalized)
    # Collapse multiple whitespaces and strip
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    # SHA-256 hash
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def count_words(text: str) -> int:
    """Returns token count using word-like regex."""
    return len(re.findall(r"\b[\w']+\b", text))

def contains_emoji(text: str) -> bool:
    """Returns True if text contains any emoji codepoint."""
    return bool(EMOJI_PATTERN.search(text))

def is_english_only_text(text: str) -> bool:
    """
    Keeps text that uses basic English-compatible characters.
    Rejects if non-ASCII letters/symbols are present (except common punctuation/whitespace).
    """
    return all(ord(ch) < 128 for ch in text)

def validate_record(record: dict, cutoff_date: datetime) -> tuple[bool, str]:
    """
    Validates a normalized review record.
    Returns (is_valid, error_reason).
    """
    # 1. Required fields
    required_fields = ["id", "store", "rating", "title", "text", "date"]
    for field in required_fields:
        if field not in record:
            return False, f"Missing required field: {field}"
        if not str(record[field]).strip() and field != "title": # Title is allowed to be empty string if it maps, but AC-1.3 says title is non-empty string.
            return False, f"Empty required field: {field}"
        if field == "title" and not str(record[field]).strip():
            return False, "Empty required field: title"

    text_value = str(record["text"])
    title_value = str(record["title"])

    # 1.1 Minimum text length check (at least 6 words)
    if count_words(text_value) < 6:
        return False, "Review text has fewer than 6 words"

    # 1.2 Emoji filter
    if contains_emoji(text_value) or contains_emoji(title_value):
        return False, "Review contains emoji"

    # 1.3 Language filter (English-only heuristic)
    if not is_english_only_text(text_value) or not is_english_only_text(title_value):
        return False, "Review contains non-English characters"

    # 2. Rating range check (1-5)
    try:
        rating = int(record["rating"])
        if rating < 1 or rating > 5:
            return False, f"Rating {rating} out of range [1, 5]"
    except (ValueError, TypeError):
        return False, f"Rating {record['rating']} is not an integer"

    # 3. Store enum check
    if record["store"] not in ["app_store", "play_store"]:
        return False, f"Invalid store: {record['store']}"

    # 4. Date validation and parseability
    try:
        dt = datetime.fromisoformat(record["date"].replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
            
        # 5. Date window check
        if dt < cutoff_date:
            return False, f"Date {record['date']} is older than window cutoff {cutoff_date.isoformat()}"
    except Exception as parse_err:
        return False, f"Unparseable date format: {record['date']} ({parse_err})"

    return True, ""

def main():
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    
    logger.info(f"Starting Ingestion Run {run_id}...")
    
    # Initialize run log schema
    run_steps = []
    
    # 1. Load config
    step_start = datetime.now(timezone.utc).isoformat()
    try:
        config = load_config()
        run_steps.append({
            "step": "load_configuration",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "output_summary": "Loaded config.yaml"
        })
    except Exception as err:
        logger.error(f"Failed to load configuration: {err}")
        run_steps.append({
            "step": "load_configuration",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failure",
            "error_message": str(err)
        })
        write_run_log(run_id, started_at, run_steps, "failure")
        return

    window_weeks = config.get("review_window_weeks", 10)
    app_id = config.get("app_store_id", "1404871703")
    package_name = config.get("play_store_package", "com.nextbillion.groww")
    cutoff_date = datetime.now(timezone.utc) - timedelta(weeks=window_weeks)
    
    # 2. Fetch App Store reviews
    step_start = datetime.now(timezone.utc).isoformat()
    app_store_raw = []
    try:
        app_store_raw = fetch_app_store_reviews(app_id, window_weeks)
        run_steps.append({
            "step": "fetch_app_store_reviews",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "output_summary": f"Fetched {len(app_store_raw)} reviews from App Store"
        })
    except Exception as err:
        logger.error(f"Failed App Store ingestion: {err}")
        run_steps.append({
            "step": "fetch_app_store_reviews",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failure",
            "error_message": str(err)
        })
        # Proceed to Play Store even if App Store failed, but the merge step will fail AC check

    # 3. Fetch Play Store reviews
    step_start = datetime.now(timezone.utc).isoformat()
    play_store_raw = []
    try:
        play_store_raw = fetch_play_store_reviews(package_name, window_weeks)
        run_steps.append({
            "step": "fetch_play_store_reviews",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "output_summary": f"Fetched {len(play_store_raw)} reviews from Play Store"
        })
    except Exception as err:
        logger.error(f"Failed Play Store ingestion: {err}")
        run_steps.append({
            "step": "fetch_play_store_reviews",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failure",
            "error_message": str(err)
        })

    # 4. Merge and Deduplicate
    step_start = datetime.now(timezone.utc).isoformat()
    merged_reviews = app_store_raw + play_store_raw
    logger.info(f"Merged total raw reviews: {len(merged_reviews)}")
    
    unique_reviews = []
    seen_hashes = set()
    dedup_count = 0
    
    for review in merged_reviews:
        h = get_review_hash(review["title"], review["text"])
        if h in seen_hashes:
            dedup_count += 1
            continue
        seen_hashes.add(h)
        unique_reviews.append(review)
        
    logger.info(f"Deduplication completed. Removed {dedup_count} duplicates. Unique count: {len(unique_reviews)}")
    
    # 5. Validation and Filtering
    validated_reviews = []
    malformed_count = 0
    out_of_range_rating_count = 0
    out_of_window_count = 0
    unparseable_date_count = 0
    validation_failures = []
    short_text_count = 0
    emoji_present_count = 0
    non_english_count = 0
    
    for review in unique_reviews:
        is_valid, reason = validate_record(review, cutoff_date)
        if not is_valid:
            validation_failures.append({"review_id": review.get("id"), "reason": reason})
            if "Missing required field" in reason or "Empty required field" in reason:
                malformed_count += 1
            elif "Rating" in reason:
                out_of_range_rating_count += 1
            elif "Date" in reason and "older than window" in reason:
                out_of_window_count += 1
            elif "date format" in reason:
                unparseable_date_count += 1
            elif "fewer than 6 words" in reason:
                short_text_count += 1
            elif "contains emoji" in reason:
                emoji_present_count += 1
            elif "non-English" in reason:
                non_english_count += 1
            continue
        validated_reviews.append(review)
        
    total_unique = len(unique_reviews)
    
    # Rule evaluation based on phase 1 evaluation thresholds
    halt_execution = False
    halt_reason = ""
    
    # AC-1.3 failure threshold check: if > 5% malformed, halt
    if total_unique > 0 and (malformed_count / total_unique) > 0.05:
        halt_execution = True
        halt_reason = f"Halted: Malformed records ({malformed_count}) exceeded 5% of unique reviews ({total_unique})"
        
    # AC-1.8 failure threshold check: if > 10% unparseable dates, halt
    if total_unique > 0 and (unparseable_date_count / total_unique) > 0.10:
        halt_execution = True
        halt_reason = f"Halted: Unparseable dates ({unparseable_date_count}) exceeded 10% of unique reviews ({total_unique})"

    # AC-1.5 date window warning/investigate threshold check: if > 20% out of window
    if total_unique > 0 and (out_of_window_count / total_unique) > 0.20:
        logger.warning(f"More than 20% of fetched reviews ({out_of_window_count}) were out of the time window. Verify source dates.")

    if halt_execution:
        logger.error(halt_reason)
        run_steps.append({
            "step": "merge_deduplicate_validate",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failure",
            "error_message": halt_reason
        })
        write_run_log(run_id, started_at, run_steps, "failure")
        return
    
    if validation_failures:
        logger.warning(f"Discarded {len(validation_failures)} invalid reviews during parsing. Reasons:")
        for fail in validation_failures[:10]:
            logger.warning(f"  ID: {fail['review_id']} - Reason: {fail['reason']}")
        if len(validation_failures) > 10:
            logger.warning(f"  ... and {len(validation_failures) - 10} more.")

    run_steps.append({
        "step": "merge_deduplicate_validate",
        "started_at": step_start,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "success",
        "output_summary": (
            f"Merged {len(merged_reviews)} raw, deduplicated {dedup_count}, "
            f"discarded {len(validation_failures)} invalid, kept {len(validated_reviews)} clean reviews. "
            f"Filtered short_text={short_text_count}, emoji={emoji_present_count}, non_english={non_english_count}."
        )
    })

    # 6. Save Output
    step_start = datetime.now(timezone.utc).isoformat()
    os.makedirs("data", exist_ok=True)
    output_path = "data/reviews_raw.json"
    
    try:
        with open(output_path, "w") as out_f:
            json.dump(validated_reviews, out_f, indent=2)
            
        logger.info(f"Successfully saved {len(validated_reviews)} reviews to {output_path}")
        
        # Ingestion summary for logging
        app_count = sum(1 for r in validated_reviews if r["store"] == "app_store")
        play_count = sum(1 for r in validated_reviews if r["store"] == "play_store")
        
        dates = [datetime.fromisoformat(r["date"]) for r in validated_reviews]
        date_min = min(dates).isoformat() if dates else "N/A"
        date_max = max(dates).isoformat() if dates else "N/A"
        
        summary_info = (
            f"Total clean records: {len(validated_reviews)} "
            f"(App Store: {app_count}, Play Store: {play_count}). "
            f"Date range: {date_min} to {date_max}. Deduplicated: {dedup_count}."
        )
        logger.info(f"Run Summary: {summary_info}")
        
        run_steps.append({
            "step": "save_output",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "output_summary": summary_info
        })
        
        write_run_log(run_id, started_at, run_steps, "success")
        
    except Exception as err:
        logger.error(f"Failed to write output file: {err}")
        run_steps.append({
            "step": "save_output",
            "started_at": step_start,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failure",
            "error_message": str(err)
        })
        write_run_log(run_id, started_at, run_steps, "failure")

def write_run_log(run_id: str, started_at: str, steps: list, final_status: str):
    """Writes the execution progress run_log.json."""
    os.makedirs("data", exist_ok=True)
    log_path = "data/run_log.json"
    
    log_data = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "final_status": final_status,
        "steps": steps
    }
    
    # Read existing runs or start new
    runs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                runs = json.load(f)
                if isinstance(runs, dict):
                    runs = [runs]
        except Exception:
            runs = []
            
    runs.append(log_data)
    
    try:
        with open(log_path, "w") as f:
            json.dump(runs, f, indent=2)
        logger.info(f"Execution log written to {log_path}")
    except Exception as e:
        logger.error(f"Failed to write run log: {e}")

if __name__ == "__main__":
    main()
