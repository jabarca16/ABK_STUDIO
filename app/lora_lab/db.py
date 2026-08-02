from .. import db as core_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS lora_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    trigger_word TEXT NOT NULL,
    checkpoint TEXT,
    preset TEXT,
    status TEXT NOT NULL DEFAULT 'dataset',
    image_count INTEGER NOT NULL DEFAULT 0,
    total_steps INTEGER,
    current_step INTEGER NOT NULL DEFAULT 0,
    current_epoch INTEGER NOT NULL DEFAULT 0,
    total_epochs INTEGER,
    loss REAL,
    log_tail TEXT,
    pid INTEGER,
    output_path TEXT,
    error_message TEXT
);
"""


def init_db():
    with core_db.get_conn() as conn:
        conn.executescript(SCHEMA)


def create_job(row: dict):
    with core_db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO lora_jobs (id, name, created_at, trigger_word, checkpoint, status)
            VALUES (:id, :name, datetime('now'), :trigger_word, :checkpoint, 'dataset')
            """,
            row,
        )


def get_job(job_id: str) -> dict | None:
    with core_db.get_conn() as conn:
        row = conn.execute("SELECT * FROM lora_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs() -> list[dict]:
    with core_db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM lora_jobs ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def set_image_count(job_id: str, count: int):
    with core_db.get_conn() as conn:
        conn.execute("UPDATE lora_jobs SET image_count = ? WHERE id = ?", (count, job_id))


def set_status(job_id: str, status: str):
    with core_db.get_conn() as conn:
        conn.execute("UPDATE lora_jobs SET status = ? WHERE id = ?", (status, job_id))


def start_training(job_id: str, preset: str, checkpoint: str, total_steps: int, total_epochs: int, pid: int):
    with core_db.get_conn() as conn:
        conn.execute(
            """
            UPDATE lora_jobs
            SET status = 'training', preset = ?, checkpoint = ?, total_steps = ?,
                total_epochs = ?, pid = ?, current_step = 0, current_epoch = 0,
                loss = NULL, error_message = NULL
            WHERE id = ?
            """,
            (preset, checkpoint, total_steps, total_epochs, pid, job_id),
        )


def update_progress(job_id: str, current_step: int | None, current_epoch: int | None, loss: float | None, log_tail: str):
    with core_db.get_conn() as conn:
        conn.execute(
            """
            UPDATE lora_jobs
            SET current_step = COALESCE(?, current_step),
                current_epoch = COALESCE(?, current_epoch),
                loss = COALESCE(?, loss),
                log_tail = ?
            WHERE id = ?
            """,
            (current_step, current_epoch, loss, log_tail, job_id),
        )


def finish_job(job_id: str, status: str, output_path: str | None = None, error_message: str | None = None):
    with core_db.get_conn() as conn:
        conn.execute(
            "UPDATE lora_jobs SET status = ?, output_path = ?, error_message = ?, pid = NULL WHERE id = ?",
            (status, output_path, error_message, job_id),
        )


def delete_job(job_id: str):
    with core_db.get_conn() as conn:
        conn.execute("DELETE FROM lora_jobs WHERE id = ?", (job_id,))
