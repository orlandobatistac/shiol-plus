"""
SHIOL+ Public API Endpoints
===========================

API endpoints specifically for the public frontend (index.html).
These endpoints provide public access to predictions and historical data.
"""

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
import os
from src.auth_middleware import apply_freemium_restrictions

from src.simple_utils import convert_numpy_types
from src.database import get_grouped_predictions_with_results_comparison

# Create router for public frontend endpoints
public_frontend_router = APIRouter(tags=["public_frontend"])

# Global components (will be injected from main API)
predictor = None
intelligent_generator = None
deterministic_generator = None

def set_public_components(pred, intel_gen, det_gen):
    """Set the global components for public endpoints."""
    global predictor, intelligent_generator, deterministic_generator
    predictor = pred
    intelligent_generator = intel_gen
    deterministic_generator = det_gen

# Build path to frontend templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
templates = Jinja2Templates(directory=FRONTEND_DIR)

@public_frontend_router.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Serve the main public index page"""
    return templates.TemplateResponse(request, "index.html")

@public_frontend_router.get("/public", response_class=HTMLResponse)
async def serve_public(request: Request):
    """Serve the public static page"""
    return templates.TemplateResponse(request, "static_public.html")

@public_frontend_router.get("/api/v1/public/predictions/by-draw/{draw_date}")
async def get_public_predictions_by_draw(
    request: Request,
    draw_date: str,
    min_matches: int = Query(0, description="Minimum number of matches to include"),
    limit: int = Query(200, description="Maximum number of predictions to return")
):
    """Get predictions for a specific draw date (public endpoint)"""
    try:
        logger.info(f"Public API request for predictions by draw date: {draw_date} (min_matches: {min_matches}, limit: {limit})")

        # Connect to database and get predictions
        from src.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # Query predictions for the specific draw date
        cursor.execute("""
            SELECT id, created_at, draw_date, n1, n2, n3, n4, n5, powerball,
                   strategy_used, confidence_score, created_at, was_played, 0, 0
            FROM generated_tickets
            WHERE draw_date = ?
            ORDER BY confidence_score DESC, created_at DESC
            LIMIT ?
        """, (draw_date, limit))

        predictions = cursor.fetchall()
        conn.close()

        # Format predictions for frontend
        predictions_list = []
        for pred in predictions:
            try:
                predictions_list.append({
                    "id": int(pred[0]) if pred[0] is not None else 0,
                    "prediction_date": str(pred[1]) if pred[1] else "",
                    "draw_date": str(pred[2]) if pred[2] else "",
                    "n1": int(pred[3]) if pred[3] is not None else 0,
                    "n2": int(pred[4]) if pred[4] is not None else 0,
                    "n3": int(pred[5]) if pred[5] is not None else 0,
                    "n4": int(pred[6]) if pred[6] is not None else 0,
                    "n5": int(pred[7]) if pred[7] is not None else 0,
                    "pb": int(pred[8]) if pred[8] is not None else 0,
                    "generator_type": str(pred[9]) if pred[9] else "mock",
                    "confidence_score": float(pred[10]) if pred[10] is not None else 0.0,
                    "created_at": str(pred[11]) if pred[11] else "",
                    "evaluated": bool(pred[12]) if pred[12] is not None else False,
                    "matches_main": int(pred[13]) if pred[13] is not None else 0,
                    "matches_powerball": bool(pred[14]) if pred[14] is not None else False
                })
            except (ValueError, TypeError) as format_error:
                logger.warning(f"Error formatting prediction data: {format_error}, skipping prediction")
                continue

        # Get actual draw numbers for comparison
        cursor = get_db_connection().cursor()
        cursor.execute("SELECT n1, n2, n3, n4, n5, pb FROM powerball_draws WHERE draw_date = ?", (draw_date,))
        draw_result = cursor.fetchone()
        cursor.connection.close()

        draw_numbers = None
        if draw_result:
            draw_numbers = {
                "n1": draw_result[0], "n2": draw_result[1], "n3": draw_result[2],
                "n4": draw_result[3], "n5": draw_result[4], "pb": draw_result[5]
            }

        logger.info(f"Found {len(predictions_list)} predictions for draw {draw_date}")

        # Apply freemium restrictions based on user authentication status with day-based quota
        freemium_result = apply_freemium_restrictions(predictions_list, request, draw_date)

        return {
            "success": True,
            "draw_date": draw_date,
            "predictions": freemium_result["predictions"],
            "accessible_count": freemium_result["accessible_count"],
            "locked_count": freemium_result["locked_count"],
            "total_count": freemium_result["total_count"],
            "access_info": freemium_result["access_info"],
            "user": freemium_result["user"],
            "draw_numbers": draw_numbers
        }

    except Exception as e:
        logger.error(f"Error fetching predictions by draw date {draw_date}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch predictions: {str(e)}")

@public_frontend_router.get("/api/v1/public/predictions/smart")
async def get_public_smart_predictions(limit: int = 100):
    """DISABLED: Public smart prediction generation is no longer supported.
    Use database queries for existing pipeline predictions only."""
    logger.warning("Attempt to use disabled public smart prediction generation")
    raise HTTPException(
        status_code=410,
        detail={
            "error": "Public prediction generation disabled",
            "message": "This endpoint no longer generates new predictions.",
            "alternative": "GET /api/v1/predict/smart (for existing predictions)",
            "reason": "System now only supports pipeline-generated predictions from database"
        }
    )

@public_frontend_router.get("/api/v1/public/recent-draws")
async def get_public_recent_draws(limit: int = Query(default=50, le=100)):
    """
    Get recent powerball draws for public access - OPTIMIZED v6.0

    IMPORTANT: Now recalculates total_prize in real-time using the same logic
    as get_draw_analytics() to ensure consistency between grid and modal.

    Returns draws with evaluation data:
    - All draws (with or without predictions)
    - Real-time calculated total_prize (same as Smart Insights modal)
    - Always verifies has_predictions against generated_tickets (source of truth)
    """
    try:
        from src.database import get_db_connection
        from src.prize_calculator import calculate_prize_amount
        import time

        start_time = time.time()
        conn = get_db_connection()

        if not conn:
            logger.error("Database connection failed")
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

        cursor = conn.cursor()

        # Step 1: Get all recent draws with their winning numbers
        try:
            cursor.execute("""
                SELECT
                    p.rowid,
                    p.draw_date,
                    p.n1, p.n2, p.n3, p.n4, p.n5, p.pb
                FROM powerball_draws p
                ORDER BY p.draw_date DESC
                LIMIT ?
            """, (limit,))
            draws = cursor.fetchall()
        except Exception as query_error:
            logger.error(f"Database query error: {query_error}")
            conn.close()
            raise HTTPException(status_code=500, detail="Database query failed")

        if not draws:
            conn.close()
            logger.warning("No draws found in database")
            return {"draws": [], "count": 0, "status": "no_data"}

        # Step 2: For each draw, calculate total_prize in real-time (same as modal)
        draws_list = []
        for draw in draws:
            try:
                draw_id = int(draw[0]) if draw[0] is not None else 0
                draw_date = str(draw[1]) if draw[1] else ""
                winning_numbers = [
                    int(draw[2]) if draw[2] is not None else 0,
                    int(draw[3]) if draw[3] is not None else 0,
                    int(draw[4]) if draw[4] is not None else 0,
                    int(draw[5]) if draw[5] is not None else 0,
                    int(draw[6]) if draw[6] is not None else 0,
                ]
                winning_pb = int(draw[7]) if draw[7] is not None else 0

                # Get all predictions for this draw
                cursor.execute("""
                    SELECT n1, n2, n3, n4, n5, powerball
                    FROM generated_tickets
                    WHERE draw_date = ?
                """, (draw_date,))
                predictions = cursor.fetchall()

                total_tickets = len(predictions)
                has_predictions = total_tickets > 0
                total_prize = 0.0

                # Calculate prize for each prediction (same logic as get_draw_analytics)
                if has_predictions and winning_numbers[0] > 0:  # Only if we have valid winning numbers
                    for pred in predictions:
                        pred_numbers = [pred[0], pred[1], pred[2], pred[3], pred[4]]
                        pred_pb = pred[5]

                        # Count main number matches
                        matches_main = sum(1 for n in pred_numbers if n in winning_numbers)
                        pb_match = (pred_pb == winning_pb)

                        # Calculate prize using same function as modal
                        prize_amount, _ = calculate_prize_amount(matches_main, pb_match)
                        total_prize += float(prize_amount or 0.0)

                draws_list.append({
                    "id": draw_id,
                    "draw_date": draw_date,
                    "n1": winning_numbers[0],
                    "n2": winning_numbers[1],
                    "n3": winning_numbers[2],
                    "n4": winning_numbers[3],
                    "n5": winning_numbers[4],
                    "pb": winning_pb,
                    "has_predictions": has_predictions,
                    "total_prize": total_prize,
                    "total_tickets": total_tickets,
                    "jackpot": "Not available"  # Legacy field for compatibility
                })
            except (ValueError, TypeError) as format_error:
                logger.warning(f"Error formatting draw data: {format_error}, skipping draw")
                continue

        conn.close()

        elapsed = time.time() - start_time
        logger.info(f"Recent draws query completed in {elapsed:.3f}s, found {len(draws_list)} draws")

        return {
            "draws": draws_list,
            "count": len(draws_list),
            "status": "success",
            "query_time": f"{elapsed:.3f}s"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in recent draws: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@public_frontend_router.get("/api/v1/public/history/grouped")
async def get_public_grouped_history():
    """Get grouped prediction history for public access"""
    try:
        grouped_data = get_grouped_predictions_with_results_comparison()
        return {"grouped_dates": convert_numpy_types(grouped_data)}

    except Exception as e:
        logger.error(f"Error getting public grouped history: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting history: {str(e)}")

@public_frontend_router.get("/api/v1/public/predictions/latest")
async def get_public_latest_predictions(request: Request, limit: int = Query(default=1000, le=1000)):
    """Get AI predictions for the next drawing date"""
    try:
        from src.database import get_db_connection
        from src.date_utils import DateManager
        import time

        start_time = time.time()

        # Calculate the next drawing date
        next_draw_date = DateManager.calculate_next_drawing_date()
        logger.info(f"Fetching predictions for next draw: {next_draw_date}")

        conn = get_db_connection()

        if not conn:
            logger.error("Database connection failed")
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

        cursor = conn.cursor()

        # Query predictions for the NEXT DRAW DATE specifically
        # Returns ALL predictions for that date (not limited to 200)
        try:
            cursor.execute("""
                SELECT
                    id,
                    created_at as timestamp,
                    draw_date as target_draw_date,
                    n1, n2, n3, n4, n5, powerball,
                    strategy_used as model_version,
                    confidence_score as score_total,
                    created_at
                FROM generated_tickets
                WHERE draw_date = ?
                ORDER BY confidence_score DESC, created_at DESC
                LIMIT ?
            """, (next_draw_date, limit))

            predictions = cursor.fetchall()
        except Exception as query_error:
            logger.error(f"Database query error: {query_error}")
            conn.close()
            raise HTTPException(status_code=500, detail="Database query failed")

        conn.close()

        elapsed = time.time() - start_time
        logger.info(f"Predictions query for {next_draw_date} completed in {elapsed:.3f}s, found {len(predictions) if predictions else 0} predictions")

        if not predictions:
            logger.warning(f"No predictions found for next draw {next_draw_date}")
            return {"predictions": [], "count": 0, "status": "no_data", "draw_date": next_draw_date}

        # Format predictions for frontend
        predictions_list = []
        for pred in predictions:
            try:
                predictions_list.append({
                    "id": int(pred[0]) if pred[0] is not None else 0,
                    "prediction_date": str(pred[1]) if pred[1] else "",
                    "draw_date": str(pred[2]) if pred[2] else "",
                    "n1": int(pred[3]) if pred[3] is not None else 0,
                    "n2": int(pred[4]) if pred[4] is not None else 0,
                    "n3": int(pred[5]) if pred[5] is not None else 0,
                    "n4": int(pred[6]) if pred[6] is not None else 0,
                    "n5": int(pred[7]) if pred[7] is not None else 0,
                    "pb": int(pred[8]) if pred[8] is not None else 0,
                    "generator_type": str(pred[9]) if pred[9] else "intelligent_ai",
                    "confidence_score": float(pred[10]) if pred[10] is not None else 0.0,
                    "created_at": str(pred[11]) if pred[11] else ""
                })
            except (ValueError, TypeError) as format_error:
                logger.warning(f"Error formatting prediction data: {format_error}, skipping prediction")
                continue

        # Apply freemium restrictions based on user authentication status
        freemium_result = apply_freemium_restrictions(predictions_list, request)

        return {
            "predictions": freemium_result["predictions"],
            "accessible_count": freemium_result["accessible_count"],
            "locked_count": freemium_result["locked_count"],
            "total_count": freemium_result["total_count"],
            "access_info": freemium_result["access_info"],
            "user": freemium_result["user"],
            "status": "success",
            "query_time": f"{elapsed:.3f}s"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_public_latest_predictions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@public_frontend_router.get("/api/v1/public/draws/recent")
async def get_public_draws_recent_alias(limit: int = Query(default=12, le=100)):
    """Alias endpoint for draws/recent to match frontend expectations"""
    return await get_public_recent_draws(limit=limit)

@public_frontend_router.get("/api/v1/public/next-drawing")
async def get_public_next_drawing():
    """Get next drawing date and time for public access"""
    try:
        from src.date_utils import DateManager
        from datetime import datetime

        # Get next drawing date
        current_et = DateManager.get_current_et_time()
        next_draw_str = DateManager.calculate_next_drawing_date(reference_date=current_et)
        next_draw = datetime.strptime(next_draw_str, "%Y-%m-%d")

        return {
            "next_draw_date": next_draw.strftime("%Y-%m-%d"),
            "next_draw_datetime": next_draw.isoformat(),
            "day_of_week": next_draw.strftime("%A"),
            "formatted_date": next_draw.strftime("%B %d, %Y"),
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Error getting next drawing date: {e}")
        # Fallback response
        return {
            "next_draw_date": "2025-09-03",
            "next_draw_datetime": "2025-09-03T22:00:00-04:00",
            "day_of_week": "Tuesday",
            "formatted_date": "September 03, 2025",
            "status": "fallback"
        }

@public_frontend_router.get("/api/v1/public/jackpot")
async def get_public_jackpot():
    """Get current Powerball jackpot with cash value from MUSL API"""
    try:
        from src.loader import fetch_musl_jackpot

        jackpot_data = fetch_musl_jackpot()

        if not jackpot_data:
            logger.warning("Could not fetch jackpot from MUSL API, returning fallback data")
            return {
                "nextAnnuity": 0,
                "nextCash": 0,
                "nextPrizeCombined": "Jackpot information unavailable",
                "nextDrawDate": "",
                "status": "fallback"
            }

        return {
            "annuity": jackpot_data.get("annuity", 0),
            "cash": jackpot_data.get("cash", 0),
            "nextAnnuity": jackpot_data.get("nextAnnuity", 0),
            "nextCash": jackpot_data.get("nextCash", 0),
            "prizeText": jackpot_data.get("prizeText", ""),
            "cashPrizeText": jackpot_data.get("cashPrizeText", ""),
            "prizeCombined": jackpot_data.get("prizeCombined", ""),
            "nextPrizeText": jackpot_data.get("nextPrizeText", ""),
            "nextCashPrizeText": jackpot_data.get("nextCashPrizeText", ""),
            "nextPrizeCombined": jackpot_data.get("nextPrizeCombined", ""),
            "drawDate": jackpot_data.get("drawDate", ""),
            "nextDrawDate": jackpot_data.get("nextDrawDate", ""),
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Error fetching jackpot data: {e}")
        return {
            "nextAnnuity": 0,
            "nextCash": 0,
            "nextPrizeCombined": "Error fetching jackpot",
            "nextDrawDate": "",
            "status": "error"
        }

@public_frontend_router.get("/api/v1/public/winners-stats")
async def get_winners_stats():
    """Calculate total prizes won by Shiol+ users by recomputing from official results.

    We recompute prizes from generated_tickets using powerball_draws as the source of truth,
    instead of relying on the stored prize_won column (which may be unset for some draws).
    """
    try:
        from src.database import get_db_connection, calculate_prize_amount

        conn = get_db_connection()
        cursor = conn.cursor()

        # Prefetch all official draw results into a map: draw_date -> (numbers, pb)
        cursor.execute(
            """
            SELECT draw_date, n1, n2, n3, n4, n5, pb
            FROM powerball_draws
            """
        )
        draw_rows = cursor.fetchall()
        draws_map = {}
        for dr in draw_rows:
            date = str(dr[0])
            draws_map[date] = {
                'nums': [int(dr[1] or 0), int(dr[2] or 0), int(dr[3] or 0), int(dr[4] or 0), int(dr[5] or 0)],
                'pb': int(dr[6] or 0)
            }

        # Fetch all predictions (only the fields we need)
        cursor.execute(
            """
            SELECT draw_date, n1, n2, n3, n4, n5, powerball
            FROM generated_tickets
            """
        )
        preds = cursor.fetchall()

        total_won = 0.0
        winning_count = 0

        for p in preds:
            draw_date = str(p[0]) if p[0] else None
            if not draw_date or draw_date not in draws_map:
                continue
            nums = [int(p[1] or 0), int(p[2] or 0), int(p[3] or 0), int(p[4] or 0), int(p[5] or 0)]
            pb = int(p[6] or 0)

            winning_nums = draws_map[draw_date]['nums']
            winning_pb = draws_map[draw_date]['pb']

            main_matches = len(set(nums) & set(winning_nums))
            pb_match = (pb == winning_pb)

            prize_amount, _ = calculate_prize_amount(main_matches, pb_match)
            if prize_amount and prize_amount > 0:
                total_won += float(prize_amount)
                winning_count += 1

        conn.close()

        formatted_total = f"${total_won:,.0f}"
        logger.info(
            f"Calculated total prizes won (recomputed): {formatted_total} from {winning_count} winning predictions"
        )

        return {
            "total_won": formatted_total,
            "formatted_amount": f"{formatted_total} won",
            "period": "all time",
            "description": "won by users who used Shiol+ AI insights",
            "winning_predictions_count": winning_count,
            "status": "success",
        }

    except Exception as e:
        logger.error(f"Error calculating winners stats: {e}")
        return {
            "total_won": "$0",
            "formatted_amount": "$0 won",
            "period": "all time",
            "description": "won by users who used Shiol+ AI insights",
            "winning_predictions_count": 0,
            "status": "error",
            "error": str(e)
        }

@public_frontend_router.get("/api/v1/public/best-match")
async def get_public_best_match():
    """Return the all-time best draw match for public display."""
    try:
        from src.database import get_best_match_all_time

        best_match = get_best_match_all_time()
        if not best_match:
            return {
                "best_match": None,
                "period": "all time",
                "status": "no_data",
            }

        return {
            "best_match": convert_numpy_types(best_match),
            "period": "all time",
            "status": "success",
        }

    except Exception as e:
        logger.error(f"Error fetching public best match: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching best match: {str(e)}")

@public_frontend_router.get("/api/v1/public/stats")
async def get_public_stats():
    """Get SHIOL+ system stats: total matches found and estimated prizes"""
    try:
        from src.database import get_db_connection
        from datetime import datetime, timedelta

        conn = get_db_connection()
        cursor = conn.cursor()

        # Compute from current schema
        # 1) Total winning sets and total prize value from generated_tickets.prize_won
        cursor.execute(
            """
            SELECT COUNT(CASE WHEN prize_won > 0 THEN 1 END) as winning_predictions,
                   COALESCE(SUM(CASE WHEN prize_won > 0 THEN prize_won ELSE 0 END), 0) as total_won
            FROM generated_tickets
            """
        )
        row = cursor.fetchone() or (0, 0.0)
        total_winning_sets = int(row[0] or 0)
        total_prize_value = float(row[1] or 0.0)

        # 2) Weekly winning sets (last 7 days) by created_at
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM generated_tickets
            WHERE prize_won > 0 AND created_at >= ?
            """,
            (week_ago,),
        )
        weekly_matches = cursor.fetchone()[0] or 0

        conn.close()

        # Format prize value for display
        if total_prize_value >= 1_000_000:
            prize_text = f"${total_prize_value/1_000_000:.1f}M"
        elif total_prize_value >= 1_000:
            prize_text = f"${total_prize_value/1_000:.1f}K"
        else:
            prize_text = f"${total_prize_value:,.0f}"

        return {
            "totalWinningSets": total_winning_sets,
            "totalPrizeValue": total_prize_value,
            "prizeText": prize_text,
            "weeklyMatches": weekly_matches,
            "status": "success",
        }

    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return {
            "totalWinningSets": 0,
            "totalPrizeValue": 0,
            "prizeText": "$0",
            "weeklyMatches": 0,
            "status": "error"
        }

