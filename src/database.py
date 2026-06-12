import sqlite3
import pandas as pd
from loguru import logger
import configparser
import os
import json
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import hashlib


def calculate_prize_amount(main_matches: int, powerball_match: bool) -> Tuple[float, str]:
    """
    Calculate prize amount based on main number matches and powerball match.

    Args:
        main_matches: Number of main numbers matched (0-5)
        powerball_match: Whether powerball was matched

    Returns:
        Tuple of (prize_amount, prize_description)
    """
    if main_matches == 5 and powerball_match:
        return 100_000_000.0, "Jackpot"
    elif main_matches == 5:
        return 1_000_000.0, "Match 5"
    elif main_matches == 4 and powerball_match:
        return 50_000.0, "Match 4 + PB"
    elif main_matches == 4:
        return 100.0, "Match 4"
    elif main_matches == 3 and powerball_match:
        return 100.0, "Match 3 + PB"
    elif main_matches == 3:
        return 7.0, "Match 3"
    elif main_matches == 2 and powerball_match:
        return 7.0, "Match 2 + PB"
    elif main_matches == 1 and powerball_match:
        return 4.0, "Match 1 + PB"
    elif powerball_match:
        return 4.0, "Match PB"
    else:
        return 0.0, "No matches"


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle numpy types."""

    def default(self, o):
        """Override default method with correct parameter name."""
        if isinstance(o, np.integer):
            return int(o)
        elif isinstance(o, np.floating):
            return float(o)
        elif isinstance(o, np.ndarray):
            return o.tolist()
        return super(NumpyEncoder, self).default(o)


def get_db_path() -> str:
    """Reads the database file path from the configuration file."""
    config = configparser.ConfigParser()
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, '..', 'config', 'config.ini')

    try:
        config.read(config_path)
        if config.has_section('paths') and config.has_option('paths', 'database_file'):
            db_file = config["paths"]["database_file"]
        else:
            db_file = "data/shiolplus.db"
            logger.warning(f"Config section 'paths' or 'database_file' option not found, using default: {db_file}")

        db_path = os.path.join(current_dir, '..', db_file)
    except (configparser.Error, OSError) as e:
        logger.error(f"Error reading config file: {e}. Using default database path.")
        db_path = os.path.join(current_dir, '..', 'data', 'shiolplus.db')

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path


def calculate_next_drawing_date() -> str:
    """
    Calculate the next Powerball drawing date using centralized DateManager.

    Returns:
        str: Next drawing date in YYYY-MM-DD format

    Raises:
        ImportError: If DateManager module cannot be imported
    """
    try:
        from src.date_utils import DateManager
        current_et = DateManager.get_current_et_time()
        next_date = DateManager.calculate_next_drawing_date(reference_date=current_et)

        logger.debug(f"Next drawing date calculated: {next_date} (from ET time: {current_et.strftime('%Y-%m-%d %H:%M')})")
        return next_date
    except ImportError as e:
        logger.error(f"Failed to import DateManager: {e}")
        raise
    except Exception as e:
        logger.error(f"Error calculating next drawing date: {e}")
        raise


def get_db_connection() -> sqlite3.Connection:
    """
    Establishes a connection to the SQLite database.

    Returns:
        sqlite3.Connection: A connection object to the database.

    Raises:
        sqlite3.Error: If database connection fails
    """
    db_path = get_db_path()
    try:
        # Use a reasonable timeout to wait on busy DB instead of failing fast
        conn = sqlite3.connect(db_path, timeout=30)
        # Configure connection pragmas to reduce write-lock contention
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            # PRAGMA calls are best-effort; ignore failures
            pass
        logger.info(f"Successfully connected to database at {db_path}")
        return conn
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database at {db_path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error connecting to database: {e}")
        raise sqlite3.Error(f"Database connection failed: {e}") from e


def save_pipeline_execution(execution_data: Dict[str, Any]) -> Optional[str]:
    """Save pipeline execution to SQLite database with duplicate prevention."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execution_id = execution_data.get('execution_id')

            # Check if execution already exists
            cursor.execute("SELECT id FROM pipeline_executions WHERE execution_id = ?", (execution_id,))
            existing = cursor.fetchone()

            if existing:
                logger.warning(f"Pipeline execution {execution_id} already exists, skipping duplicate creation")
                return execution_id

            cursor.execute(
                """
                INSERT INTO pipeline_executions (
                    execution_id, status, start_time, trigger_type, trigger_source,
                    current_step, steps_completed, total_steps, num_predictions,
                    execution_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                execution_id,
                execution_data.get('status', 'starting'),
                execution_data.get('start_time'),
                execution_data.get('trigger_type', 'unknown'),
                execution_data.get('trigger_source', 'unknown'),
                execution_data.get('current_step'),
                execution_data.get('steps_completed', 0),
                execution_data.get('total_steps', 5),
                execution_data.get('num_predictions', 100),
                json.dumps(execution_data.get('execution_details', {}), cls=NumpyEncoder)
            ))

            conn.commit()
            logger.info(f"Pipeline execution {execution_id} saved to SQLite")
            return execution_id

    except sqlite3.Error as e:
        logger.error(f"SQLite error saving pipeline execution: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON encoding error in pipeline execution: {e}")
        return None


def update_pipeline_execution(execution_id: str, update_data: Dict[str, Any]) -> bool:
    """Update pipeline execution in SQLite database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            update_fields = []
            params = []

            field_mappings = {
                'status': 'status = ?',
                'end_time': 'end_time = ?',
                'current_step': 'current_step = ?',
                'steps_completed': 'steps_completed = ?',
                'error_message': 'error_message = ?',
                'subprocess_success': 'subprocess_success = ?',
                'stdout_output': 'stdout_output = ?',
                'stderr_output': 'stderr_output = ?'
            }

            for field, sql_field in field_mappings.items():
                if field in update_data:
                    update_fields.append(sql_field)
                    params.append(update_data[field])

            if not update_fields:
                logger.warning(f"No valid fields to update for execution {execution_id}")
                return False

            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(execution_id)

            query = f"""
                UPDATE pipeline_executions
                SET {', '.join(update_fields)}
                WHERE execution_id = ?
            """

            cursor.execute(query, params)

            if cursor.rowcount > 0:
                conn.commit()
                logger.info(f"Pipeline execution {execution_id} updated in SQLite")
                return True
            else:
                logger.warning(f"Pipeline execution {execution_id} not found for update")
                return False

    except sqlite3.Error as e:
        logger.error(f"SQLite error updating pipeline execution: {e}")
        return False


def get_pipeline_execution_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Get pipeline execution history from SQLite database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    execution_id, status, start_time, end_time,
                    trigger_type, trigger_source, current_step,
                    steps_completed, total_steps, num_predictions,
                    error_message, subprocess_success, created_at
                FROM pipeline_executions
                ORDER BY start_time DESC
                LIMIT ?
            """, (limit,))

            executions = []
            for row in cursor.fetchall():
                execution = {
                    'execution_id': row[0],
                    'status': row[1],
                    'start_time': row[2],
                    'end_time': row[3],
                    'trigger_type': row[4],
                    'trigger_source': row[5],
                    'current_step': row[6],
                    'steps_completed': row[7],
                    'total_steps': row[8],
                    'num_predictions': row[9],
                    'error': row[10],
                    'subprocess_success': row[11] == 1 if row[11] is not None else False,
                    'created_at': row[12]
                }
                executions.append(execution)

            logger.info(f"Retrieved {len(executions)} pipeline executions from SQLite")
            return executions

    except sqlite3.Error as e:
        logger.error(f"SQLite error getting pipeline execution history: {e}")
        return []


def get_pipeline_execution_by_id(execution_id: str) -> Optional[Dict[str, Any]]:
    """Get specific pipeline execution by ID from SQLite."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    execution_id, status, start_time, end_time,
                    trigger_type, trigger_source, current_step,
                    steps_completed, total_steps, num_predictions,
                    error_message, execution_details, subprocess_success,
                    stdout_output, stderr_output, created_at, updated_at
                FROM pipeline_executions
                WHERE execution_id = ?
            """, (execution_id,))

            row = cursor.fetchone()
            if row:
                execution = {
                    'execution_id': row[0],
                    'status': row[1],
                    'start_time': row[2],
                    'end_time': row[3],
                    'trigger_type': row[4],
                    'trigger_source': row[5],
                    'current_step': row[6],
                    'steps_completed': row[7],
                    'total_steps': row[8],
                    'num_predictions': row[9],
                    'error': row[10],
                    'execution_details': json.loads(row[11]) if row[11] else {},
                    'subprocess_success': row[12] == 1 if row[12] is not None else False,
                    'stdout_output': row[13],
                    'stderr_output': row[14],
                    'created_at': row[15],
                    'updated_at': row[16]
                }

                logger.info(f"Retrieved pipeline execution {execution_id} from SQLite")
                return execution
            else:
                logger.warning(f"Pipeline execution {execution_id} not found in SQLite")
                return None

    except sqlite3.Error as e:
        logger.error(f"Error getting pipeline execution by ID from SQLite: {e}")
        return None


def initialize_database():
    """Initialize the database by creating all required tables if they don't exist.

    Also ensures analytics tables and triggers exist, and auto-creates an admin user
    on first run if none exists. Idempotent and safe to call multiple times.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Core and domain tables
            _create_core_tables(cursor)
            _create_prediction_tables(cursor)
            _create_feedback_tables(cursor)
            _create_indexes(cursor)

            conn.commit()

        # Create analytics tables and triggers using their own safe connections
        try:
            create_analytics_tables()
        except Exception as e:
            logger.warning(f"Failed to create analytics tables during initialization: {e}")

        try:
            create_pb_era_triggers()
        except Exception as e:
            logger.warning(f"Failed to create pb_era triggers during initialization: {e}")

        # Ensure at least one admin user exists
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE is_admin = 1 LIMIT 1")
                exists = cursor.fetchone()
                if not exists:
                    admin_email = os.getenv('ADMIN_EMAIL')
                    admin_username = os.getenv('ADMIN_USERNAME')
                    admin_password = os.getenv('ADMIN_PASSWORD')

                    if not (admin_email and admin_username and admin_password):
                        # Fallback to config.ini if no env vars
                        cfg = configparser.ConfigParser()
                        current_dir = os.path.dirname(os.path.abspath(__file__))
                        cfg_path = os.path.join(current_dir, '..', 'config', 'config.ini')
                        cfg.read(cfg_path)
                        admin_email = cfg.get('admin', 'email', fallback='admin@shiolplus.com')
                        admin_username = cfg.get('admin', 'username', fallback='admin')
                        admin_password = cfg.get('admin', 'password', fallback='Admin123!')

                    # Hash password (bcrypt preferred, sha256 fallback)
                    try:
                        import bcrypt  # type: ignore
                        password_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    except Exception:
                        password_hash = hashlib.sha256(admin_password.encode('utf-8')).hexdigest()

                    cursor.execute(
                        """
                        INSERT INTO users (email, username, password_hash, is_admin, is_active, created_at)
                        VALUES (?, ?, ?, 1, 1, CURRENT_TIMESTAMP)
                        """,
                        (admin_email, admin_username, password_hash)
                    )
                    conn.commit()
                    logger.info(f"Admin user created: {admin_email} / {admin_username}")
        except Exception as e:
            logger.warning(f"Admin auto-provisioning skipped due to error: {e}")

        logger.info("Database initialized successfully with all tables and indexes.")

    except sqlite3.Error as e:
        logger.error(f"Database error during initialization: {e}")
        raise

def _create_feedback_tables(cursor):
    """Create feedback/evaluation related tables used by the pipeline."""
    # Performance tracking table to record evaluation of predictions
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS performance_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL,
            draw_date DATE NOT NULL,
            actual_n1 INTEGER NOT NULL,
            actual_n2 INTEGER NOT NULL,
            actual_n3 INTEGER NOT NULL,
            actual_n4 INTEGER NOT NULL,
            actual_n5 INTEGER NOT NULL,
            actual_pb INTEGER NOT NULL,
            matches_main INTEGER DEFAULT 0,
            matches_pb INTEGER DEFAULT 0,
            prize_tier TEXT DEFAULT 'Non-winning',
            score_accuracy REAL DEFAULT 0.0,
            component_accuracy TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def create_analytics_tables():
    """Create advanced analytics tables for the enhanced pipeline."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Table 1: Co-occurrence matrix - tracks which number pairs appear together
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cooccurrences (
                number_a INTEGER NOT NULL,
                number_b INTEGER NOT NULL,
                count INTEGER DEFAULT 0,
                expected REAL DEFAULT 0.0,
                deviation_pct REAL DEFAULT 0.0,
                is_significant BOOLEAN DEFAULT FALSE,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (number_a, number_b),
                CHECK (number_a >= 1 AND number_a <= 69),
                CHECK (number_b >= 1 AND number_b <= 69),
                CHECK (number_a < number_b)
            )
        """)

        # Table 2: Pattern statistics - sum, range, gaps, distribution analysis
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pattern_stats (
                pattern_type TEXT NOT NULL,
                pattern_value TEXT NOT NULL,
                frequency INTEGER DEFAULT 0,
                percentage REAL DEFAULT 0.0,
                is_typical BOOLEAN DEFAULT TRUE,
                mean_value REAL,
                std_dev REAL,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (pattern_type, pattern_value)
            )
        """)

        # Table 3: Strategy performance tracking with adaptive weights
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategy_performance (
                strategy_name TEXT PRIMARY KEY,
                total_plays INTEGER DEFAULT 0,
                total_wins INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.0,
                total_prizes REAL DEFAULT 0.0,
                total_cost REAL DEFAULT 0.0,
                roi REAL DEFAULT 0.0,
                avg_prize REAL DEFAULT 0.0,
                current_weight REAL DEFAULT 0.1667,
                confidence REAL DEFAULT 0.5,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table 4: Generated tickets with strategy attribution
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS generated_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draw_date DATE NOT NULL,
                strategy_used TEXT NOT NULL,
                n1 INTEGER NOT NULL,
                n2 INTEGER NOT NULL,
                n3 INTEGER NOT NULL,
                n4 INTEGER NOT NULL,
                n5 INTEGER NOT NULL,
                powerball INTEGER NOT NULL,
                confidence_score REAL DEFAULT 0.5,
                was_played BOOLEAN DEFAULT FALSE,
                prize_won REAL DEFAULT 0.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                evaluated BOOLEAN DEFAULT FALSE,
                matches_wb INTEGER DEFAULT 0,
                matches_pb INTEGER DEFAULT 0,
                prize_description TEXT DEFAULT '',
                evaluation_date DATETIME,
                CHECK (n1 < n2 AND n2 < n3 AND n3 < n4 AND n4 < n5),
                CHECK (n1 >= 1 AND n5 <= 69),
                CHECK (powerball >= 1 AND powerball <= 26)
            )
        """)

        # Table 5: Pipeline execution logs - tracks all pipeline runs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_execution_logs (
                execution_id TEXT PRIMARY KEY,
                start_time DATETIME NOT NULL,
                end_time DATETIME,
                status TEXT NOT NULL DEFAULT 'running',
                current_step TEXT,
                steps_completed INTEGER DEFAULT 0,
                total_steps INTEGER DEFAULT 7,
                error TEXT,
                metadata TEXT,
                total_tickets_generated INTEGER DEFAULT 0,
                target_draw_date DATE,
                elapsed_seconds REAL,
                data_source TEXT,
                CHECK (status IN ('running', 'completed', 'failed', 'timeout'))
            )
        """)

        # Migration: Add data_source column if it doesn't exist
        try:
            cursor.execute("SELECT data_source FROM pipeline_execution_logs LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE pipeline_execution_logs ADD COLUMN data_source TEXT")
            logger.info("Added data_source column to pipeline_execution_logs")

        # Migration: Update total_steps default for existing rows
        cursor.execute("""
            UPDATE pipeline_execution_logs
            SET total_steps = 7
            WHERE total_steps = 5
        """)
        rows_updated = cursor.rowcount
        if rows_updated > 0:
            logger.info(f"Updated total_steps from 5 to 7 for {rows_updated} existing pipeline logs")

        # Table 6: Pending draws - tracks draws waiting for results (Pipeline v6.1 - 3 Layer Architecture)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draw_date TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_attempt_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                completed_by_layer INTEGER,
                error_message TEXT,
                CHECK (status IN ('pending', 'completed', 'failed_permanent'))
            )
        """)

        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cooccurrence_significant ON cooccurrences(is_significant)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_generated_tickets_date ON generated_tickets(draw_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_generated_tickets_strategy ON generated_tickets(strategy_used)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_logs_status ON pipeline_execution_logs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_logs_start_time ON pipeline_execution_logs(start_time DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_draws_status ON pending_draws(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_draws_draw_date ON pending_draws(draw_date)")

        conn.commit()
        conn.close()
        logger.info("Analytics tables created successfully")
    except sqlite3.Error as e:
        logger.error(f"SQLite error while creating analytics tables: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating analytics tables: {e}")
        raise


def create_pb_era_triggers():
    """
    Create database triggers to auto-classify pb_era and pb_is_current on INSERT/UPDATE.
    These triggers ensure new draws from MUSL API are automatically classified
    into the correct Powerball era based on pb value.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Drop existing triggers (idempotent)
        cursor.execute("DROP TRIGGER IF EXISTS set_pb_era_on_insert")
        cursor.execute("DROP TRIGGER IF EXISTS set_pb_era_on_update")

        # Create AFTER INSERT trigger
        cursor.execute("""
            CREATE TRIGGER set_pb_era_on_insert
            AFTER INSERT ON powerball_draws
            FOR EACH ROW
            WHEN NEW.pb_is_current = 0 AND NEW.pb_era = 'unknown'
            BEGIN
                UPDATE powerball_draws
                SET
                    pb_is_current = CASE WHEN NEW.pb BETWEEN 1 AND 26 THEN 1 ELSE 0 END,
                    pb_era = CASE
                        WHEN NEW.pb BETWEEN 1 AND 26 THEN '2015-now (1-26)'
                        WHEN NEW.pb BETWEEN 27 AND 35 THEN '2012-2015 (1-35)'
                        WHEN NEW.pb BETWEEN 36 AND 39 THEN '2009-2012 (1-39)'
                        WHEN NEW.pb BETWEEN 40 AND 42 THEN '1997-2009 (1-42)'
                        WHEN NEW.pb BETWEEN 43 AND 45 THEN '1992-1997 (1-45)'
                        ELSE 'other'
                    END
                WHERE rowid = NEW.rowid;
            END
        """)

        # Create AFTER UPDATE trigger
        cursor.execute("""
            CREATE TRIGGER set_pb_era_on_update
            AFTER UPDATE OF pb ON powerball_draws
            FOR EACH ROW
            BEGIN
                UPDATE powerball_draws
                SET
                    pb_is_current = CASE WHEN NEW.pb BETWEEN 1 AND 26 THEN 1 ELSE 0 END,
                    pb_era = CASE
                        WHEN NEW.pb BETWEEN 1 AND 26 THEN '2015-now (1-26)'
                        WHEN NEW.pb BETWEEN 27 AND 35 THEN '2012-2015 (1-35)'
                        WHEN NEW.pb BETWEEN 36 AND 39 THEN '2009-2012 (1-39)'
                        WHEN NEW.pb BETWEEN 40 AND 42 THEN '1997-2009 (1-42)'
                        WHEN NEW.pb BETWEEN 43 AND 45 THEN '1992-1997 (1-45)'
                        ELSE 'other'
                    END
                WHERE rowid = NEW.rowid;
            END
        """)

        conn.commit()
        conn.close()
        logger.info("✅ pb_era triggers created successfully")
    except sqlite3.Error as e:
        logger.error(f"Failed to create pb_era triggers: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating triggers: {e}")
        raise


def _create_core_tables(cursor):
    """Create core system tables."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS powerball_draws (
            draw_date DATE PRIMARY KEY,
            n1 INTEGER NOT NULL,
            n2 INTEGER NOT NULL,
            n3 INTEGER NOT NULL,
            n4 INTEGER NOT NULL,
            n5 INTEGER NOT NULL,
            pb INTEGER NOT NULL
        )
    """)

    # Migration for pb_is_current and pb_era columns
    try:
        cursor.execute("PRAGMA table_info(powerball_draws)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'pb_is_current' not in columns:
            logger.info("Adding pb_is_current column to powerball_draws table...")
            cursor.execute("ALTER TABLE powerball_draws ADD COLUMN pb_is_current INTEGER DEFAULT 0")
            logger.info("pb_is_current column added successfully")

        if 'pb_era' not in columns:
            logger.info("Adding pb_era column to powerball_draws table...")
            cursor.execute("ALTER TABLE powerball_draws ADD COLUMN pb_era TEXT DEFAULT 'unknown'")
            logger.info("pb_era column added successfully")
    except sqlite3.Error as e:
        logger.error(f"Error during powerball_draws migration: {e}")

    # Users table for authentication and premium access
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_premium BOOLEAN DEFAULT FALSE,
            premium_expires_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME,
            login_count INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE
        )
    """)

    # Migration for is_admin column
    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'is_admin' not in columns:
            logger.info("Adding is_admin column to users table...")
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
            logger.info("is_admin column added successfully")
    except sqlite3.Error as e:
        logger.error(f"Error during is_admin migration: {e}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            section TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (section, key)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'starting',
            start_time TEXT NOT NULL,
            end_time TEXT,
            trigger_type TEXT NOT NULL,
            trigger_source TEXT NOT NULL,
            current_step TEXT,
            steps_completed INTEGER DEFAULT 0,
            total_steps INTEGER DEFAULT 7,
            num_predictions INTEGER DEFAULT 100,
            error_message TEXT,
            execution_details TEXT,
            subprocess_success BOOLEAN DEFAULT FALSE,
            stdout_output TEXT,
            stderr_output TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tabla para visitas únicas por dispositivo
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unique_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_fingerprint TEXT UNIQUE NOT NULL,
            first_visit DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_visit DATETIME DEFAULT CURRENT_TIMESTAMP,
            visit_count INTEGER DEFAULT 1
        )
    """)

    # Tabla para instalaciones del PWA
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pwa_installs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_fingerprint TEXT UNIQUE NOT NULL,
            install_date DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Weekly verification limits table for guest and registered users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weekly_verification_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NULL,
            device_fingerprint TEXT NULL,
            week_start_date DATE NOT NULL,
            verification_count INTEGER DEFAULT 0,
            last_verification DATETIME,
            user_type TEXT NOT NULL DEFAULT 'guest',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, week_start_date),
            UNIQUE(device_fingerprint, week_start_date),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Stripe billing tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT UNIQUE NOT NULL,
            endpoint TEXT NOT NULL,
            request_payload TEXT NOT NULL,
            response_data TEXT,
            status_code INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            processed_at DATETIME
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stripe_event_id TEXT UNIQUE NOT NULL,
            event_type TEXT NOT NULL,
            processed BOOLEAN DEFAULT FALSE,
            processed_at DATETIME,
            payload TEXT NOT NULL,
            processing_error TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stripe_customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stripe_customer_id TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            user_id INTEGER NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stripe_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stripe_subscription_id TEXT UNIQUE NOT NULL,
            stripe_customer_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_period_start DATETIME,
            current_period_end DATETIME,
            canceled_at DATETIME,
            ended_at DATETIME,
            trial_start DATETIME,
            trial_end DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stripe_customer_id) REFERENCES stripe_customers(stripe_customer_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS premium_passes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pass_token TEXT UNIQUE NOT NULL,
            jti TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            stripe_subscription_id TEXT UNIQUE,
            stripe_customer_id TEXT,
            user_id INTEGER NULL,
            expires_at DATETIME NOT NULL,
            revoked_at DATETIME,
            revoked_reason TEXT,
            device_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (stripe_subscription_id) REFERENCES stripe_subscriptions(stripe_subscription_id),
            FOREIGN KEY (stripe_customer_id) REFERENCES stripe_customers(stripe_customer_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS premium_pass_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pass_id INTEGER NOT NULL,
            device_fingerprint TEXT NOT NULL,
            first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pass_id, device_fingerprint),
            FOREIGN KEY (pass_id) REFERENCES premium_passes(id)
        )
    """)

    # IP rate limiting table for abuse protection
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ip_rate_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            hour_window DATETIME NOT NULL,
            request_count INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ip_address, hour_window)
        )
    """)


def _create_prediction_tables(cursor):
    """Create prediction-related tables."""
    # Legacy table: predictions_log
    # The original DDL for the legacy `predictions_log` table is preserved below as a
    # historical reference only. The runtime code now uses `generated_tickets` and the
    # legacy DDL is intentionally commented out to avoid recreating or mutating the
    # archived table during normal initialization.
    #
    # CREATE TABLE IF NOT EXISTS predictions_log (
    #     id INTEGER PRIMARY KEY AUTOINCREMENT,
    #     timestamp TEXT NOT NULL,
    #     n1 INTEGER NOT NULL,
    #     n2 INTEGER NOT NULL,
    #     n3 INTEGER NOT NULL,
    #     n4 INTEGER NOT NULL,
    #     n5 INTEGER NOT NULL,
    #     powerball INTEGER NOT NULL,
    #     score_total REAL NOT NULL,
    #     model_version TEXT NOT NULL,
    #     dataset_hash TEXT NOT NULL,
    # the legacy table has been archived and dropped from the active database.
    #

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS adaptive_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weight_set_name TEXT NOT NULL,
            probability_weight REAL NOT NULL,
            diversity_weight REAL NOT NULL,
            historical_weight REAL NOT NULL,
            risk_adjusted_weight REAL NOT NULL,
            performance_score REAL NOT NULL,
            optimization_algorithm TEXT NOT NULL,
            dataset_hash TEXT NOT NULL,
            is_active BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL,
            pattern_description TEXT NOT NULL,
            pattern_data TEXT NOT NULL,
            success_rate REAL NOT NULL,
            frequency INTEGER NOT NULL,
            confidence_score REAL NOT NULL,
            date_range_start DATE NOT NULL,
            date_range_end DATE NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reliable_plays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            n1 INTEGER NOT NULL,
            n2 INTEGER NOT NULL,
            n3 INTEGER NOT NULL,
            n4 INTEGER NOT NULL,
            n5 INTEGER NOT NULL,
            pb INTEGER NOT NULL,
            reliability_score REAL NOT NULL,
            performance_history TEXT NOT NULL,
            win_rate REAL NOT NULL,
            avg_score REAL NOT NULL,
            times_generated INTEGER NOT NULL,
            last_generated DATETIME NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_type TEXT NOT NULL,
            component_name TEXT NOT NULL,
            original_value REAL NOT NULL,
            adjusted_value REAL NOT NULL,
            adjustment_reason TEXT NOT NULL,
            performance_impact REAL NOT NULL,
            dataset_hash TEXT NOT NULL,
            model_version TEXT NOT NULL,
            is_applied BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            applied_at DATETIME NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS draw_evaluation_results (
            draw_date DATE PRIMARY KEY,
            total_tickets INTEGER DEFAULT 0,
            matches_3 INTEGER DEFAULT 0,
            matches_4 INTEGER DEFAULT 0,
            matches_5 INTEGER DEFAULT 0,
            matches_5_pb INTEGER DEFAULT 0,
            total_prize REAL DEFAULT 0,
            has_predictions BOOLEAN DEFAULT 1,
            evaluation_date DATETIME,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _create_indexes(cursor):
    """Create performance indexes for frequently queried columns."""
    indexes = [
        # Legacy indexes for `predictions_log` (preserved as history; the active
        # runtime schema uses `generated_tickets` and these indexes should not
        # be created against the dropped/archived legacy table.)
        # ("idx_predictions_log_created_at", "predictions_log", "created_at DESC"),
        # ("idx_predictions_log_target_date", "predictions_log", "target_draw_date"),
        ("idx_performance_tracking_prediction_id", "performance_tracking", "prediction_id"),
        ("idx_performance_tracking_draw_date", "performance_tracking", "draw_date"),
        ("idx_powerball_draws_date", "powerball_draws", "draw_date"),
        ("idx_pipeline_executions_status", "pipeline_executions", "status"),
        ("idx_pipeline_executions_start_time", "pipeline_executions", "start_time DESC"),
        ("idx_pipeline_executions_trigger_type", "pipeline_executions", "trigger_type"),
        ("idx_pipeline_executions_execution_id", "pipeline_executions", "execution_id"),
        # Weekly verification limits indexes
        ("idx_weekly_limits_user_week", "weekly_verification_limits", "user_id, week_start_date"),
        ("idx_weekly_limits_device_week", "weekly_verification_limits", "device_fingerprint, week_start_date"),
        ("idx_weekly_limits_week_start", "weekly_verification_limits", "week_start_date DESC"),
        # IP rate limiting indexes
        ("idx_ip_limits_ip_hour", "ip_rate_limits", "ip_address, hour_window"),
        ("idx_ip_limits_hour_window", "ip_rate_limits", "hour_window DESC"),
        # Stripe billing indexes
        ("idx_idempotency_keys_key", "idempotency_keys", "idempotency_key"),
        ("idx_webhook_events_stripe_id", "webhook_events", "stripe_event_id"),
        ("idx_webhook_events_type", "webhook_events", "event_type"),
        ("idx_webhook_events_processed", "webhook_events", "processed"),
        ("idx_stripe_customers_email", "stripe_customers", "email"),
        ("idx_stripe_customers_stripe_id", "stripe_customers", "stripe_customer_id"),
        ("idx_stripe_subscriptions_customer", "stripe_subscriptions", "stripe_customer_id"),
        ("idx_stripe_subscriptions_status", "stripe_subscriptions", "status"),
        ("idx_premium_passes_email", "premium_passes", "email"),
        ("idx_premium_passes_token", "premium_passes", "pass_token"),
        ("idx_premium_passes_jti", "premium_passes", "jti"),
        ("idx_premium_passes_subscription", "premium_passes", "stripe_subscription_id"),
        ("idx_premium_pass_devices_pass", "premium_pass_devices", "pass_id"),
        ("idx_premium_pass_devices_fingerprint", "premium_pass_devices", "device_fingerprint")
    ]

    for index_name, table_name, columns in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})")
        except sqlite3.Error as e:
            logger.warning(f"Error creating index {index_name}: {e}")

    logger.info("Database performance indexes created successfully")




def get_latest_draw_date() -> Optional[str]:
    """Retrieve the most recent draw date from the database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(draw_date) FROM powerball_draws")
            result = cursor.fetchone()
            latest_date = result[0] if result else None
            if latest_date:
                logger.info(f"Latest draw date in DB: {latest_date}")
            else:
                logger.info("No existing data found in 'powerball_draws'.")
            return latest_date
    except sqlite3.Error as e:
        logger.error(f"Failed to get latest draw date: {e}")
        return None


