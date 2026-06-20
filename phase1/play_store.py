import logging
from datetime import datetime, timezone, timedelta
from google_play_scraper import reviews, Sort

logger = logging.getLogger(__name__)

def fetch_play_store_reviews(package_name: str, window_weeks: int) -> list:
    """
    Fetches customer reviews for the given Play Store package name (within the configured window of weeks).
    Returns a list of reviews mapped to the normalized schema.
    """
    reviews_list = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(weeks=window_weeks)
    
    continuation_token = None
    max_batches = 10  # Fetch up to 10 batches of 200 = 2000 reviews max
    batch_count = 200
    
    for batch_num in range(max_batches):
        try:
            logger.info(f"Fetching Play Store batch {batch_num + 1}...")
            
            if continuation_token:
                # Fetch next page using continuation token
                result, continuation_token = reviews(
                    package_name,
                    continuation_token=continuation_token
                )
            else:
                # Fetch first page
                result, continuation_token = reviews(
                    package_name,
                    lang='en',
                    country='in',
                    sort=Sort.NEWEST,
                    count=batch_count
                )
                
            if not result:
                logger.info("No reviews returned in this batch.")
                break
                
            batch_added = 0
            batch_filtered = 0
            
            for review in result:
                review_id = review.get('reviewId')
                rating = review.get('score')
                text = review.get('content')
                dt = review.get('at')  # This is a python datetime object
                
                if not review_id or rating is None or text is None or dt is None:
                    continue
                
                # Make datetime timezone-aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                    
                # Apply date window filter
                if dt < cutoff_date:
                    batch_filtered += 1
                    continue
                    
                # Synthesize a non-empty title from the text body to pass strict validation
                words = text.split()
                if words:
                    title_words = words[:5]
                    title = " ".join(title_words)
                    if len(words) > 5:
                        title += "..."
                else:
                    title = "Play Store Review"
                    
                normalized_review = {
                    "id": str(review_id),
                    "store": "play_store",
                    "rating": int(rating),
                    "title": str(title),
                    "text": str(text),
                    "date": dt.isoformat()
                }
                
                reviews_list.append(normalized_review)
                batch_added += 1
                
            logger.info(f"Batch {batch_num + 1}: Added {batch_added} reviews, filtered out {batch_filtered} older than window.")
            
            # Early stop if all reviews in the batch were older than the window
            if batch_added == 0 and batch_filtered > 0:
                logger.info("Stopping Play Store fetch: reached reviews older than the window.")
                break
                
            if not continuation_token:
                logger.info("No continuation token returned. End of reviews.")
                break
                
        except Exception as err:
            logger.error(f"Error fetching Play Store reviews in batch {batch_num + 1}: {err}")
            break
            
    logger.info(f"Completed Play Store fetch. Total reviews gathered: {len(reviews_list)}")
    return reviews_list