@public_frontend_router.post("/api/v1/public/register-visit")
async def register_unique_visit(request: Request):
    """Register unique visit per device"""
    try:
        from src.database import get_db_connection

        # Get device fingerprint from request body
        body = await request.json()
        device_fingerprint = body.get("fingerprint", "")

        if not device_fingerprint:
            return {"status": "error", "message": "No fingerprint provided"}

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if device already visited
        cursor.execute("""
            SELECT id, visit_count FROM unique_visits
            WHERE device_fingerprint = ?
        """, (device_fingerprint,))

        existing_visit = cursor.fetchone()

        if existing_visit:
            # Update last visit time and increment count
            cursor.execute("""
                UPDATE unique_visits
                SET last_visit = CURRENT_TIMESTAMP,
                    visit_count = visit_count + 1
                WHERE device_fingerprint = ?
            """, (device_fingerprint,))
        else:
            # Insert new unique visit
            cursor.execute("""
                INSERT INTO unique_visits (device_fingerprint)
                VALUES (?)
            """, (device_fingerprint,))

        conn.commit()
        conn.close()

        return {"status": "success", "new_visit": existing_visit is None}

    except Exception as e:
        logger.error(f"Error registering visit: {e}")
        return {"status": "error", "message": str(e)}

@public_frontend_router.post("/api/v1/public/register-pwa-install")
async def register_pwa_install(request: Request):
    """Register PWA installation"""
    try:
        from src.database import get_db_connection

        # Get device fingerprint from request body
        body = await request.json()
        device_fingerprint = body.get("fingerprint", "")

        if not device_fingerprint:
            return {"status": "error", "message": "No fingerprint provided"}

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if already installed
        cursor.execute("""
            SELECT id FROM pwa_installs
            WHERE device_fingerprint = ?
        """, (device_fingerprint,))

        if cursor.fetchone():
            conn.close()
            return {"status": "already_installed"}

        # Insert new installation
        cursor.execute("""
            INSERT INTO pwa_installs (device_fingerprint)
            VALUES (?)
        """, (device_fingerprint,))

        conn.commit()
        conn.close()

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error registering PWA install: {e}")
        return {"status": "error", "message": str(e)}