def get_draw_by_date(draw_date: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a specific draw by date.

    Args:
        draw_date: Date in YYYY-MM-DD format

    Returns:
        Dict with draw data or None if not found
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT draw_date, n1, n2, n3, n4, n5, pb FROM powerball_draws WHERE draw_date = ?",
                (draw_date,)
            )
            result = cursor.fetchone()
            if result:
                return {
                    'draw_date': result[0],
                    'n1': result[1],
                    'n2': result[2],
                    'n3': result[3],
                    'n4': result[4],
                    'n5': result[5],
                    'pb': result[6]
                }
            return None
    except sqlite3.Error as e:
        logger.error(f"Failed to get draw by date {draw_date}: {e}")
        return None


def bulk_insert_draws(df: pd.DataFrame) -> int:
    """
    Insert or replace a batch of draw data into the database from a DataFrame.

    Args:
        df: DataFrame with columns [draw_date, n1, n2, n3, n4, n5, pb]

    Returns:
        Number of rows inserted/updated
    """
    if df.empty:
        logger.info("No new draws to insert.")
        return 0

    try:
        with get_db_connection() as conn:
            df.to_sql('powerball_draws', conn, if_exists='append', index=False)
            row_count = len(df)
            logger.info(f"Successfully inserted {row_count} rows into the database.")
            return row_count
    except sqlite3.IntegrityError as e:
        logger.warning(f"Integrity constraint violation during bulk insert: {e}. Using upsert method.")
        return _upsert_draws(df)
    except sqlite3.Error as e:
        logger.error(f"SQLite error during bulk insert: {e}")
        return 0


