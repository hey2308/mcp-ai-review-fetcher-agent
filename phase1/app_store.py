import logging
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

def fetch_app_store_reviews(app_id: str, window_weeks: int) -> list:
    """
    Fetches customer reviews for the given App Store ID (within the configured window of weeks).
    Returns a list of reviews mapped to the normalized schema.
    """
    reviews_list = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(weeks=window_weeks)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # The feed allows pagination up to 10 pages
    for page in range(1, 11):
        url = f"https://itunes.apple.com/in/rss/customerreviews/page={page}/id={app_id}/sortBy=mostRecent/json"
        try:
            logger.info(f"Fetching App Store page {page} from RSS feed...")
            response = requests.get(url, headers=headers, timeout=15)
            
            # Apple feed can return 400/404 if page limits are exceeded or empty
            if response.status_code != 200:
                logger.warning(f"App Store page {page} returned status code {response.status_code}")
                break
                
            data = response.json()
            feed = data.get("feed", {})
            entries = feed.get("entry", [])
            
            if not entries:
                logger.info(f"No entries found on page {page}.")
                break
                
            # If there's only one review, 'entry' might be a dict instead of a list
            if isinstance(entries, dict):
                entries = [entries]
                
            page_added = 0
            page_filtered = 0
            
            for entry in entries:
                # Skip the metadata entry (which usually has no rating or is of type application)
                if "im:rating" not in entry or "content" not in entry:
                    continue
                
                # Extract fields
                try:
                    review_id = entry["id"]["label"]
                    rating = int(entry["im:rating"]["label"])
                    title = entry["title"]["label"]
                    text = entry["content"]["label"]
                    date_str = entry["updated"]["label"]
                    
                    # Parse date and normalize timezone
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                        
                    # Apply date window filter
                    if dt < cutoff_date:
                        page_filtered += 1
                        continue
                        
                    # Map to schema
                    normalized_review = {
                        "id": str(review_id),
                        "store": "app_store",
                        "rating": rating,
                        "title": str(title),
                        "text": str(text),
                        "date": dt.isoformat()
                    }
                    
                    reviews_list.append(normalized_review)
                    page_added += 1
                    
                except (KeyError, ValueError) as parse_err:
                    logger.error(f"Error parsing review entry on page {page}: {parse_err}")
                    continue
            
            logger.info(f"Page {page}: Added {page_added} reviews, filtered out {page_filtered} older than window.")
            
            # If all reviews on this page were filtered out (older than window), we can stop fetching subsequent pages
            # since the RSS feed is reverse-chronological (most recent first).
            if page_added == 0 and page_filtered > 0:
                logger.info("Stopping RSS fetch: all reviews on this page are outside the time window.")
                break
                
        except requests.RequestException as req_err:
            logger.error(f"Network error fetching page {page} from App Store RSS: {req_err}")
            break
        except Exception as err:
            logger.error(f"Unexpected error fetching page {page} from App Store RSS: {err}")
            break
            
    logger.info(f"Completed App Store fetch. Total reviews gathered: {len(reviews_list)}")
    return reviews_list