@public_frontend_router.get("/api/v1/public/counters")
async def get_counters():
    """Get visit and PWA install counters"""
    try:
        from src.database import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Count unique visits
        cursor.execute("SELECT COUNT(*) FROM unique_visits")
        unique_visits = cursor.fetchone()[0]

        # Count PWA installations
        cursor.execute("SELECT COUNT(*) FROM pwa_installs")
        pwa_installs = cursor.fetchone()[0]

        conn.close()

        return {
            "visits": unique_visits,
            "installs": pwa_installs
        }

    except Exception as e:
        logger.error(f"Error getting counters: {e}")
        return {
            "visits": 0,
            "installs": 0
        }



@public_frontend_router.get("/api/v1/public/analytics/draw/{draw_date}")
async def get_public_draw_analytics(draw_date: str, limit: int = 50):
    """Return draw-level analytics powered by generated_tickets."""
    try:
        from src.database import get_draw_analytics
        analytics = get_draw_analytics(draw_date, limit=limit)
        return analytics
    except Exception as e:
        logger.error(f"Error fetching draw analytics for {draw_date}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@public_frontend_router.get("/api/v1/public/analytics/summary")
async def get_public_analytics_summary(days_back: int = 30):
    """Return site-wide analytics summary for dashboard."""
    try:
        from src.database import get_analytics_summary
        summary = get_analytics_summary(days_back=days_back)
        return summary
    except Exception as e:
        logger.error(f"Error fetching analytics summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