def _upsert_draws(df: pd.DataFrame) -> int:
    """
    Slower, row-by-row insert/replace for handling duplicates.

    Args:
        df: DataFrame with columns [draw_date, n1, n2, n3, n4, n5, pb]

    Returns:
        Number of rows upserted
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            for _, row in df.iterrows():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO powerball_draws (draw_date, n1, n2, n3, n4, n5, pb)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, tuple(row))
            conn.commit()
            row_count = len(df)
            logger.info(f"Successfully upserted {row_count} rows.")
            return row_count
    except sqlite3.Error as e:
        logger.error(f"SQLite error during upsert: {e}")
        return 0


def get_all_draws(max_date: str = None) -> pd.DataFrame:
    """Retrieve all historical draw data from the database.

    Args:
        max_date: Optional date limit (YYYY-MM-DD). Only returns draws before this date.
                  Used to prevent data leakage when generating historical predictions.
    """
    try:
        with get_db_connection() as conn:
            if max_date:
                query = "SELECT * FROM powerball_draws WHERE draw_date < ? ORDER BY draw_date ASC"
                df = pd.read_sql_query(
                    query,
                    conn,
                    params=(max_date,),
                    parse_dates=['draw_date']
                )
                logger.info(f"Successfully loaded {len(df)} rows from the database (filtered to before {max_date}).")
            else:
                df = pd.read_sql_query(
                    "SELECT * FROM powerball_draws ORDER BY draw_date ASC",
                    conn,
                    parse_dates=['draw_date']
                )
                logger.info(f"Successfully loaded {len(df)} rows from the database.")
            return df
    except sqlite3.Error as e:
        logger.error(f"SQLite error retrieving draws data: {e}")
        return pd.DataFrame()
    except pd.errors.DatabaseError as e:
        logger.error(f"Pandas database error: {e}")
        return pd.DataFrame()



def save_prediction_log(prediction_data: Dict[str, Any], allow_simulation: bool = False, execution_source: Optional[str] = None) -> Optional[int]:
    """Save a prediction into the active generated_tickets table and return its ID.

    This function replaces legacy predictions_log usage by mapping fields to the
    generated_tickets schema. It validates inputs and ensures ascending numbers.
    """
    try:
        logger.debug(f"Received prediction data: {prediction_data}")

        # Optional source gating (kept permissive for pipeline)
        allowed_sources = {None, "manual_dashboard", "automatic_scheduler", "pipeline_execution"}
        if execution_source not in allowed_sources:
            logger.error(f"Rejected prediction from unauthorized source: {execution_source}")
            return None

        # Sanitize and validate
        sanitized = _sanitize_prediction_data(prediction_data, allow_simulated=allow_simulation)
        if not sanitized:
            logger.error("Prediction data failed validation/sanitization")
            return None

        numbers = sanitized.get('numbers')
        powerball = int(sanitized.get('powerball')) if sanitized.get('powerball') is not None else None
        if not numbers or len(numbers) != 5 or powerball is None:
            logger.error("Prediction must include 5 numbers and a powerball")
            return None

        # Ensure numbers are strictly increasing to satisfy CHECK constraint
        numbers = sorted(int(n) for n in numbers)

        # Decide draw_date - accept both draw_date and target_draw_date for backward compatibility
        draw_date = (sanitized.get('draw_date') or sanitized.get('target_draw_date') or
                    prediction_data.get('draw_date') or prediction_data.get('target_draw_date'))
        if not draw_date:
            try:
                draw_date = calculate_next_drawing_date()
            except Exception:
                # Fallback: use today; CHECK constraints won't validate date format, just store string
                draw_date = datetime.now().strftime('%Y-%m-%d')

        # Map model_version/strategy to strategy_used; score_total -> confidence_score
        strategy_used = str(prediction_data.get('strategy') or prediction_data.get('model_version') or 'intelligent_ai')
        confidence = float(prediction_data.get('score_total') or sanitized.get('score_total') or 0.5)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO generated_tickets (
                    draw_date, strategy_used,
                    n1, n2, n3, n4, n5, powerball,
                    confidence_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draw_date, strategy_used,
                    numbers[0], numbers[1], numbers[2], numbers[3], numbers[4], powerball,
                    confidence
                )
            )
            new_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Saved prediction to generated_tickets with id={new_id} for draw {draw_date}")
            return int(new_id)
    except sqlite3.Error as e:
        logger.error(f"Database error saving prediction: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error saving prediction: {e}")
        return None


# Phase 4: Adaptive Feedback System Database Methods

def save_performance_tracking(
    prediction_id: int,
    draw_date: str,
    actual_numbers: List[int],
    actual_pb: int,
    matches_main: int,
    matches_pb: int,
    prize_tier: str,
    score_accuracy: float,
    component_accuracy: Dict,
    *,
    conn: Optional[sqlite3.Connection] = None,
    cursor: Optional[sqlite3.Cursor] = None,
) -> Optional[int]:
    """Save performance tracking for a prediction.

    If an external connection/cursor is provided, this function will use it and
    will NOT commit; the caller is responsible for committing. If no connection
    is provided, a short‑lived connection is created and committed immediately.
    """
    try:
        external = conn is not None or cursor is not None
        if cursor is None:
            if conn is None:
                conn = get_db_connection()
            cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO performance_tracking
            (prediction_id, draw_date, actual_n1, actual_n2, actual_n3, actual_n4, actual_n5,
             actual_pb, matches_main, matches_pb, prize_tier, score_accuracy, component_accuracy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction_id,
                draw_date,
                actual_numbers[0],
                actual_numbers[1],
                actual_numbers[2],
                actual_numbers[3],
                actual_numbers[4],
                actual_pb,
                matches_main,
                matches_pb,
                prize_tier,
                score_accuracy,
                json.dumps(component_accuracy, cls=NumpyEncoder),
            ),
        )

        tracking_id = cursor.lastrowid

        if not external and conn is not None:
            conn.commit()
            conn.close()

        logger.info(
            f"Performance tracking saved with ID {tracking_id} for prediction {prediction_id}"
        )
        return tracking_id

    except sqlite3.Error as e:
        logger.error(f"Error saving performance tracking: {e}")
        # Close internal connection on error if we created it
        try:
            if not external and conn is not None:
                conn.close()
        except Exception:
            pass
        return None


def save_adaptive_weights(weight_set_name: str, weights: Dict[str, float], performance_score: float, optimization_algorithm: str, dataset_hash: str, is_active: bool = False) -> Optional[int]:
    """Saves adaptive weight configuration."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            if is_active:
                cursor.execute("UPDATE adaptive_weights SET is_active = FALSE")

            cursor.execute(
                """
                INSERT INTO adaptive_weights
                (weight_set_name, probability_weight, diversity_weight, historical_weight,
                 risk_adjusted_weight, performance_score, optimization_algorithm, dataset_hash, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (weight_set_name, weights.get('probability', 0.4),
                  weights.get('diversity', 0.25), weights.get('historical', 0.2), weights.get('risk_adjusted', 0.15), performance_score,
                  optimization_algorithm, dataset_hash, is_active))

            weights_id = cursor.lastrowid
            conn.commit()

            logger.info(
                f"Adaptive weights saved with ID {weights_id}: {weight_set_name}"
            )
            return weights_id

    except sqlite3.Error as e:
        logger.error(f"Error saving adaptive weights: {e}")
        return None


def get_active_adaptive_weights() -> Optional[Dict]:
    """Retrieves the currently active adaptive weights."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT weight_set_name, probability_weight, diversity_weight, historical_weight,
                       risk_adjusted_weight, performance_score, optimization_algorithm, dataset_hash
                FROM adaptive_weights
                WHERE is_active = TRUE
                ORDER BY created_at DESC
                LIMIT 1
            """)

            result = cursor.fetchone()
            if result:
                return {
                    'weight_set_name': result[0],
                    'weights': {
                        'probability': result[1],
                        'diversity': result[2],
                        'historical': result[3],
                        'risk_adjusted': result[4]
                    },
                    'performance_score': result[5],
                    'optimization_algorithm': result[6],
                    'dataset_hash': result[7]
                }
            return None

    except sqlite3.Error as e:
        logger.error(f"Error retrieving active adaptive weights: {e}")
        return None


def save_pattern_analysis(pattern_type: str, pattern_description: str, pattern_data: Dict, success_rate: float, frequency: int, confidence_score: float, date_range_start: str, date_range_end: str) -> Optional[int]:
    """Saves pattern analysis results."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO pattern_analysis
                (pattern_type, pattern_description, pattern_data, success_rate, frequency,
                 confidence_score, date_range_start, date_range_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (pattern_type, pattern_description,
                  json.dumps(pattern_data, cls=NumpyEncoder), success_rate, frequency,
                  confidence_score, date_range_start, date_range_end))

            pattern_id = cursor.lastrowid
            conn.commit()

            logger.info(
                f"Pattern analysis saved with ID {pattern_id}: {pattern_type}")
            return pattern_id

    except sqlite3.Error as e:
        logger.error(f"Error saving pattern analysis: {e}")
        return None


def save_reliable_play(numbers: List[int], powerball: int, reliability_score: float, performance_history: Dict, win_rate: float, avg_score: float) -> Optional[int]:
    """Saves or updates a reliable play combination."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, times_generated FROM reliable_plays
                WHERE n1 = ? AND n2 = ? AND n3 = ? AND n4 = ? AND n5 = ? AND pb = ?
            """, tuple(numbers + [powerball]))

            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE reliable_plays
                    SET reliability_score = ?, performance_history = ?, win_rate = ?,
                        avg_score = ?, times_generated = ?, last_generated = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (reliability_score,
                      json.dumps(performance_history, cls=NumpyEncoder),
                      win_rate, avg_score, existing[1] + 1, existing[0]))
                play_id = existing[0]
                logger.info(f"Updated reliable play ID {play_id}")
            else:
                cursor.execute(
                    """
                    INSERT INTO reliable_plays
                    (n1, n2, n3, n4, n5, pb, reliability_score, performance_history,
                     win_rate, avg_score, times_generated, last_generated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (numbers[0], numbers[1], numbers[2], numbers[3],
                      numbers[4], powerball, reliability_score,
                      json.dumps(performance_history, cls=NumpyEncoder), win_rate, avg_score, 1))
                play_id = cursor.lastrowid
                logger.info(f"Saved new reliable play ID {play_id}")

            conn.commit()
            return play_id

    except sqlite3.Error as e:
        logger.error(f"Error saving reliable play: {e}")
        return None


def get_reliable_plays(limit: int = 20, min_reliability_score: float = 0.7) -> pd.DataFrame:
    """Retrieves reliable plays ranked by reliability score."""
    try:
        with get_db_connection() as conn:
            query = """
                SELECT id, n1, n2, n3, n4, n5, pb, reliability_score, win_rate,
                       avg_score, times_generated, last_generated, created_at
                FROM reliable_plays
                WHERE reliability_score >= ?
                ORDER BY reliability_score DESC, times_generated DESC
                LIMIT ?
            """
            # Load reliable plays from database with filtering on reliability score and limit
            df = pd.read_sql(query, conn, params=(min_reliability_score, limit))
            logger.info(f"Retrieved {len(df)} reliable plays")
            return df
    except sqlite3.Error as e:
        logger.error(f"Error retrieving reliable plays: {e}")
        return pd.DataFrame()


def save_model_feedback(feedback_type: str, component_name: str, original_value: float, adjusted_value: float, adjustment_reason: str, performance_impact: float, dataset_hash: str, model_version: str) -> Optional[int]:
    """Saves model feedback for adaptive learning."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO model_feedback
                (feedback_type, component_name, original_value, adjusted_value,
                 adjustment_reason, performance_impact, dataset_hash, model_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (feedback_type, component_name, original_value,
                  adjusted_value, adjustment_reason, performance_impact,
                  dataset_hash, model_version))

            feedback_id = cursor.lastrowid
            conn.commit()

            logger.info(
                f"Model feedback saved with ID {feedback_id}: {feedback_type}")
            return feedback_id

    except sqlite3.Error as e:
        logger.error(f"Error saving model feedback: {e}")
        return None


def get_performance_analytics(days_back: int = 30) -> Dict:
    """Retrieves performance analytics for the specified time period."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_predictions,
                    AVG(pt.score_accuracy) as avg_accuracy,
                    AVG(pt.matches_main) as avg_main_matches,
                    AVG(pt.matches_pb) as avg_pb_matches,
                    COUNT(CASE WHEN pt.prize_tier != 'Non-winning' THEN 1 END) as winning_predictions
                FROM performance_tracking pt
                JOIN generated_tickets pl ON pt.prediction_id = pl.id
                WHERE pt.created_at >= datetime('now', '-' || ? || ' days')
            """, (days_back,))

            overall_stats = cursor.fetchone()

            cursor.execute(
                """
                SELECT pt.prize_tier, COUNT(*) as count
                FROM performance_tracking pt
                JOIN generated_tickets pl ON pt.prediction_id = pl.id
                WHERE pt.created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY pt.prize_tier
                ORDER BY count DESC
            """, (days_back,))

            prize_distribution = dict(cursor.fetchall())

            cursor.execute(
                """
                SELECT DATE(pt.created_at) as date, AVG(pt.score_accuracy) as avg_accuracy
                FROM performance_tracking pt
                JOIN generated_tickets pl ON pt.prediction_id = pl.id
                WHERE pt.created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY DATE(pt.created_at)
                ORDER BY date
            """, (days_back,))

            accuracy_trends = dict(cursor.fetchall())

            analytics = {
                'period_days': days_back,
                'total_predictions': overall_stats[0] if overall_stats and overall_stats[0] else 0,
                'avg_accuracy': overall_stats[1] if overall_stats and overall_stats[1] else 0.0,
                'avg_main_matches': overall_stats[2] if overall_stats and overall_stats[2] else 0.0,
                'avg_pb_matches': overall_stats[3] if overall_stats and overall_stats[3] else 0.0,
                'winning_predictions': overall_stats[4] if overall_stats and overall_stats[4] else 0,
                'win_rate': (overall_stats[4] / overall_stats[0] * 100) if overall_stats and overall_stats[0] > 0 else 0.0,
                'prize_distribution': prize_distribution,
                'accuracy_trends': accuracy_trends
            }

            logger.info(
                f"Retrieved performance analytics for {days_back} days")
            return analytics

    except sqlite3.Error as e:
        logger.error(f"Error retrieving performance analytics: {e}")
        return {
            'total_predictions': 0,
            'total_winnings': 0.0,
            'average_score': 0.0,
            'accuracy_rate': 0.0,
            'predictions_by_date': [],
            'performance_by_rank': []
        }


