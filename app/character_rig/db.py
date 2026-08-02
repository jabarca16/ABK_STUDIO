import json

from .. import db as core_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS character_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    art_style TEXT,
    description TEXT,
    pose TEXT,
    palette_hex TEXT,
    checkpoint TEXT,
    seed INTEGER,
    base_image_path TEXT,
    base_prompt TEXT,
    base_params_json TEXT,
    status TEXT NOT NULL DEFAULT 'drafting_base'
);

CREATE TABLE IF NOT EXISTS character_base_iterations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES character_projects(id),
    created_at TEXT NOT NULL,
    prompt_id TEXT,
    seed INTEGER,
    image_path TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
);

CREATE TABLE IF NOT EXISTS character_layers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES character_projects(id),
    part_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    mask_path TEXT,
    image_path TEXT,
    status TEXT NOT NULL DEFAULT 'pendiente',
    prompt_id TEXT,
    job_status TEXT
);
"""


def init_db():
    with core_db.get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- projects ----------

def create_project(row: dict):
    with core_db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO character_projects (
                id, name, created_at, art_style, description, pose,
                palette_hex, checkpoint, seed, status
            ) VALUES (
                :id, :name, datetime('now'), :art_style, :description, :pose,
                :palette_hex, :checkpoint, :seed, 'drafting_base'
            )
            """,
            row,
        )


def get_project(project_id: str) -> dict | None:
    with core_db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM character_projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None


def list_projects() -> list[dict]:
    with core_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM character_projects ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def approve_base(project_id: str, image_path: str, seed: int, params: dict):
    with core_db.get_conn() as conn:
        conn.execute(
            """
            UPDATE character_projects
            SET base_image_path = ?, seed = ?, base_params_json = ?, status = 'separating_layers'
            WHERE id = ?
            """,
            (image_path, seed, json.dumps(params), project_id),
        )


# ---------- base iterations ----------

def insert_base_iteration(row: dict):
    with core_db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO character_base_iterations (
                id, project_id, created_at, prompt_id, seed, status
            ) VALUES (
                :id, :project_id, datetime('now'), :prompt_id, :seed, :status
            )
            """,
            row,
        )


def update_base_iteration(iteration_id: str, status: str, image_path: str | None = None):
    with core_db.get_conn() as conn:
        if image_path is not None:
            conn.execute(
                "UPDATE character_base_iterations SET status = ?, image_path = ? WHERE id = ?",
                (status, image_path, iteration_id),
            )
        else:
            conn.execute(
                "UPDATE character_base_iterations SET status = ? WHERE id = ?",
                (status, iteration_id),
            )


def get_base_iteration(iteration_id: str) -> dict | None:
    with core_db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM character_base_iterations WHERE id = ?", (iteration_id,)
        ).fetchone()
        return dict(row) if row else None


def list_base_iterations(project_id: str) -> list[dict]:
    with core_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM character_base_iterations WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- layers ----------

def create_layer(row: dict):
    with core_db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO character_layers (
                id, project_id, part_key, display_name, order_index, status
            ) VALUES (
                :id, :project_id, :part_key, :display_name, :order_index, :status
            )
            """,
            row,
        )


def list_layers(project_id: str) -> list[dict]:
    with core_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM character_layers WHERE project_id = ? ORDER BY order_index ASC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_layer(layer_id: str) -> dict | None:
    with core_db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM character_layers WHERE id = ?", (layer_id,)
        ).fetchone()
        return dict(row) if row else None


def update_layer_mask(layer_id: str, mask_path: str):
    """User-drawn/corrected mask, uploaded through the mask editor."""
    with core_db.get_conn() as conn:
        conn.execute(
            "UPDATE character_layers SET mask_path = ?, status = 'trazada' WHERE id = ?",
            (mask_path, layer_id),
        )


def set_layer_proposed_mask(layer_id: str, mask_path: str):
    """Auto-segmented mask from Human Parts Ultra — a starting point, not yet
    reviewed by the user (see plan §3/§8 on the 'propuesta' state)."""
    with core_db.get_conn() as conn:
        conn.execute(
            "UPDATE character_layers SET mask_path = ?, status = 'propuesta' WHERE id = ?",
            (mask_path, layer_id),
        )


def reset_layer_for_resegment(layer_id: str):
    """Back to 'pendiente' with no mask — used when re-approving a base image
    (retry after a ComfyUI-side segmentation error) reuses the same layer row
    instead of creating a duplicate."""
    with core_db.get_conn() as conn:
        conn.execute(
            "UPDATE character_layers SET status = 'pendiente', mask_path = NULL, "
            "image_path = NULL, job_status = NULL WHERE id = ?",
            (layer_id,),
        )


def update_layer_job(layer_id: str, prompt_id: str, job_status: str):
    with core_db.get_conn() as conn:
        conn.execute(
            "UPDATE character_layers SET prompt_id = ?, job_status = ? WHERE id = ?",
            (prompt_id, job_status, layer_id),
        )


def update_layer_result(layer_id: str, job_status: str, image_path: str | None = None):
    with core_db.get_conn() as conn:
        if image_path is not None:
            conn.execute(
                "UPDATE character_layers SET job_status = ?, status = 'generada', image_path = ? WHERE id = ?",
                (job_status, image_path, layer_id),
            )
        else:
            conn.execute(
                "UPDATE character_layers SET job_status = ? WHERE id = ?",
                (job_status, layer_id),
            )


def patch_layer(layer_id: str, display_name: str | None, order_index: int | None):
    with core_db.get_conn() as conn:
        if display_name is not None:
            conn.execute(
                "UPDATE character_layers SET display_name = ? WHERE id = ?",
                (display_name, layer_id),
            )
        if order_index is not None:
            conn.execute(
                "UPDATE character_layers SET order_index = ? WHERE id = ?",
                (order_index, layer_id),
            )


def delete_layer(layer_id: str):
    with core_db.get_conn() as conn:
        conn.execute("DELETE FROM character_layers WHERE id = ?", (layer_id,))
