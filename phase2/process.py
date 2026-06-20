"""Phase 2 orchestrator: theme clustering and signal extraction."""

import argparse
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env from project root (if present)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from phase2.actions import generate_action_ideas
from phase2.classify import classify_batch
from phase2.groq_client import GroqBudgetExceeded, GroqClient
from phase2.pii_scrub import scrub_review
from phase2.pre_router import best_keyword_theme, pre_route_review
from phase2.quotes import select_quote_for_theme
from phase2.ranking import aggregate_themes, build_quote_candidates
from phase2.sentiment import final_sentiment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("process")


def load_config(config_path: str = "config.yaml") -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cap_reviews(reviews: list[dict], max_count: int) -> tuple[list[dict], int]:
    original = len(reviews)
    sorted_reviews = sorted(
        reviews,
        key=lambda r: r.get("date", ""),
        reverse=True,
    )
    capped = sorted_reviews[:max_count]
    return capped, original


def estimate_run_tokens(
    groq_queue_count: int,
    batch_size: int,
    featured_count: int = 3,
) -> int:
    classify_calls = max(1, (groq_queue_count + batch_size - 1) // batch_size) if groq_queue_count else 0
    classify_tokens = classify_calls * 3000
    quote_tokens = featured_count * 2000
    action_tokens = 4000
    return classify_tokens + quote_tokens + action_tokens


def write_run_log(run_id: str, started_at: str, steps: list, final_status: str) -> None:
    os.makedirs("data", exist_ok=True)
    log_path = "data/run_log.json"
    log_data = {
        "run_id": run_id,
        "phase": 2,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "final_status": final_status,
        "steps": steps,
    }
    runs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                runs = json.load(f)
                if isinstance(runs, dict):
                    runs = [runs]
        except Exception:
            runs = []
    runs.append(log_data)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2)


def _offline_action_ideas(featured: list[dict], quotes: list[dict]) -> list[str]:
    ideas = []
    for theme_row in featured:
        quote = next((q for q in quotes if q["theme"] == theme_row["name"]), None)
        snippet = quote["quote"][:80] if quote else "recent user feedback"
        ideas.append(
            f"Address {theme_row['name']} pain points highlighted in reviews "
            f"(e.g. \"{snippet}\") with a focused fix in the corresponding Groww flow."
        )
    return ideas[:3]