def get_draw_analytics(draw_date: str, limit: int = 50) -> Dict[str, Any]:
    """Return analytics for a specific draw date based on generated_tickets.

    Returns counts, total prizes, top predictions (by confidence) and the official draw numbers.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Official draw numbers
        cursor.execute("SELECT n1, n2, n3, n4, n5, pb FROM powerball_draws WHERE draw_date = ?", (draw_date,))
        draw_row = cursor.fetchone()
        if draw_row:
            winning_numbers = list(draw_row[:5])
            winning_pb = draw_row[5]
        else:
            winning_numbers = []
            winning_pb = None

        # Load all predictions for draw_date to compute richer analytics
        cursor.execute(
            """
            SELECT id, n1, n2, n3, n4, n5, powerball, confidence_score, strategy_used, prize_won, created_at
            FROM generated_tickets
            WHERE draw_date = ?
            """,
            (draw_date,)
        )
        rows = cursor.fetchall()

        total_predictions = len(rows)
        winning_predictions = 0
        total_prize = 0.0

        # Structures for analytics
        prize_tiers: Dict[str, Dict[str, Any]] = {}
        strategy_counts: Dict[str, Dict[str, Any]] = {}
        match_distribution: Dict[int, Dict[str, int]] = {i: {'with_pb': 0, 'without_pb': 0} for i in range(0, 6)}
        confidence_buckets = {'high': {'count': 0, 'sum_conf': 0.0},
                              'medium': {'count': 0, 'sum_conf': 0.0},
                              'low': {'count': 0, 'sum_conf': 0.0}}
        # Collect all rows (id -> confidence) to compute generation rank consistently
        id_to_conf: Dict[int, float] = {}
        # Build winning predictions list from computed prizes to avoid dependency on stored prize_won
        computed_winners: List[Dict[str, Any]] = []

        try:
            from src.prize_calculator import calculate_prize_amount
        except Exception:
            # Fallback mapping if prize_calculator unavailable
            def calculate_prize_amount(main_matches, pb):
                if main_matches == 5 and pb:
                    return (100000000.0, 'Jackpot')
                if main_matches == 5:
                    return (1000000.0, 'Match 5')
                if main_matches == 4 and pb:
                    return (50000.0, 'Match 4 + PB')
                if main_matches == 4:
                    return (100.0, 'Match 4')
                if main_matches == 3 and pb:
                    return (100.0, 'Match 3 + PB')
                if main_matches == 3:
                    return (7.0, 'Match 3')
                if main_matches == 2 and pb:
                    return (7.0, 'Match 2 + PB')
                if main_matches == 1 and pb:
                    return (4.0, 'Match 1 + PB')
                if main_matches == 0 and pb:
                    return (4.0, 'Powerball Only')
                return (0.0, 'No Prize')

        # Compute analytics by iterating tickets
        for r in rows:
            tid, a, b, c, d, e, pb, conf, strat, prize_val, created_at = r
            ticket_nums = [a, b, c, d, e]
            # Compute main matches by counting intersections
            matches_main = 0
            for n in ticket_nums:
                if n in winning_numbers:
                    matches_main += 1

            pb_match = (pb == winning_pb)

            prize_amount, prize_desc = calculate_prize_amount(matches_main, pb_match)

            # Accumulate totals
            total_prize += float(prize_amount or 0.0)
            if prize_amount and prize_amount > 0:
                winning_predictions += 1

            # Keep confidence map for generation rank calculation
            try:
                id_to_conf[int(tid)] = float(conf) if conf is not None else 0.0
            except Exception:
                pass

            # Build computed winners list independent of stored prize_won
            if prize_amount and prize_amount > 0:
                computed_winners.append({
                    'id': int(tid) if tid is not None else None,
                    'n1': a, 'n2': b, 'n3': c, 'n4': d, 'n5': e,
                    'powerball': pb,
                    'confidence_score': float(conf) if conf is not None else 0.0,
                    'strategy_used': strat,
                    'prize_won': float(prize_amount)
                })

            # Prize tier breakdown
            tier = prize_desc or str(prize_amount)
            if tier not in prize_tiers:
                prize_tiers[tier] = {'count': 0, 'total_prize': 0.0}
            prize_tiers[tier]['count'] += 1
            prize_tiers[tier]['total_prize'] += float(prize_amount or 0.0)

            # Strategy counts
            strat_key = strat if strat else 'unknown'
            if strat_key not in strategy_counts:
                strategy_counts[strat_key] = {'count': 0, 'wins': 0, 'total_prize': 0.0}
            strategy_counts[strat_key]['count'] += 1
            if prize_amount and prize_amount > 0:
                strategy_counts[strat_key]['wins'] += 1
                strategy_counts[strat_key]['total_prize'] += float(prize_amount or 0.0)

            # Match distribution (0-5 main matches) split by PB
            md = match_distribution.get(matches_main)
            if pb_match:
                md['with_pb'] += 1
            else:
                md['without_pb'] += 1

            # Confidence buckets
            conf_val = float(conf) if conf is not None else 0.0
            if conf_val >= 0.75:
                bucket = 'high'
            elif conf_val >= 0.5:
                bucket = 'medium'
            else:
                bucket = 'low'
            confidence_buckets[bucket]['count'] += 1
            confidence_buckets[bucket]['sum_conf'] += conf_val

        # Prepare winning predictions list from computed winners to ensure consistency
        # Compute generation_rank by ordering all tickets by confidence desc, id asc
        # Build ranking map
        try:
            # Create sorted list of (id, conf) pairs
            conf_sorted = sorted(
                [(pid, c) for pid, c in id_to_conf.items()],
                key=lambda x: (-x[1], x[0] if x[0] is not None else 0)
            )
            rank_map: Dict[int, int] = {}
            for idx, (pid, _) in enumerate(conf_sorted, start=1):
                rank_map[pid] = idx
        except Exception:
            rank_map = {}

        # Sort computed winners by prize desc, then confidence desc
        winning_predictions_list: List[Dict[str, Any]] = sorted(
            computed_winners,
            key=lambda w: (-(w.get('prize_won') or 0.0), -(w.get('confidence_score') or 0.0))
        )
        # Attach generation rank if available
        for w in winning_predictions_list:
            pid = w.get('id')
            w['generation_rank'] = rank_map.get(pid)

        # Also prepare top predictions by confidence (for reference)
        cursor.execute(
            """
            SELECT id, n1, n2, n3, n4, n5, powerball, confidence_score, strategy_used, prize_won
            FROM generated_tickets
            WHERE draw_date = ?
            ORDER BY confidence_score DESC
            LIMIT ?
            """,
            (draw_date, limit)
        )
        top_rows = cursor.fetchall()
        top_predictions = []
        for r in top_rows:
            top_predictions.append({
                'id': r[0],
                'n1': r[1], 'n2': r[2], 'n3': r[3], 'n4': r[4], 'n5': r[5],
                'powerball': r[6],
                'confidence_score': float(r[7]) if r[7] is not None else 0.0,
                'strategy_used': r[8],
                'prize_won': float(r[9]) if r[9] is not None else 0.0
            })

        conn.close()

        # finalize confidence metrics
        confidence_summary = {}
        for k, v in confidence_buckets.items():
            confidence_summary[k] = {
                'count': v['count'],
                'avg_confidence': (v['sum_conf'] / v['count']) if v['count'] > 0 else 0.0
            }

        return {
            'draw_date': draw_date,
            'winning_numbers': {
                'main_numbers': winning_numbers,
                'powerball': winning_pb
            },
            'total_predictions': total_predictions,
            # Ensure this matches the computed winners list size for consistency in UI
            'predictions_with_prizes': len(winning_predictions_list),
            'total_prize': total_prize,
            'prize_tiers': prize_tiers,
            'strategy_counts': strategy_counts,
            'match_distribution': match_distribution,
            'confidence_summary': confidence_summary,
            # Provide full list of winning predictions for UI rendering
            'winning_predictions': winning_predictions_list,
            'top_predictions': top_predictions  # Top N by confidence for reference
        }

    except sqlite3.Error as e:
        logger.error(f"SQLite error in get_draw_analytics: {e}")
        return {
            'draw_date': draw_date,
            'winning_numbers': {'main_numbers': [], 'powerball': None},
            'total_predictions': 0,
            'predictions_with_prizes': 0,
            'total_prize': 0.0,
            'top_predictions': []
        }


def get_best_match_all_time() -> Optional[Dict[str, Any]]:
    """Return the historical draw with the highest computed prize total.

    Uses powerball_draws as the official result source and generated_tickets as
    the prediction source, matching the public recent-draws and draw analytics
    calculation path instead of relying on stored prize_won values.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(generated_tickets)")
        generated_ticket_columns = {str(row[1]) for row in cursor.fetchall()}
        if "powerball" in generated_ticket_columns:
            ticket_pb_column = "powerball"
        elif "pb" in generated_ticket_columns:
            ticket_pb_column = "pb"
        else:
            conn.close()
            logger.error("generated_tickets is missing a Powerball column")
            return None

        cursor.execute(
            f"""
            SELECT
                p.rowid,
                p.draw_date,
                p.n1, p.n2, p.n3, p.n4, p.n5, p.pb,
                gt.n1, gt.n2, gt.n3, gt.n4, gt.n5, gt.{ticket_pb_column}
            FROM powerball_draws p
            JOIN generated_tickets gt ON gt.draw_date = p.draw_date
            ORDER BY p.draw_date DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None

        draws: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            draw_id = int(row[0]) if row[0] is not None else 0
            draw_date = str(row[1]) if row[1] else ""
            winning_numbers = [
                int(row[2] or 0),
                int(row[3] or 0),
                int(row[4] or 0),
                int(row[5] or 0),
                int(row[6] or 0),
            ]
            winning_pb = int(row[7] or 0)
            ticket_numbers = [
                int(row[8] or 0),
                int(row[9] or 0),
                int(row[10] or 0),
                int(row[11] or 0),
                int(row[12] or 0),
            ]
            ticket_pb = int(row[13] or 0)

            draw_summary = draws.setdefault(
                draw_date,
                {
                    "id": draw_id,
                    "draw_date": draw_date,
                    "n1": winning_numbers[0],
                    "n2": winning_numbers[1],
                    "n3": winning_numbers[2],
                    "n4": winning_numbers[3],
                    "n5": winning_numbers[4],
                    "pb": winning_pb,
                    "has_predictions": True,
                    "total_prize": 0.0,
                    "total_tickets": 0,
                    "predictions_with_prizes": 0,
                    "best_prize": 0.0,
                    "best_result": "No Match",
                    "jackpot": "Not available",
                },
            )

            main_matches = len(set(ticket_numbers) & set(winning_numbers))
            pb_match = ticket_pb == winning_pb
            prize_amount, prize_description = calculate_prize_amount(main_matches, pb_match)
            prize_amount = float(prize_amount or 0.0)

            draw_summary["total_tickets"] += 1
            draw_summary["total_prize"] += prize_amount
            if prize_amount > 0:
                draw_summary["predictions_with_prizes"] += 1
            if prize_amount > draw_summary["best_prize"]:
                draw_summary["best_prize"] = prize_amount
                draw_summary["best_result"] = prize_description or "No Match"

        best_draw = max(
            draws.values(),
            key=lambda d: (
                float(d.get("total_prize") or 0.0),
                float(d.get("best_prize") or 0.0),
                int(d.get("predictions_with_prizes") or 0),
                str(d.get("draw_date") or ""),
            ),
        )

        best_draw["total_prize"] = float(best_draw.get("total_prize") or 0.0)
        best_draw["best_prize"] = float(best_draw.get("best_prize") or 0.0)
        return best_draw

    except sqlite3.Error as e:
        logger.error(f"SQLite error in get_best_match_all_time: {e}")
        return None


def get_analytics_summary(days_back: int = 30) -> Dict[str, Any]:
    """Return high-level analytics summary for the site over the given period."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                COUNT(*) as total_predictions,
                COUNT(CASE WHEN prize_won > 0 THEN 1 END) as winning_predictions,
                COALESCE(SUM(COALESCE(prize_won, 0)), 0) as total_prize,
                AVG(confidence_score) as avg_confidence
            FROM generated_tickets
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            """,
            (days_back,)
        )

        row = cursor.fetchone() or (0, 0, 0, 0.0)
        conn.close()

        return {
            'period_days': days_back,
            'total_predictions': int(row[0] or 0),
            'winning_predictions': int(row[1] or 0),
            'total_prize': float(row[2] or 0.0),
            'avg_confidence': float(row[3] or 0.0)
        }

    except sqlite3.Error as e:
        logger.error(f"SQLite error in get_analytics_summary: {e}")
        return {
            'period_days': days_back,
            'total_predictions': 0,
            'winning_predictions': 0,
            'total_prize': 0.0,
            'avg_confidence': 0.0
        }


def get_prediction_details(prediction_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve prediction details.

    If a json_details_path column exists and points to a file, load and return it.
    Otherwise, build a details structure from generated_tickets columns.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Detect if json_details_path column exists
            cursor.execute("PRAGMA table_info(generated_tickets)")
            cols = [row[1] for row in cursor.fetchall()]
            has_json_path = 'json_details_path' in cols

            if has_json_path:
                cursor.execute(
                    "SELECT json_details_path FROM generated_tickets WHERE id = ?",
                    (prediction_id,)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    json_path = row[0]
                    try:
                        if os.path.exists(json_path):
                            with open(json_path, 'r', encoding='utf-8') as f:
                                return json.load(f)
                        else:
                            logger.warning(f"JSON file not found for prediction {prediction_id}: {json_path}")
                    except (OSError, json.JSONDecodeError) as e:
                        logger.warning(f"Failed to read JSON details for prediction {prediction_id}: {e}")

            # Fallback: build details from current columns
            cursor.execute(
                """
                SELECT id, draw_date, n1, n2, n3, n4, n5, powerball,
                       strategy_used, confidence_score, created_at
                FROM generated_tickets
                WHERE id = ?
                """,
                (prediction_id,)
            )
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Prediction with ID {prediction_id} not found")
                return None

            return {
                'id': row[0],
                'draw_date': row[1],
                'numbers': [row[2], row[3], row[4], row[5], row[6]],
                'powerball': row[7],
                'strategy_used': row[8],
                'confidence_score': float(row[9]) if row[9] is not None else 0.0,
                'created_at': row[10]
            }

    except sqlite3.Error as e:
        logger.error(f"Database error retrieving prediction details for ID {prediction_id}: {e}")
        return None

def get_evaluated_predictions_count(execution_id: str) -> int:
    """Get count of evaluated predictions for a specific execution"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Count evaluated predictions for this execution timeframe
            cursor.execute("""
                SELECT COUNT(*)
                FROM generated_tickets
                WHERE evaluated = 1
                AND draw_date IS NOT NULL
                AND prize_won IS NOT NULL
                AND created_at >= (
                    SELECT start_time FROM pipeline_executions
                    WHERE execution_id = ?
                )
                AND created_at <= COALESCE((
                    SELECT end_time FROM pipeline_executions
                    WHERE execution_id = ?
                ), datetime('now'))
            """, (execution_id, execution_id))

            count = cursor.fetchone()[0] or 0
            logger.info(f"Found {count} evaluated predictions for execution {execution_id}")
            return count

    except Exception as e:
        logger.error(f"Error counting evaluated predictions for execution {execution_id}: {e}")
        return 0

def get_evaluated_predictions_for_execution(execution_id: str) -> Optional[Dict[str, Any]]:
    """Get evaluation results for a specific execution"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get predictions that were evaluated for this execution
            cursor.execute("""
                SELECT
                    n1, n2, n3, n4, n5, pb, prize_won, matches_regular, matches_powerball, draw_date
                FROM generated_tickets
                WHERE evaluated = 1
                AND draw_date IS NOT NULL
                AND created_at >= (
                    SELECT start_time FROM pipeline_executions
                    WHERE execution_id = ?
                )
                AND created_at <= COALESCE((
                    SELECT end_time FROM pipeline_executions
                    WHERE execution_id = ?
                ), datetime('now'))
                ORDER BY prize_won DESC
                LIMIT 100
            """, (execution_id, execution_id))

            predictions_data = cursor.fetchall()

            if not predictions_data:
                return None

            # Get draw date (should be same for all)
            draw_date = predictions_data[0][9] if predictions_data else None

            # Format predictions
            predictions = []
            for row in predictions_data:
                try:
                    predictions.append({
                        'numbers': [row[0], row[1], row[2], row[3], row[4]],
                        'powerball': row[5],
                        'prize_won': row[6] or 0,
                        'matches_regular': row[7] or 0,
                        'matches_powerball': row[8] or 0
                    })
                except Exception as e:
                    logger.warning(f"Error parsing prediction data: {e}")
                    continue

            return {
                'predictions': predictions,
                'draw_date': draw_date,
                'execution_id': execution_id
            }

    except Exception as e:
        logger.error(f"Error getting evaluated predictions for execution {execution_id}: {e}")
        return None

def get_predictions_by_dataset_hash(dataset_hash: str) -> pd.DataFrame:
    """Retrieve all predictions associated with a specific dataset hash."""
    try:
        with get_db_connection() as conn:
            query = """
                SELECT id, timestamp, n1, n2, n3, n4, n5, powerball,
                       score_total, model_version, created_at
                FROM generated_tickets
                WHERE dataset_hash = ?
                ORDER BY created_at DESC
            """
            df = pd.read_sql(query, conn, params=(dataset_hash,))
            logger.debug(f"Executed query with dataset_hash={dataset_hash}")
            logger.info(
                f"Retrieved {len(df)} predictions for dataset hash {dataset_hash}"
            )
            return df
    except sqlite3.Error as e:
        logger.error(f"Error retrieving predictions by dataset hash: {e}")
        return pd.DataFrame()


def get_predictions_grouped_by_date(limit_dates: int = 25) -> List[Dict]:
    """
    Get predictions grouped by date for draws that have already occurred.
    Only includes REAL pipeline predictions for draws with official results.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT DISTINCT
                    pd.draw_date as target_date,
                    COUNT(pl.id) as total_predictions,
                    COUNT(CASE WHEN pl.evaluated = 1 AND pl.prize_won > 0 THEN 1 END) as winning_predictions,
                    COUNT(CASE WHEN pl.evaluated = 1 THEN 1 END) as evaluated_predictions,
                    SUM(CASE WHEN pl.evaluated = 1 THEN pl.prize_won ELSE 0 END) as total_prizes
                FROM powerball_draws pd
                INNER JOIN generated_tickets pl ON pl.draw_date = pd.draw_date
                WHERE pl.created_at IS NOT NULL
                    AND pl.strategy_used NOT IN ('fallback', 'test', 'simulated', 'default')
                    AND pl.dataset_hash NOT IN ('simulated', 'test', 'fallback', 'default')
                    AND pl.confidence_score > 0
                    AND LENGTH(pl.dataset_hash) >= 16
                    AND pl.json_details_path IS NOT NULL
                    AND pl.draw_date IS NOT NULL
                GROUP BY pd.draw_date
                HAVING COUNT(pl.id) > 0
                ORDER BY pd.draw_date DESC
                LIMIT ?
            """, (limit_dates,))

            date_groups = cursor.fetchall()

            grouped_results = []

            spanish_months = {
                1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun',
                7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'
            }

            for date_row in date_groups:
                target_date = date_row[0]
                total_predictions_for_date = date_row[1]

                cursor.execute(
                    """
                    SELECT
                        pl.id, pl.created_at, pl.n1, pl.n2, pl.n3, pl.n4, pl.n5, pl.pb,
                        pt.matches_main, pt.matches_pb, pt.prize_tier,
                        pl.draw_date,
                        pl.created_at
                    FROM generated_tickets pl
                    LEFT JOIN performance_tracking pt ON pl.id = pt.prediction_id
                    WHERE pl.draw_date = ?
                    ORDER BY pl.confidence_score DESC
                """, (target_date,))

                predictions_data = cursor.fetchall()

                predictions = []
                total_prize = 0.0
                winning_predictions = 0
                best_prize_amount = 0.0
                best_prize_description = "No matches"

                for pred_row in predictions_data:
                    prediction_numbers = [pred_row[2], pred_row[3], pred_row[4], pred_row[5], pred_row[6]]
                    prediction_pb = pred_row[7]
                    prediction_draw_date = pred_row[11] or target_date
                    prediction_created_at = pred_row[12]

                    cursor.execute(
                        "SELECT n1, n2, n3, n4, n5, pb FROM powerball_draws WHERE draw_date = ?",
                        (prediction_draw_date,))
                    official_result = cursor.fetchone()

                    matches_main = 0
                    powerball_match = False
                    prize_amount = 0.0
                    prize_description = "No matches"

                    if official_result:
                        winning_numbers = [official_result[0], official_result[1], official_result[2], official_result[3], official_result[4]]
                        winning_pb = official_result[5]

                        matches_main = len(set(prediction_numbers) & set(winning_numbers))
                        powerball_match = prediction_pb == winning_pb

                        try:
                            prize_amount, prize_description = calculate_prize_amount(matches_main, powerball_match)
                        except Exception as e:
                            logger.error(f"Error calculating prize amount: {e}")
                            prize_amount, prize_description = 0.0, "Error calculating prize"

                    total_prize += prize_amount
                    if prize_amount > 0:
                        winning_predictions += 1

                    if prize_amount > best_prize_amount:
                        best_prize_amount = prize_amount
                        best_prize_description = prize_description

                    prediction_detail = {
                        "prediction_id": pred_row[0],
                        "created_at": pred_row[1],
                        "numbers": prediction_numbers,
                        "powerball": prediction_pb,
                        "draw_date": prediction_draw_date,
                        "matches_main": matches_main,
                        "powerball_match": powerball_match,
                        "prize_amount": prize_amount,
                        "prize_description": prize_description,
                        "has_prize": prize_amount > 0
                    }
                    predictions.append(prediction_detail)

                try:
                    date_obj = datetime.strptime(target_date, '%Y-%m-%d')
                    formatted_date = f"{date_obj.day} {spanish_months[date_obj.month]} {date_obj.year}"
                except Exception as e:
                    logger.warning(f"Failed to format date: {e}")
                    formatted_date = target_date

                if best_prize_amount >= 100000000:
                    total_prize_display = "JACKPOT!"
                elif total_prize >= 1000000:
                    total_prize_display = f"${total_prize/1000000:.1f}M"
                elif total_prize >= 1000:
                    total_prize_display = f"${total_prize/1000:.0f}K"
                elif total_prize > 0:
                    total_prize_display = f"${total_prize:.0f}"
                else:
                    total_prize_display = "$0"

                win_rate = (winning_predictions / total_predictions_for_date * 100) if total_predictions_for_date > 0 else 0.0

                grouped_result = {
                    "date": target_date,
                    "formatted_date": formatted_date,
                    "total_plays": total_predictions_for_date,
                    "winning_plays": winning_predictions,
                    "win_rate_percentage": f"{win_rate:.1f}%",
                    "best_prize": best_prize_description,
                    "best_prize_amount": best_prize_amount,
                    "total_prize_amount": total_prize,
                    "total_prize_display": total_prize_display,
                    "predictions": predictions,
                    "context": f"Predictions generated for drawing on {formatted_date}"
                }
                grouped_results.append(grouped_result)

            # Return grouped results for requested dates
            logger.info(f"Retrieved {len(grouped_results)} grouped prediction dates")
            return grouped_results

    except sqlite3.Error as e:
        logger.error(
            f"Error retrieving predictions with results comparison: {e}")
        return []


def get_grouped_predictions_with_results_comparison(limit_groups: int = 5) -> List[Dict]:
    """Return grouped prediction results by draw_date using generated_tickets + powerball_draws.

    Builds a compact structure the frontend expects, including a summary with totals.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Latest draw dates where we have both official results and generated tickets
            cursor.execute(
                """
                SELECT pd.draw_date
                FROM powerball_draws pd
                JOIN generated_tickets gt ON gt.draw_date = pd.draw_date
                GROUP BY pd.draw_date
                ORDER BY pd.draw_date DESC
                LIMIT ?
                """,
                (limit_groups,)
            )
            draw_dates = [row[0] for row in cursor.fetchall()]

            grouped: List[Dict[str, Any]] = []

            for draw_date in draw_dates:
                # Official results
                cursor.execute(
                    "SELECT n1, n2, n3, n4, n5, pb FROM powerball_draws WHERE draw_date = ?",
                    (draw_date,)
                )
                r = cursor.fetchone()
                if not r:
                    # Shouldn't happen due to join above
                    continue
                winning_numbers = [r[0], r[1], r[2], r[3], r[4]]
                winning_powerball = r[5]

                # Predictions for this draw
                cursor.execute(
                    """
                    SELECT id, created_at, n1, n2, n3, n4, n5, powerball
                    FROM generated_tickets
                    WHERE draw_date = ?
                    ORDER BY created_at ASC
                    """,
                    (draw_date,)
                )
                preds = cursor.fetchall()
                if not preds:
                    continue

                predictions = []
                total_prize = 0.0
                total_matches = 0
                winning_predictions = 0

                for idx, row in enumerate(preds):
                    pid, created_at, a, b, c, d, e, pb = row
                    numbers = [a, b, c, d, e]
                    number_matches = [{
                        'number': n,
                        'position': i,
                        'is_match': n in winning_numbers
                    } for i, n in enumerate(numbers)]

                    main_matches = sum(1 for m in number_matches if m['is_match'])
                    pb_match = (pb == winning_powerball)
                    prize_amount, prize_desc = calculate_prize_amount(main_matches, pb_match)

                    total_prize += float(prize_amount or 0.0)
                    total_matches += int(main_matches)
                    if prize_amount and prize_amount > 0:
                        winning_predictions += 1

                    if prize_amount >= 100000000:
                        prize_display = "JACKPOT!"
                    elif prize_amount >= 1000000:
                        prize_display = f"${prize_amount/1000000:.1f}M"
                    elif prize_amount >= 1000:
                        prize_display = f"${prize_amount/1000:.0f}K"
                    elif prize_amount > 0:
                        prize_display = f"${prize_amount:.2f}"
                    else:
                        prize_display = "$0.00"

                    predictions.append({
                        'prediction_id': pid,
                        'prediction_date': created_at,
                        'prediction_numbers': numbers,
                        'prediction_powerball': pb,
                        'winning_numbers': winning_numbers,
                        'winning_powerball': winning_powerball,
                        'number_matches': number_matches,
                        'powerball_match': pb_match,
                        'total_matches': main_matches,
                        'prize_amount': float(prize_amount or 0.0),
                        'prize_description': prize_desc,
                        'prize_display': prize_display,
                        'has_prize': bool(prize_amount and prize_amount > 0),
                        'play_number': idx + 1
                    })

                num_predictions = len(predictions)
                avg_matches = (total_matches / num_predictions) if num_predictions > 0 else 0.0
                win_rate = (winning_predictions / num_predictions * 100.0) if num_predictions > 0 else 0.0

                if total_prize >= 100000000:
                    total_prize_display = "JACKPOT!"
                elif total_prize >= 1000000:
                    total_prize_display = f"${total_prize/1000000:.1f}M"
                elif total_prize >= 1000:
                    total_prize_display = f"${total_prize/1000:.0f}K"
                elif total_prize > 0:
                    total_prize_display = f"${total_prize:.0f}"
                else:
                    total_prize_display = "$0"

                # Determine best result
                best_result = "No Match"
                if predictions:
                    bp = max(predictions, key=lambda p: (p['total_matches'], p['powerball_match'], p['prize_amount']))
                    if bp['total_matches'] == 5 and bp['powerball_match']:
                        best_result = 'JACKPOT'
                    elif bp['total_matches'] == 5:
                        best_result = '5 Numbers'
                    elif bp['total_matches'] == 4 and bp['powerball_match']:
                        best_result = '4 + PB'
                    elif bp['total_matches'] == 4:
                        best_result = '4 Numbers'
                    elif bp['total_matches'] == 3 and bp['powerball_match']:
                        best_result = '3 + PB'
                    elif bp['total_matches'] == 3:
                        best_result = '3 Numbers'
                    elif bp['total_matches'] == 2 and bp['powerball_match']:
                        best_result = '2 + PB'
                    elif bp['total_matches'] == 1 and bp['powerball_match']:
                        best_result = '1 + PB'
                    elif bp['powerball_match']:
                        best_result = 'PB Only'

                grouped.append({
                    'draw_date': draw_date,
                    'winning_numbers': winning_numbers,
                    'winning_powerball': winning_powerball,
                    'prediction_date': predictions[0]['prediction_date'] if predictions else None,
                    'predictions': predictions,
                    'summary': {
                        'total_prize': float(total_prize),
                        'total_prize_display': total_prize_display,
                        'predictions_with_prizes': winning_predictions,
                        'win_rate_percentage': f"{win_rate:.0f}",
                        'avg_matches': f"{avg_matches:.1f}",
                        'best_result': best_result,
                        'total_predictions': num_predictions
                    }
                })

            logger.info(f"Grouped history built for {len(grouped)} draw dates")
            return grouped
    except sqlite3.Error as e:
        logger.error(f"Error retrieving grouped predictions with results comparison: {e}")
        return []


# Hybrid Configuration System - Simple & Robust

def migrate_config_from_file() -> bool:
    """Migrate configuration from config.ini to database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM system_config")
            config_count = cursor.fetchone()[0]

            if config_count > 0:
                logger.info("Configuration already exists in database, skipping migration")
                return True

        config = configparser.ConfigParser()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, '..', 'config', 'config.ini')

        if not os.path.exists(config_path):
            logger.warning(f"Config file not found at {config_path}, using default values")
            return _create_default_config_in_db()

        config.read(config_path)

        with get_db_connection() as conn:
            cursor = conn.cursor()

            for section_name in config.sections():
                for key, value in config.items(section_name):
                    cursor.execute(
                        "INSERT OR REPLACE INTO system_config (section, key, value) VALUES (?, ?, ?)",
                        (section_name, key, value)
                    )

            cursor.execute(
                "INSERT OR REPLACE INTO system_config (section, key, value) VALUES ('system', 'config_migrated', 'true')"
            )

            # Add sample predictions for frontend testing
            sample_predictions = [
                ('2025-08-18T03:49:16.657479', 10, 15, 33, 36, 37, 7, 0.491, '1.0.0-sample', 'sample_hash_001', None, '2025-08-23'),
                ('2025-08-18T03:49:16.657479', 9, 19, 24, 27, 34, 5, 0.478, '1.0.0-sample', 'sample_hash_002', None, '2025-08-23'),
                ('2025-08-18T03:49:16.657479', 13, 17, 20, 29, 38, 5, 0.465, '1.0.0-sample', 'sample_hash_003', None, '2025-08-23'),
                ('2025-08-18T03:49:16.657479', 6, 11, 22, 31, 45, 12, 0.452, '1.0.0-sample', 'sample_hash_004', None, '2025-08-23'),
                ('2025-08-18T03:49:16.657479', 14, 25, 30, 42, 58, 8, 0.439, '1.0.0-sample', 'sample_hash_005', None, '2025-08-23')
            ]

            cursor.executemany("""
                INSERT OR IGNORE INTO predictions_log
                (created_at, n1, n2, n3, n4, n5, pb, confidence_score, strategy_used, dataset_hash, json_details_path, draw_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_predictions)

            conn.commit()

        logger.info("Configuration successfully migrated from config.ini to database")
        return True

    except (configparser.Error, sqlite3.Error, OSError) as e:
        logger.error(f"Error migrating configuration from file: {e}")
        return False


def _create_default_config_in_db() -> bool:
    """Create default configuration in database."""
    default_config = {
        'paths': {
            'db_file': 'data/shiolplus.db',
            'model_file': 'models/shiolplus.pkl'
        },
        'pipeline': {
            'execution_days_monday': 'True',
            'execution_days_wednesday': 'True',
            'execution_days_saturday': 'True',
            'execution_time': '02:00',
            'timezone': 'America/New_York',
            'auto_execution': 'True'
        },
        'predictions': {
            'count': '100',
            'method': 'deterministic'
        },
        'weights': {
            'probability': '50',
            'diversity': '20',
            'historical': '20',
            'risk': '10'
        }
    }

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            for section_name, section_data in default_config.items():
                for key, value in section_data.items():
                    cursor.execute(
                        "INSERT OR REPLACE INTO system_config (section, key, value) VALUES (?, ?, ?)",
                        (section_name, key, value)
                    )

            cursor.execute(
                "INSERT OR REPLACE INTO system_config (section, key, value) VALUES ('system', 'config_migrated', 'default')"
            )

            conn.commit()

        logger.info("Default configuration created in database")
        return True

    except sqlite3.Error as e:
        logger.error(f"Error creating default configuration: {e}")
        return False


def load_config_from_db() -> Dict[str, Any]:
    """Load configuration from database with file fallback."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT section, key, value FROM system_config")
            config_rows = cursor.fetchall()

            if not config_rows:
                logger.warning("No configuration found in database, using file fallback")
                return _load_config_from_file()

            config_dict = {}
            for section, key, value in config_rows:
                if section not in config_dict:
                    config_dict[section] = {}
                config_dict[section][key] = value

            logger.info("Configuration loaded successfully from database")
            return config_dict

    except sqlite3.Error as e:
        logger.error(f"Error loading configuration from database: {e}")
        logger.info("Falling back to config file")
        return _load_config_from_file()


def _load_config_from_file() -> Dict[str, Any]:
    """Fallback: load configuration from file."""
    try:
        config = configparser.ConfigParser()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, '..', 'config', 'config.ini')

        config.read(config_path)

        config_dict = {}
        for section in config.sections():
            config_dict[section] = dict(config.items(section))

        logger.info(f"Configuration loaded from {config_path}")
        return config_dict

    except (configparser.Error, OSError) as e:
        logger.error(f"Error loading configuration from file: {e}")
        return {}


def save_config_to_db(config_data: Dict[str, Any]) -> bool:
    """Save configuration to database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            for section_name, section_data in config_data.items():
                if isinstance(section_data, dict):
                    for key, value in section_data.items():
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO system_config (section, key, value, updated_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        """, (section_name, key, str(value)))
                else:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO system_config (section, key, value, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """, ('general', section_name, str(section_data)))

            conn.commit()

        logger.info("Configuration saved successfully to database")
        return True

    except sqlite3.Error as e:
        logger.error(f"Error saving configuration to database: {e}")
        return False


def get_config_value(section: str, key: str, default: Any = None) -> Any:
    """Get a specific configuration value with automatic fallback."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM system_config WHERE section = ? AND key = ?",
                (section, key)
            )

            result = cursor.fetchone()
            if result:
                return result[0]

        # Fallback to file if not in DB
        config = configparser.ConfigParser()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, '..', 'config', 'config.ini')

        if os.path.exists(config_path):
            config.read(config_path)
            if config.has_section(section) and config.has_option(section, key):
                return config.get(section, key)

        return default

    except (configparser.Error, sqlite3.Error) as e:
        logger.error(f"Error getting config value {section}.{key}: {e}")
        return default


def is_config_initialized() -> bool:
    """Check if hybrid configuration system is initialized."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM system_config WHERE section = 'system' AND key = 'config_migrated'"
            )

            result = cursor.fetchone()
            return result is not None

    except sqlite3.Error as e:
        logger.error(f"Error checking config initialization: {e}")
        return False


