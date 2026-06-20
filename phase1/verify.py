import os
import re
import yaml
import json
import logging
import hashlib
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("verify")

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)

def load_config(config_path="config.yaml") -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def get_review_hash(title: str, text: str) -> str:
    combined = f"{title} {text}"
    normalized = combined.lower()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))

def contains_emoji(text: str) -> bool:
    return bool(EMOJI_PATTERN.search(text))

def is_english_only_text(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)

def run_verification() -> bool:
    logger.info("Starting automated verification for Phase 1 output dataset...")
    
    # Check if config exists
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"FAIL: Could not load configuration: {e}")
        return False
        
    window_weeks = config.get("review_window_weeks", 10)
    cutoff_date = datetime.now(timezone.utc) - timedelta(weeks=window_weeks)
    
    # Check if output file exists
    output_path = "data/reviews_raw.json"
    if not os.path.exists(output_path):
        logger.error(f"FAIL: Output file not found at {output_path}")
        return False
        
    try:
        with open(output_path, "r") as f:
            reviews = json.load(f)
    except Exception as e:
        logger.error(f"FAIL: Could not parse output JSON file: {e}")
        return False
        
    total_count = len(reviews)
    logger.info(f"Loaded {total_count} reviews from {output_path}")
    
    results = {}
    
    # AC-1.1 — Minimum Review Volume
    ac_1_1 = total_count >= 100
    results["AC-1.1: Minimum Review Volume (>= 100)"] = (ac_1_1, f"Found {total_count} reviews total.")
    
    # AC-1.2 — Both Stores Represented
    app_store_count = sum(1 for r in reviews if r.get("store") == "app_store")
    play_store_count = sum(1 for r in reviews if r.get("store") == "play_store")
    ac_1_2 = app_store_count > 0 and play_store_count > 0
    results["AC-1.2: Both Stores Represented (App Store & Play Store)"] = (
        ac_1_2, 
        f"App Store reviews: {app_store_count}, Play Store reviews: {play_store_count}."
    )
    
    # AC-1.3 — All Records Have Required Fields
    # AC-1.4 — Rating Range Validity
    # AC-1.5 — Date Window Compliance
    # AC-1.6 — No PII Fields in Schema
    # AC-1.7 — No Duplicate Records
    # AC-1.8 — Date Field is Parseable
    
    ac_1_3_passed = True
    ac_1_3_reasons = []
    
    ac_1_4_passed = True
    ac_1_4_reasons = []
    
    ac_1_5_passed = True
    ac_1_5_reasons = []
    
    ac_1_6_passed = True
    ac_1_6_reasons = []
    
    ac_1_7_passed = True
    seen_hashes = set()
    duplicate_hashes_found = 0
    
    ac_1_8_passed = True
    ac_1_8_reasons = []

    # AC-1.9 — Minimum Word Count (>= 6 words in text)
    ac_1_9_passed = True
    ac_1_9_reasons = []

    # AC-1.10 — No Emoji
    ac_1_10_passed = True
    ac_1_10_reasons = []

    # AC-1.11 — English-only text
    ac_1_11_passed = True
    ac_1_11_reasons = []
    
    pii_keys_to_check = ["reviewer_name", "user_id", "device_model", "os_version", "author", "username", "email"]
    
    for idx, r in enumerate(reviews):
        # AC-1.3 Check Required Fields
        required_fields = ["id", "store", "rating", "title", "text", "date"]
        missing_or_empty = []
        for field in required_fields:
            if field not in r:
                missing_or_empty.append(f"missing {field}")
            elif not str(r[field]).strip():
                missing_or_empty.append(f"empty {field}")
        if missing_or_empty:
            ac_1_3_passed = False
            ac_1_3_reasons.append(f"Record {idx} (ID: {r.get('id', 'N/A')}): {', '.join(missing_or_empty)}")
            
        # AC-1.4 Check Rating Range
        rating = r.get("rating")
        if rating is not None:
            try:
                rating_int = int(rating)
                if rating_int < 1 or rating_int > 5:
                    ac_1_4_passed = False
                    ac_1_4_reasons.append(f"Record {idx} (ID: {r.get('id')}): Rating {rating_int} out of range [1, 5]")
            except (ValueError, TypeError):
                ac_1_4_passed = False
                ac_1_4_reasons.append(f"Record {idx} (ID: {r.get('id')}): Rating {rating} is not an integer")
                
        # AC-1.6 Check No PII Fields in Schema Keys
        found_pii_keys = [k for k in pii_keys_to_check if k in r]
        if found_pii_keys:
            ac_1_6_passed = False
            ac_1_6_reasons.append(f"Record {idx} (ID: {r.get('id')}): Contains keys {found_pii_keys}")
            
        # AC-1.8 Check Date Parseability
        date_str = r.get("date")
        dt_parsed = None
        if date_str:
            try:
                dt_parsed = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if dt_parsed.tzinfo is None:
                    dt_parsed = dt_parsed.replace(tzinfo=timezone.utc)
            except Exception as e:
                ac_1_8_passed = False
                ac_1_8_reasons.append(f"Record {idx} (ID: {r.get('id')}): Date {date_str} fails parsing ({e})")

        # AC-1.9 Check minimum word count
        text_value = str(r.get("text", ""))
        if count_words(text_value) < 6:
            ac_1_9_passed = False
            ac_1_9_reasons.append(f"Record {idx} (ID: {r.get('id')}): Text has fewer than 6 words")

        # AC-1.10 Check emoji-free content
        title_value = str(r.get("title", ""))
        if contains_emoji(title_value) or contains_emoji(text_value):
            ac_1_10_passed = False
            ac_1_10_reasons.append(f"Record {idx} (ID: {r.get('id')}): Contains emoji")

        # AC-1.11 Check English-only text heuristic
        if not is_english_only_text(title_value) or not is_english_only_text(text_value):
            ac_1_11_passed = False
            ac_1_11_reasons.append(f"Record {idx} (ID: {r.get('id')}): Contains non-English characters")
                
        # AC-1.5 Check Date Window Compliance (depends on parseability)
        if dt_parsed:
            if dt_parsed < cutoff_date:
                ac_1_5_passed = False
                ac_1_5_reasons.append(f"Record {idx} (ID: {r.get('id')}): Date {dt_parsed.isoformat()} is before cutoff {cutoff_date.isoformat()}")
                
        # AC-1.7 Check Deduplication
        if r.get("title") is not None and r.get("text") is not None:
            h = get_review_hash(r["title"], r["text"])
            if h in seen_hashes:
                duplicate_hashes_found += 1
                ac_1_7_passed = False
            else:
                seen_hashes.add(h)
                
    results["AC-1.3: Required Fields Present & Non-Empty"] = (
        ac_1_3_passed, 
        "All records pass." if ac_1_3_passed else f"Malformed records found: {len(ac_1_3_reasons)}. First few: {ac_1_3_reasons[:3]}"
    )
    
    results["AC-1.4: Rating Range Validity [1, 5]"] = (
        ac_1_4_passed, 
        "All ratings valid." if ac_1_4_passed else f"Invalid ratings found: {len(ac_1_4_reasons)}. First few: {ac_1_4_reasons[:3]}"
    )
    
    results["AC-1.5: Date Window Compliance"] = (
        ac_1_5_passed, 
        "All dates inside window." if ac_1_5_passed else f"Out of window records found: {len(ac_1_5_reasons)}. First few: {ac_1_5_reasons[:3]}"
    )
    
    results["AC-1.6: PII Fields Excluded from Schema"] = (
        ac_1_6_passed, 
        "All schema keys sanitized." if ac_1_6_passed else f"PII keys found: {len(ac_1_6_reasons)}. First few: {ac_1_6_reasons[:3]}"
    )
    
    results["AC-1.7: No Duplicate Records"] = (
        ac_1_7_passed, 
        "All records unique." if ac_1_7_passed else f"Found {duplicate_hashes_found} duplicates."
    )
    
    results["AC-1.8: Date Field Parseable as ISO 8601"] = (
        ac_1_8_passed, 
        "All dates parseable." if ac_1_8_passed else f"Unparseable dates: {len(ac_1_8_reasons)}. First few: {ac_1_8_reasons[:3]}"
    )

    results["AC-1.9: Minimum Review Text Length (>= 6 words)"] = (
        ac_1_9_passed,
        "All records meet minimum word count." if ac_1_9_passed else f"Too-short texts: {len(ac_1_9_reasons)}. First few: {ac_1_9_reasons[:3]}"
    )

    results["AC-1.10: Emoji-Free Reviews"] = (
        ac_1_10_passed,
        "No emojis found." if ac_1_10_passed else f"Emoji-containing reviews: {len(ac_1_10_reasons)}. First few: {ac_1_10_reasons[:3]}"
    )

    results["AC-1.11: English-Only Reviews"] = (
        ac_1_11_passed,
        "All reviews pass English-only filter." if ac_1_11_passed else f"Non-English reviews: {len(ac_1_11_reasons)}. First few: {ac_1_11_reasons[:3]}"
    )
    
    # Summary report
    logger.info("=== VERIFICATION RESULTS ===")
    all_passed = True
    for check, (status, detail) in results.items():
        status_str = "PASS" if status else "FAIL"
        logger.info(f"[{status_str}] {check} - {detail}")
        if not status:
            all_passed = False
            
    logger.info("=============================")
    if all_passed:
        logger.info("VERIFICATION COMPLETED: ALL AUTOMATED CHECKS PASSED!")
    else:
        logger.error("VERIFICATION COMPLETED: SOME AUTOMATED CHECKS FAILED.")
        
    return all_passed

if __name__ == "__main__":
    run_verification()