def main(offline: bool = False) -> None:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    steps: list[dict] = []

    logger.info("Starting Phase 2 run %s", run_id)

    try:
        config = load_config()
        steps.append(
            {
                "step": "load_configuration",
                "status": "success",
                "output_summary": "Loaded config.yaml",
            }
        )
    except Exception as err:
        logger.error("Failed to load config: %s", err)
        steps.append(
            {"step": "load_configuration", "status": "failure", "error_message": str(err)}
        )
        write_run_log(run_id, started_at, steps, "failure")
        return

    input_path = "data/reviews_raw.json"
    if not os.path.exists(input_path):
        logger.error("Input file missing: %s", input_path)
        steps.append(
            {
                "step": "load_reviews",
                "status": "failure",
                "error_message": f"Missing {input_path}",
            }
        )
        write_run_log(run_id, started_at, steps, "failure")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        all_reviews = json.load(f)

    max_reviews = int(config.get("max_reviews_to_process", 1000))
    reviews, original_count = cap_reviews(all_reviews, max_reviews)
    logger.info(
        "Loaded %d reviews (original=%d, cap=%d)",
        len(reviews),
        original_count,
        max_reviews,
    )
    steps.append(
        {
            "step": "cap_reviews",
            "status": "success",
            "output_summary": f"Processing {len(reviews)} of {original_count} reviews",
        }
    )

    pii_flagged = 0
    scrubbed_reviews = []
    for review in reviews:
        cleaned, had_pii = scrub_review(review)
        if had_pii:
            pii_flagged += 1
        scrubbed_reviews.append(cleaned)
    steps.append(
        {
            "step": "pii_scrub",
            "status": "success",
            "output_summary": f"Scrubbed {len(scrubbed_reviews)} reviews; flagged {pii_flagged} with embedded PII",
        }
    )

    pre_routed: list[dict] = []
    groq_queue: list[dict] = []
    for review in scrubbed_reviews:
        theme = pre_route_review(review)
        if theme:
            pre_routed.append(
                {
                    "review_id": review["id"],
                    "theme": theme,
                    "sentiment_score": final_sentiment(review["rating"], 0.0),
                    "source": "keyword",
                }
            )
        else:
            groq_queue.append(review)

    logger.info(
        "Pre-routed %d reviews; %d queued for Groq",
        len(pre_routed),
        len(groq_queue),
    )
    steps.append(
        {
            "step": "keyword_pre_route",
            "status": "success",
            "output_summary": (
                f"Pre-routed {len(pre_routed)}, queued {len(groq_queue)} for Groq classification"
            ),
        }
    )

    batch_size = int(config.get("llm_batch_size", 20))
    text_max_words = int(config.get("llm_text_max_words", 50))

    groq_classified: list[dict] = []
    client = None

    if offline:
        logger.warning("Running in OFFLINE mode — Groq calls skipped")
        for review in groq_queue:
            theme = best_keyword_theme(review)
            groq_classified.append(
                {
                    "review_id": review["id"],
                    "theme": theme,
                    "sentiment_score": final_sentiment(review["rating"], 0.0),
                    "source": "keyword_fallback",
                }
            )
        steps.append(
            {
                "step": "offline_classify",
                "status": "success",
                "output_summary": f"Keyword fallback classified {len(groq_classified)} reviews",
            }
        )
    else:
        client = GroqClient(
            model=config.get("llm_model", "llama-3.3-70b-versatile"),
            max_rpm=int(config.get("llm_max_rpm", 24)),
            max_tpm=int(config.get("llm_max_tpm", 10000)),
            max_tokens_per_run=int(config.get("llm_max_tokens_per_run", 90000)),
        )

        estimated_tokens = estimate_run_tokens(len(groq_queue), batch_size)
        logger.info("Pre-flight token estimate: %d", estimated_tokens)
        try:
            client.preflight_check(estimated_tokens)
        except GroqBudgetExceeded as err:
            logger.error("Pre-flight budget check failed: %s", err)
            steps.append(
                {
                    "step": "preflight_budget",
                    "status": "failure",
                    "error_message": str(err),
                }
            )
            write_run_log(run_id, started_at, steps, "failure")
            return

        try:
            for i in range(0, len(groq_queue), batch_size):
                batch = groq_queue[i : i + batch_size]
                logger.info(
                    "Classifying batch %d/%d (%d reviews)",
                    i // batch_size + 1,
                    max(1, (len(groq_queue) + batch_size - 1) // batch_size),
                    len(batch),
                )
                groq_classified.extend(classify_batch(client, batch, text_max_words))
            steps.append(
                {
                    "step": "groq_classify",
                    "status": "success",
                    "output_summary": f"Groq classified {len(groq_classified)} reviews in {(len(groq_queue) + batch_size - 1) // batch_size if groq_queue else 0} batches",
                }
            )
        except Exception as err:
            logger.error("Groq classification failed: %s", err)
            steps.append(
                {"step": "groq_classify", "status": "failure", "error_message": str(err)}
            )
            write_run_log(run_id, started_at, steps, "failure")
            return

    classifications = pre_routed + groq_classified
    reviews_by_id = {r["id"]: r for r in scrubbed_reviews}

    theme_rows = aggregate_themes(classifications, reviews_by_id)
    featured = [t for t in theme_rows if t["featured"]]
    featured.sort(key=lambda t: t["priority_score"], reverse=True)
    steps.append(
        {
            "step": "aggregate_rank",
            "status": "success",
            "output_summary": (
                "Top themes: "
                + ", ".join(f"{t['name']} ({t['review_count']})" for t in featured)
            ),
        }
    )

    quotes: list[dict] = []
    try:
        if offline:
            for theme_row in featured:
                candidates = build_quote_candidates(
                    theme_row["name"], classifications, reviews_by_id
                )
                if not candidates:
                    continue
                chosen = candidates[0]
                review = reviews_by_id[chosen["review_id"]]
                snippet = chosen["snippet"]
                if snippet not in review["text"]:
                    snippet = review["text"][:200].strip()
                quotes.append(
                    {
                        "theme": theme_row["name"],
                        "review_id": chosen["review_id"],
                        "quote": snippet,
                        "store": chosen["store"],
                        "rating": chosen["rating"],
                    }
                )
        else:
            for theme_row in featured:
                quote = select_quote_for_theme(
                    client,
                    theme_row["name"],
                    classifications,
                    reviews_by_id,
                )
                if quote:
                    quotes.append(quote)
        if len(quotes) != 3:
            raise RuntimeError(f"Expected 3 quotes, got {len(quotes)}")
        steps.append(
            {
                "step": "quote_selection",
                "status": "success",
                "output_summary": "Selected 3 verbatim quotes for featured themes",
            }
        )
    except Exception as err:
        logger.error("Quote selection failed: %s", err)
        steps.append(
            {"step": "quote_selection", "status": "failure", "error_message": str(err)}
        )
        write_run_log(run_id, started_at, steps, "failure")
        return

    try:
        if offline:
            action_ideas = _offline_action_ideas(featured, quotes)
        else:
            action_ideas = generate_action_ideas(client, featured, quotes)
        steps.append(
            {
                "step": "action_ideas",
                "status": "success",
                "output_summary": "Generated 3 action ideas",
            }
        )
    except Exception as err:
        logger.error("Action generation failed: %s", err)
        steps.append(
            {"step": "action_ideas", "status": "failure", "error_message": str(err)}
        )
        write_run_log(run_id, started_at, steps, "failure")
        return

    week_id = datetime.now(timezone.utc).strftime("%G-W%V")
    output = {
        "week": week_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviews_input_total": original_count,
        "reviews_processed": len(scrubbed_reviews),
        "classifications": classifications,
        "themes": theme_rows,
        "quotes": quotes,
        "action_ideas": action_ideas,
        "groq_usage": {
            "requests": client.total_requests if client else 0,
            "estimated_tokens": client.total_tokens if client else 0,
            "pre_routed_count": len(pre_routed),
            "groq_classified_count": len(groq_classified),
            "offline_mode": offline,
        },
    }

    os.makedirs("data", exist_ok=True)
    output_path = "data/processed_signal.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info(
        "Phase 2 complete. Saved %s (%d classifications, %d Groq requests, %d tokens)",
        output_path,
        len(classifications),
        client.total_requests if client else 0,
        client.total_tokens if client else 0,
    )
    steps.append(
        {
            "step": "save_output",
            "status": "success",
            "output_summary": f"Wrote {output_path}",
        }
    )
    write_run_log(run_id, started_at, steps, "success")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2: Theme clustering and signal extraction")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip Groq API calls and use keyword fallback (for testing without GROQ_API_KEY)",
    )
    args = parser.parse_args()
    main(offline=args.offline)