# Phase 2: Date Validation Functions

def _validate_target_draw_date(date_str: str) -> bool:
    """Validate that target_draw_date has correct format."""
    from src.date_utils import DateManager
    return DateManager.validate_date_format(date_str)


def _is_valid_drawing_date(date_str: str) -> bool:
    """Verify that a date corresponds to a drawing day."""
    from src.date_utils import DateManager
    return DateManager.is_valid_drawing_date(date_str)


def _sanitize_prediction_data(prediction_data: Dict[str, Any], allow_simulated: bool = False) -> Optional[Dict[str, Any]]:
    """Sanitize and validate all prediction fields before saving."""
    from src.date_utils import DateManager

    sanitized_data = prediction_data.copy()

    # Validate and correct timestamp using DateManager
    if 'timestamp' not in sanitized_data or not sanitized_data['timestamp']:
        sanitized_data['timestamp'] = DateManager.get_current_et_time().isoformat()

    # Validate main numbers (must be between 1-69)
    if 'numbers' in sanitized_data:
        numbers = sanitized_data['numbers']
        if isinstance(numbers, list) and len(numbers) == 5:
            valid_numbers = []
            for num in numbers:
                try:
                    num_int = int(num)
                    if 1 <= num_int <= 69:
                        valid_numbers.append(num_int)
                    else:
                        logger.warning(f"Number {num} is outside valid range 1-69")
                        return None
                except (ValueError, TypeError):
                    logger.error(f"Invalid number format: {num}")
                    return None
            sanitized_data['numbers'] = valid_numbers
        else:
            logger.error(f"Invalid numbers format: {numbers}")
            return None

    # Validate Powerball (must be between 1-26)
    if 'powerball' in sanitized_data:
        try:
            pb = int(sanitized_data['powerball'])
            if not (1 <= pb <= 26):
                logger.error(f"Powerball {pb} is outside valid range 1-26")
                return None
            sanitized_data['powerball'] = pb
        except (ValueError, TypeError):
            logger.error(f"Invalid powerball format: {sanitized_data['powerball']}")
            return None

    # Validate score_total
    if 'score_total' in sanitized_data:
        try:
            score = float(sanitized_data['score_total'])
            if score < 0 or score > 1:
                logger.warning(f"Score {score} is outside typical range 0-1")
            sanitized_data['score_total'] = score
        except (ValueError, TypeError):
            logger.error(f"Invalid score format: {sanitized_data['score_total']}")
            return None

    # Validate model_version
    if 'model_version' not in sanitized_data or not sanitized_data['model_version']:
        sanitized_data['model_version'] = '1.0.0-pipeline'

    # Validate dataset_hash
    if 'dataset_hash' not in sanitized_data or not sanitized_data['dataset_hash']:
        import hashlib
        timestamp_str = str(sanitized_data.get('timestamp', datetime.now().isoformat()))
        default_hash = hashlib.md5(timestamp_str.encode()).hexdigest()[:16]
        sanitized_data['dataset_hash'] = default_hash

    return sanitized_data


