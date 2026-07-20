import json
import sqlite3
from contextlib import contextmanager

from . import config, workflow_builder

SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '(root)',
    prompt_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    positive_prompt TEXT,
    negative_prompt TEXT,
    seed INTEGER,
    width INTEGER,
    height INTEGER,
    batch_size INTEGER,
    steps INTEGER,
    cfg REAL,
    sampler TEXT,
    scheduler TEXT,
    checkpoint TEXT,
    loras_json TEXT,
    image_paths_json TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Workflow feature-toggle defaults, matching what's already baked into
# Standard_V37.api.json today (CLIP Skip / Use SAMLoader active, rest bypassed).
FEATURE_TOGGLE_DEFAULTS = {
    "clip_skip": True,
    "use_samloader": True,
    "color_match": False,
    "hiresfix_pre": False,
    "hiresfix_post": False,
    "vpred_model": False,
    "epsilon_scaling": False,
    "cfg_zero_star": False,
    "seperate_vae": False,
    "contrast": False,
    "image_morphology": False,
    "image_quantize": False,
    "image_sharpen": False,
    "detailer": False,
    "hand_adetailer": False,
    "nsfw_adetailer": False,
    "face_adetailer": True,
    "eyes_adetailer": False,
}

# Detector model_name per ADetailer group — installed .pt files vary per
# machine, so these are exposed as dropdowns instead of hardcoded.
ALL_SETTINGS_DEFAULTS = {**FEATURE_TOGGLE_DEFAULTS, **workflow_builder.DETECTOR_MODEL_DEFAULTS}


@contextmanager
def get_conn():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO projects (name, created_at) VALUES ('(root)', datetime('now'))"
        )


def insert_generation(row: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO generations (
                id, created_at, project, prompt_id, status,
                positive_prompt, negative_prompt, seed,
                width, height, batch_size, steps, cfg, sampler, scheduler,
                checkpoint, loras_json, image_paths_json
            ) VALUES (
                :id, datetime('now'), :project, :prompt_id, :status,
                :positive_prompt, :negative_prompt, :seed,
                :width, :height, :batch_size, :steps, :cfg, :sampler, :scheduler,
                :checkpoint, :loras_json, :image_paths_json
            )
            """,
            row,
        )


def update_generation_status(gen_id: str, status: str, image_paths: list[str] | None = None):
    with get_conn() as conn:
        if image_paths is not None:
            conn.execute(
                "UPDATE generations SET status = ?, image_paths_json = ? WHERE id = ?",
                (status, json.dumps(image_paths), gen_id),
            )
        else:
            conn.execute(
                "UPDATE generations SET status = ? WHERE id = ?",
                (status, gen_id),
            )


def get_generation(gen_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM generations WHERE id = ?", (gen_id,)).fetchone()
        return dict(row) if row else None


def get_generation_by_prompt_id(prompt_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM generations WHERE prompt_id = ?", (prompt_id,)
        ).fetchone()
        return dict(row) if row else None


def list_pending_generations() -> list[dict]:
    """Rows still queued/running — used to reconcile against ComfyUI's own
    history when nobody is polling a given generation (tab closed/refreshed)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generations WHERE status IN ('queued', 'running')"
        ).fetchall()
        return [dict(r) for r in rows]


def list_generations(project: str | None, limit: int = 60, offset: int = 0) -> list[dict]:
    with get_conn() as conn:
        if project and project != "__all__":
            rows = conn.execute(
                "SELECT * FROM generations WHERE project = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project, limit, offset),
            ).fetchall()
        else:
            # Group whole projects together (most recently active project first),
            # then order each project's own rows by date. Keeps LIMIT/OFFSET stable
            # across pages since a project's rows never scatter out of sequence.
            rows = conn.execute(
                """
                SELECT g.* FROM generations g
                JOIN (SELECT project, MAX(created_at) AS latest FROM generations GROUP BY project) p
                  ON p.project = g.project
                ORDER BY p.latest DESC, g.project, g.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]


def delete_generation(gen_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM generations WHERE id = ?", (gen_id,))


def list_projects() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM projects ORDER BY created_at ASC").fetchall()
        return [r["name"] for r in rows]


def create_project(name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO projects (name, created_at) VALUES (?, datetime('now'))",
            (name,),
        )


def get_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(ALL_SETTINGS_DEFAULTS)
    for row in rows:
        if row["key"] in settings:
            settings[row["key"]] = json.loads(row["value"])
    return settings


def set_setting(key: str, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
