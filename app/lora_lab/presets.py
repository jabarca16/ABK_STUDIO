"""Training intensity presets — hide sd-scripts' ~40 knobs behind three choices.
Tuned for a 6GB RTX 3050: fp16, gradient checkpointing, batch size 1 always."""

PRESETS = {
    "boceto": {
        "label": "Boceto",
        "description": "Prueba rápida para validar que el dataset y el trigger word funcionan.",
        "epochs": 4,
        "num_repeats": 5,
        "network_dim": 16,
        "network_alpha": 8,
        "learning_rate": 1e-4,
        "resolution": 768,
    },
    "balanceado": {
        "label": "Balanceado",
        "description": "El punto medio recomendado para personajes de anime sobre Illustrious.",
        "epochs": 10,
        "num_repeats": 8,
        "network_dim": 32,
        "network_alpha": 16,
        "learning_rate": 1e-4,
        "resolution": 768,
    },
    "fino": {
        "label": "Fino",
        "description": "Mayor fidelidad de detalles, más tiempo de horno.",
        "epochs": 16,
        "num_repeats": 10,
        "network_dim": 48,
        "network_alpha": 24,
        "learning_rate": 8e-5,
        "resolution": 896,
    },
}


def estimate_steps(preset_key: str, image_count: int) -> int:
    preset = PRESETS[preset_key]
    return preset["epochs"] * max(1, (image_count * preset["num_repeats"]))