# ===============================================
# USER AUTHENTICATION & PREMIUM ACCESS FUNCTIONS
# ===============================================

# Password hashing moved to api_auth_endpoints.py using bcrypt
# These functions are kept for backwards compatibility but deprecated

def hash_password(password: str) -> str:
    """
    Hash password using SHA-256 with salt.
    DEPRECATED: Use bcrypt from api_auth_endpoints.py instead.
    Kept for backwards compatibility only.
    """
    salt = "powerball_shiol_2024"  # Static salt for backward compatibility
    return hashlib.sha256((password + salt).encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """
    Verify password against SHA-256 hash.
    DEPRECATED: Use bcrypt verification from api_auth_endpoints.py instead.
    Kept for backwards compatibility with legacy users only.
    """
    return hash_password(password) == hashed


def create_user(email: str, username: str, password_or_hash: str) -> Optional[int]:
    """Create a new user account.
    Args:
        password_or_hash: Either a plain password (legacy) or a bcrypt hash (new)
    """
    try:
        # Detect if input is already a bcrypt hash (starts with $2a$, $2b$, or $2y$)
        if password_or_hash.startswith(("$2a$", "$2b$", "$2y$")):
            password_hash = password_or_hash  # Store bcrypt hash verbatim
        else:
            # Legacy: if it's a plain password, hash it with SHA-256
            # Note: New registrations should pass bcrypt hashes, not plain passwords
            password_hash = hash_password(password_or_hash)  # Legacy SHA-256 hash

        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO users (email, username, password_hash)
                VALUES (?, ?, ?)
            """, (email.lower().strip(), username.strip(), password_hash))

            user_id = cursor.lastrowid
            conn.commit()

            logger.info(f"New user created: {username} (ID: {user_id})")
            return user_id

    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed" in str(e):
            logger.warning(f"Duplicate user: {email} / {username}")
            return None
        logger.error(f"Integrity error creating user: {e}")
        raise
    except sqlite3.Error as e:
        logger.error(f"Database error creating user: {e}")
        raise


def authenticate_user(login: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate user by email or username."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Try login as email first, then username
            cursor.execute("""
                SELECT id, email, username, password_hash, is_premium, premium_expires_at, is_active, created_at, login_count, is_admin
                FROM users
                WHERE (email = ? OR username = ?) AND is_active = TRUE
            """, (login.lower().strip(), login.strip()))

            user_data = cursor.fetchone()

            if not user_data:
                return None

            user_id, email, username, stored_hash, is_premium, premium_expires_at, is_active, created_at, login_count, is_admin = user_data

            # Deterministic verification based on hash format
            password_valid = False

            if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
                # Bcrypt hash - use secure verification
                try:
                    from src.api_auth_endpoints import verify_password_secure
                    password_valid = verify_password_secure(password, stored_hash)
                    if password_valid:
                        logger.debug(f"User {login} authenticated with bcrypt hash")
                except Exception as e:
                    logger.error(f"Bcrypt verification failed for {login}: {e}")
            else:
                # Legacy SHA-256 hash - use legacy verification
                password_valid = verify_password(password, stored_hash)
                if password_valid:
                    logger.info(f"User {login} authenticated with legacy hash - consider migration")

            if not password_valid:
                logger.warning(f"Authentication failed: invalid password for {login}")
                return None

            # Update login statistics
            cursor.execute("""
                UPDATE users
                SET last_login = CURRENT_TIMESTAMP, login_count = login_count + 1
                WHERE id = ?
            """, (user_id,))
            conn.commit()

            # Get updated login count
            updated_login_count = login_count + 1

            # Check if premium has expired
            current_premium_status = is_premium
            if is_premium and premium_expires_at:
                try:
                    expiry_date = datetime.fromisoformat(premium_expires_at.replace('Z', '+00:00'))
                    if datetime.now() > expiry_date:
                        current_premium_status = False
                        cursor.execute("""
                            UPDATE users SET is_premium = FALSE WHERE id = ?
                        """, (user_id,))
                        conn.commit()
                except ValueError:
                    pass

            logger.info(f"User authenticated: {username} (Premium: {current_premium_status}, Admin: {bool(is_admin)})")

            return {
                'id': user_id,
                'email': email,
                'username': username,
                'is_premium': current_premium_status,
                'premium_expires_at': premium_expires_at,
                'created_at': created_at,
                'login_count': updated_login_count,
                'is_admin': bool(is_admin) if is_admin is not None else False
            }

    except sqlite3.Error as e:
        logger.error(f"Database error during authentication: {e}")
        return None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user information by ID."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, email, username, is_premium, premium_expires_at, created_at, last_login, login_count, is_admin
                FROM users
                WHERE id = ? AND is_active = TRUE
            """, (user_id,))

            user_data = cursor.fetchone()

            if not user_data:
                return None

            user_id, email, username, is_premium, premium_expires_at, created_at, last_login, login_count, is_admin = user_data

            return {
                'id': user_id,
                'email': email,
                'username': username,
                'is_premium': is_premium,
                'premium_expires_at': premium_expires_at,
                'created_at': created_at,
                'last_login': last_login,
                'login_count': login_count,
                'is_admin': bool(is_admin) if is_admin is not None else False
            }

    except sqlite3.Error as e:
        logger.error(f"Database error getting user: {e}")
        return None


def upgrade_user_to_premium(user_id: int, expiry_date: datetime) -> bool:
    """Upgrade user to premium access."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE users
                SET is_premium = TRUE, premium_expires_at = ?
                WHERE id = ? AND is_active = TRUE
            """, (expiry_date.isoformat(), user_id))

            if cursor.rowcount > 0:
                conn.commit()
                logger.info(f"User {user_id} upgraded to premium until {expiry_date}")
                return True
            else:
                logger.warning(f"User {user_id} not found for premium upgrade")
                return False

    except sqlite3.Error as e:
        logger.error(f"Database error upgrading user to premium: {e}")
        return False


def get_user_stats() -> Dict[str, int]:
    """Get platform statistics for user counts."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Total users
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
            total_users = cursor.fetchone()[0]

            # Premium users
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE is_premium = TRUE AND is_active = TRUE
                AND (premium_expires_at IS NULL OR premium_expires_at > CURRENT_TIMESTAMP)
            """)
            premium_users = cursor.fetchone()[0]

            # Users created in last 30 days
            cursor.execute("""
                SELECT COUNT(*) FROM users
                WHERE is_active = TRUE
                AND created_at > datetime('now', '-30 days')
            """)
            new_users = cursor.fetchone()[0]

            return {
                'total_users': total_users,
                'premium_users': premium_users,
                'new_users_30d': new_users,
                'free_users': total_users - premium_users
            }

    except sqlite3.Error as e:
        logger.error(f"Database error getting user stats: {e}")
        return {
            'total_users': 0,
            'premium_users': 0,
            'new_users_30d': 0,
            'free_users': 0
        }


def update_user_password(user_id: int, new_password_hash: str) -> bool:
    """Update user password with bcrypt hash.

    Args:
        user_id: User ID
        new_password_hash: New bcrypt password hash

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE users
                SET password_hash = ?
                WHERE id = ?
            """, (new_password_hash, user_id))

            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"Password updated for user ID: {user_id}")
                return True
            else:
                logger.warning(f"User not found for password update: {user_id}")
                return False

    except sqlite3.Error as e:
        logger.error(f"Database error updating password: {e}")
        return False


def update_user_email(user_id: int, new_email: str) -> bool:
    """Update user email address.

    Args:
        user_id: User ID
        new_email: New email address

    Returns:
        True if successful, False if email already exists or error
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Check if email already exists
            cursor.execute("""
                SELECT id FROM users WHERE email = ? AND id != ?
            """, (new_email.lower().strip(), user_id))

            if cursor.fetchone():
                logger.warning(f"Email already exists: {new_email}")
                return False

            # Update email
            cursor.execute("""
                UPDATE users
                SET email = ?
                WHERE id = ?
            """, (new_email.lower().strip(), user_id))

            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"Email updated for user ID: {user_id}")
                return True
            else:
                logger.warning(f"User not found for email update: {user_id}")
                return False

    except sqlite3.IntegrityError as e:
        logger.error(f"Email uniqueness constraint violated: {e}")
        return False
    except sqlite3.Error as e:
        logger.error(f"Database error updating email: {e}")
        return False


def delete_user_account(user_id: int) -> bool:
    """Delete user account and all associated data.

    Cascades deletion to:
    - predictions table
    - premium_passes table
    - Any other user-related data

    Args:
        user_id: User ID

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # First verify user exists
            cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
            if not cursor.fetchone():
                logger.warning(f"User not found for deletion: {user_id}")
                return False

            # Delete related data first (optional tables)
            try:
                cursor.execute("DELETE FROM predictions WHERE user_id = ?", (user_id,))
                deleted_predictions = cursor.rowcount
                logger.info(f"Deleted {deleted_predictions} predictions for user {user_id}")
            except sqlite3.OperationalError:
                # Table may not exist in current schema; skip safely
                logger.info("predictions table doesn't exist, skipping")

            # Delete premium passes if table exists
            try:
                cursor.execute("DELETE FROM premium_passes WHERE user_id = ?", (user_id,))
                deleted_passes = cursor.rowcount
                logger.info(f"Deleted {deleted_passes} premium passes for user {user_id}")
            except sqlite3.OperationalError:
                # Table doesn't exist, skip
                logger.info("premium_passes table doesn't exist, skipping")

            # Delete user
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted_users = cursor.rowcount

            conn.commit()

            if deleted_users > 0:
                logger.info(f"User account deleted successfully: {user_id}")
                return True
            else:
                logger.error(f"Failed to delete user: {user_id}")
                return False

    except sqlite3.Error as e:
        logger.error(f"Database error deleting user account: {e}")
        return False


def get_all_users():
    """
    Returns a list of all users with basic info for admin management.
    Output: [{id, username, email, is_admin, premium_until, created_at}, ...]
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, is_admin, premium_expires_at as premium_until, created_at FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
        users = [dict(zip(["id", "username", "email", "is_admin", "premium_until", "created_at"], row)) for row in rows]
    return users


def get_user_by_id_admin(user_id: int):
    """
    Returns user dict for given user_id, or None if not found.
    Admin version with limited fields for user management.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, is_admin, is_premium, premium_expires_at as premium_until, created_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return dict(zip(["id", "username", "email", "is_admin", "is_premium", "premium_until", "created_at"], row))
        return None


def update_user_password_hash(user_id: int, new_hash: str) -> bool:
    """
    Updates password hash for user. Returns True if successful.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        conn.commit()
        return cursor.rowcount > 0


def toggle_user_premium(user_id: int) -> str:
    """
    Toggles premium status for user. If not premium, assigns 30 days. If premium, removes.
    Returns new status: 'active' or 'inactive'.
    """
    from datetime import datetime, timedelta
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT premium_expires_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        now = datetime.utcnow()
        if row and row[0]:
            # Remove premium
            cursor.execute("UPDATE users SET premium_expires_at = NULL, is_premium = 0 WHERE id = ?", (user_id,))
            conn.commit()
            return 'inactive'
        else:
            # Assign 1 year from activation date
            premium_until = (now + timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("UPDATE users SET premium_expires_at = ?, is_premium = 1 WHERE id = ?", (premium_until, user_id))
            conn.commit()
            return 'active'


# ============================================================
# PIPELINE EXECUTION LOGS FUNCTIONS
# ============================================================

def insert_pipeline_execution_log(execution_id: str, start_time: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
    """
    Insert a new pipeline execution log with 'running' status.

    Args:
        execution_id: Unique execution identifier (8-char hex)
        start_time: Start timestamp in ISO format
        metadata: Optional dictionary with execution metadata (converted to JSON)

    Returns:
        bool: True if inserted successfully
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            metadata_json = json.dumps(metadata, cls=NumpyEncoder) if metadata else None
            cursor.execute(
                """
                INSERT INTO pipeline_execution_logs
                (execution_id, start_time, status, current_step, steps_completed, metadata)
                VALUES (?, ?, 'running', NULL, 0, ?)
                """,
                (execution_id, start_time, metadata_json)
            )
            conn.commit()
            logger.debug(f"Pipeline log inserted: {execution_id}")
            return True
    except sqlite3.Error as e:
        logger.error(f"Failed to insert pipeline execution log: {e}")
        return False


def update_pipeline_execution_log(
    execution_id: str,
    status: Optional[str] = None,
    current_step: Optional[str] = None,
    steps_completed: Optional[int] = None,
    total_steps: Optional[int] = None,
    end_time: Optional[str] = None,
    error: Optional[str] = None,
    total_tickets_generated: Optional[int] = None,
    target_draw_date: Optional[str] = None,
    elapsed_seconds: Optional[float] = None,
    metadata: Optional[str] = None,
    data_source: Optional[str] = None
) -> bool:
    """
    Update an existing pipeline execution log.

    Args:
        execution_id: Execution ID to update
        status: New status ('running', 'completed', 'failed', 'timeout')
        current_step: Current step description
        steps_completed: Number of steps completed
        total_steps: Total number of steps in pipeline
        end_time: End timestamp in ISO format
        error: Error message if failed
        total_tickets_generated: Number of tickets generated
        target_draw_date: Target draw date (YYYY-MM-DD)
        elapsed_seconds: Total elapsed time in seconds
        metadata: JSON string with additional metadata
        data_source: Data source used (MUSL_API, NY_STATE_API, CSV, etc.)

    Returns:
        bool: True if updated successfully
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build dynamic UPDATE query
            updates = []
            params = []

            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if current_step is not None:
                updates.append("current_step = ?")
                params.append(current_step)
            if steps_completed is not None:
                updates.append("steps_completed = ?")
                params.append(steps_completed)
            if total_steps is not None:
                updates.append("total_steps = ?")
                params.append(total_steps)
            if end_time is not None:
                updates.append("end_time = ?")
                params.append(end_time)
            if error is not None:
                updates.append("error = ?")
                params.append(error)
            if total_tickets_generated is not None:
                updates.append("total_tickets_generated = ?")
                params.append(total_tickets_generated)
            if target_draw_date is not None:
                updates.append("target_draw_date = ?")
                params.append(target_draw_date)
            if elapsed_seconds is not None:
                updates.append("elapsed_seconds = ?")
                params.append(elapsed_seconds)
            if metadata is not None:
                updates.append("metadata = ?")
                params.append(metadata)
            if data_source is not None:
                updates.append("data_source = ?")
                params.append(data_source)

            if not updates:
                logger.warning(f"No updates provided for execution {execution_id}")
                return False

            params.append(execution_id)
            query = f"UPDATE pipeline_execution_logs SET {', '.join(updates)} WHERE execution_id = ?"

            cursor.execute(query, params)
            conn.commit()

            if cursor.rowcount > 0:
                logger.debug(f"Pipeline log updated: {execution_id} ({', '.join(updates)})")
                return True
            else:
                logger.warning(f"No pipeline log found with execution_id: {execution_id}")
                return False

    except sqlite3.Error as e:
        logger.error(f"Failed to update pipeline execution log: {e}")
        return False


def get_pipeline_execution_logs(
    limit: int = 20,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve pipeline execution logs with optional filters.

    Args:
        limit: Maximum number of logs to return (default: 20)
        status: Filter by status ('running', 'completed', 'failed', 'timeout')
        start_date: Filter logs after this date (YYYY-MM-DD)
        end_date: Filter logs before this date (YYYY-MM-DD)

    Returns:
        List of log dictionaries sorted by start_time DESC
        Each log includes:
        - execution_id, status, start_time, end_time, steps_completed
        - total_tickets_generated, target_draw_date, elapsed_seconds
        - data_source: From table column (CSV, MUSL_API, SCRAPING, or UNKNOWN)
        - metadata: Full metadata object (parsed from JSON)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM pipeline_execution_logs WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if start_date:
                query += " AND start_time >= ?"
                params.append(start_date)
            if end_date:
                query += " AND start_time <= ?"
                params.append(end_date)

            query += " ORDER BY start_time DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            columns = [desc[0] for desc in cursor.description]
            logs = []
            for row in rows:
                log_dict = dict(zip(columns, row))

                # Parse metadata JSON if exists
                if log_dict.get('metadata'):
                    try:
                        metadata_obj = json.loads(log_dict['metadata'])
                        log_dict['metadata'] = metadata_obj
                    except (json.JSONDecodeError, TypeError, AttributeError) as e:
                        logger.warning(f"Failed to parse metadata JSON for execution {log_dict.get('execution_id')}: {e}")
                        log_dict['metadata'] = None

                # Use data_source from table column directly (already in log_dict)
                # If NULL, fall back to 'UNKNOWN'
                if not log_dict.get('data_source'):
                    log_dict['data_source'] = 'UNKNOWN'

                logs.append(log_dict)

            return logs

    except sqlite3.Error as e:
        logger.error(f"Failed to retrieve pipeline execution logs: {e}")
        return []


def get_pipeline_execution_statistics() -> Dict[str, Any]:
    """
    Get statistics about pipeline executions.

    Returns:
        Dictionary with statistics (total runs, success rate, avg duration, etc.)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Total executions
            cursor.execute("SELECT COUNT(*) FROM pipeline_execution_logs")
            total_runs = cursor.fetchone()[0]

            # Completed vs failed
            cursor.execute("SELECT status, COUNT(*) FROM pipeline_execution_logs GROUP BY status")
            status_counts = dict(cursor.fetchall())

            # Average duration for completed runs
            cursor.execute("""
                SELECT AVG(CAST(elapsed_seconds AS REAL)),
                       MIN(CAST(elapsed_seconds AS REAL)),
                       MAX(CAST(elapsed_seconds AS REAL))
                FROM pipeline_execution_logs
                WHERE status = 'completed' AND elapsed_seconds IS NOT NULL
            """)
            duration_stats = cursor.fetchone() or (None, None, None)

            # Last execution
            cursor.execute("""
                SELECT execution_id, start_time, status, elapsed_seconds
                FROM pipeline_execution_logs
                ORDER BY start_time DESC LIMIT 1
            """)
            last_execution = cursor.fetchone()

            return {
                "total_runs": total_runs,
                "status_breakdown": status_counts,
                "avg_duration_seconds": duration_stats[0] if duration_stats and duration_stats[0] else None,
                "min_duration_seconds": duration_stats[1] if duration_stats and duration_stats[1] else None,
                "max_duration_seconds": duration_stats[2] if duration_stats and duration_stats[2] else None,
                "last_execution": {
                    "execution_id": last_execution[0],
                    "start_time": last_execution[1],
                    "status": last_execution[2],
                    "elapsed_seconds": last_execution[3]
                } if last_execution else None,
                "success_rate": (
                    status_counts.get('completed', 0) / total_runs * 100
                    if total_runs > 0 else 0.0
                )
            }

    except sqlite3.Error as e:
        logger.error(f"Failed to retrieve pipeline execution statistics: {e}")
        # Return valid empty structure instead of empty dict
        return {
            "total_runs": 0,
            "status_breakdown": {},
            "avg_duration_seconds": None,
            "min_duration_seconds": None,
            "max_duration_seconds": None,
            "last_execution": None,
            "success_rate": 0.0
        }


# ============================================================================
# PENDING DRAWS MANAGEMENT (Pipeline v6.1 - 3 Layer Architecture)
# ============================================================================

def insert_pending_draw(draw_date: str) -> bool:
    """
    Insert a new pending draw into the tracking table.

    Args:
        draw_date: The draw date to track (YYYY-MM-DD format)

    Returns:
        True if inserted successfully, False if already exists or error
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO pending_draws (draw_date, status, attempts, created_at)
                VALUES (?, 'pending', 0, datetime('now'))
            """, (draw_date,))
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"📋 Pending draw created: {draw_date}")
                return True
            else:
                logger.debug(f"Pending draw already exists: {draw_date}")
                return False

    except sqlite3.Error as e:
        logger.error(f"Failed to insert pending draw {draw_date}: {e}")
        return False


def get_pending_draws(status: str = 'pending') -> List[Dict[str, Any]]:
    """
    Get all pending draws with the specified status.

    Args:
        status: Filter by status ('pending', 'completed', 'failed_permanent')

    Returns:
        List of pending draw records
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, draw_date, status, attempts, last_attempt_at,
                       created_at, completed_at, completed_by_layer, error_message
                FROM pending_draws
                WHERE status = ?
                ORDER BY draw_date DESC
            """, (status,))

            rows = cursor.fetchall()
            columns = ['id', 'draw_date', 'status', 'attempts', 'last_attempt_at',
                      'created_at', 'completed_at', 'completed_by_layer', 'error_message']

            return [dict(zip(columns, row)) for row in rows]

    except sqlite3.Error as e:
        logger.error(f"Failed to get pending draws: {e}")
        return []


def update_pending_draw(
    draw_date: str,
    status: Optional[str] = None,
    increment_attempts: bool = False,
    completed_by_layer: Optional[int] = None,
    error_message: Optional[str] = None
) -> bool:
    """
    Update a pending draw record.

    Args:
        draw_date: The draw date to update
        status: New status ('pending', 'completed', 'failed_permanent')
        increment_attempts: If True, increment the attempts counter
        completed_by_layer: Which layer completed the draw (1, 2, or 3)
        error_message: Error message if failed

    Returns:
        True if updated successfully, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            updates = ["last_attempt_at = datetime('now')"]
            params = []

            if status:
                updates.append("status = ?")
                params.append(status)

            if increment_attempts:
                updates.append("attempts = attempts + 1")

            if completed_by_layer:
                updates.append("completed_by_layer = ?")
                updates.append("completed_at = datetime('now')")
                params.append(completed_by_layer)

            if error_message:
                updates.append("error_message = ?")
                params.append(error_message)

            params.append(draw_date)

            query = f"UPDATE pending_draws SET {', '.join(updates)} WHERE draw_date = ?"
            cursor.execute(query, params)
            conn.commit()

            if cursor.rowcount > 0:
                logger.debug(f"Updated pending draw {draw_date}: status={status}")
                return True
            return False

    except sqlite3.Error as e:
        logger.error(f"Failed to update pending draw {draw_date}: {e}")
        return False


def mark_pending_draw_completed(draw_date: str, layer: int) -> bool:
    """
    Mark a pending draw as completed by a specific layer.

    Args:
        draw_date: The draw date that was completed
        layer: Which layer completed it (1, 2, or 3)

    Returns:
        True if marked successfully
    """
    return update_pending_draw(
        draw_date=draw_date,
        status='completed',
        completed_by_layer=layer
    )


def mark_pending_draw_failed(draw_date: str, error_message: str) -> bool:
    """
    Mark a pending draw as permanently failed.

    Args:
        draw_date: The draw date that failed
        error_message: Description of why it failed

    Returns:
        True if marked successfully
    """
    return update_pending_draw(
        draw_date=draw_date,
        status='failed_permanent',
        error_message=error_message
    )


def get_pending_draws_count() -> Dict[str, int]:
    """
    Get count of pending draws by status.

    Returns:
        Dict with counts: {'pending': N, 'completed': N, 'failed_permanent': N}
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM pending_draws
                GROUP BY status
            """)

            result = {'pending': 0, 'completed': 0, 'failed_permanent': 0}
            for row in cursor.fetchall():
                result[row[0]] = row[1]

            return result

    except sqlite3.Error as e:
        logger.error(f"Failed to get pending draws count: {e}")
        return {'pending': 0, 'completed': 0, 'failed_permanent': 0}


def cleanup_old_pending_draws(days_to_keep: int = 30) -> int:
    """
    Remove completed pending draws older than specified days.

    Args:
        days_to_keep: Keep records for this many days

    Returns:
        Number of records deleted
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM pending_draws
                WHERE status = 'completed'
                AND completed_at < datetime('now', ?)
            """, (f'-{days_to_keep} days',))
            conn.commit()

            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"🧹 Cleaned up {deleted} old pending draw records")
            return deleted

    except sqlite3.Error as e:
        logger.error(f"Failed to cleanup pending draws: {e}")
        return 0



