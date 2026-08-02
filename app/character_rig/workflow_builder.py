"""Graph builders for the character-rig module.

Unlike the Standard workflow_builder (which patches a hand-exported editor
JSON because that graph is too complex to author by hand), these two graphs
are small and linear enough to build directly as API-format dicts. No
Workflow/*.json template files are needed for this module.

Both graphs were designed against the live node schemas queried from this
machine's ComfyUI (`/object_info/<ClassType>`), not guessed from source —
see docs/character-rig-prep-plan.md §3/§7 for the node inventory.
"""

DEFAULT_NEGATIVE = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
    "fewer digits, cropped, worst quality, low quality, jpeg artifacts, "
    "signature, watermark, blurry"
)


def build_character_base_graph(params: dict, output_prefix: str) -> dict:
    """checkpoint -> CLIP encode (pos/neg) -> empty latent -> KSampler -> VAE decode -> save.

    params: checkpoint, positive_prompt, negative_prompt, seed, width, height.
    """
    seed = int(params["seed"])
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": params["checkpoint"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": params["positive_prompt"], "clip": ["1", 1]}},
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": params.get("negative_prompt") or DEFAULT_NEGATIVE, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": int(params["width"]), "height": int(params["height"]), "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                "seed": seed, "steps": 30, "cfg": 5.5,
                "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0,
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": output_prefix}},
    }


def build_human_parts_segment_graph(base_image_filename: str, output_prefix: str) -> dict:
    """Runs HumanPartsUltra once per part (it only returns one combined
    mask for whatever parts are enabled, so isolating each one takes its own
    call), grows+blurs the edge a little, and saves each as a plain
    white-on-black PNG via MaskToImage — the same representation a
    hand-drawn correction produces, so build_part_extract_graph's
    ImageToMask(channel="red") step works identically on either source.

    Each save node is keyed `save_<part_key>` so the caller can look up
    history_entry["outputs"][f"save_{part_key}"] directly by part_key.
    """
    nodes = {"1": {"class_type": "LoadImage", "inputs": {"image": base_image_filename}}}
    for part_key in PART_KEYS:
        flags = {k: (k == part_key) for k in PART_KEYS}
        seg_id, mask_id, img_id, save_id = (
            f"seg_{part_key}", f"mask_{part_key}", f"img_{part_key}", f"save_{part_key}",
        )
        nodes[seg_id] = {
            "class_type": "LayerMask: HumanPartsUltra",
            "inputs": {
                "image": ["1", 0],
                **flags,
                "detail_method": "VITMatte", "detail_erode": 8, "detail_dilate": 6,
                "black_point": 0.01, "white_point": 0.99,
                "process_detail": True, "device": "cuda", "max_megapixels": 2.0,
            },
        }
        nodes[mask_id] = {
            "class_type": "LayerMask: MaskGrow",
            "inputs": {"mask": [seg_id, 1], "invert_mask": False, "grow": 2, "blur": 2},
        }
        nodes[img_id] = {"class_type": "MaskToImage", "inputs": {"mask": [mask_id, 0]}}
        nodes[save_id] = {
            "class_type": "SaveImage",
            "inputs": {"images": [img_id, 0], "filename_prefix": f"{output_prefix}/{part_key}"},
        }
    return nodes


PART_KEYS = [
    "face", "hair", "glasses", "top_clothes", "bottom_clothes", "torso_skin",
    "left_arm", "right_arm", "left_leg", "right_leg", "left_foot", "right_foot",
]

PART_DISPLAY_NAMES = {
    "face": "Rostro", "hair": "Pelo (sin separar)", "glasses": "Lentes",
    "top_clothes": "Ropa superior", "bottom_clothes": "Ropa inferior",
    "torso_skin": "Torso / piel", "left_arm": "Brazo izquierdo", "right_arm": "Brazo derecho",
    "left_leg": "Pierna izquierda", "right_leg": "Pierna derecha",
    "left_foot": "Pie izquierdo", "right_foot": "Pie derecho",
}


def build_part_extract_graph(base_image_filename: str, mask_image_filename: str, output_prefix: str) -> dict:
    """Fase 3 (simple crop, no occlusion fill — see plan §1): loads the base
    image and a hand/auto-drawn mask (white strokes on black), derives a MASK
    from its red channel, softens the edge a little, and saves the base image
    with that mask as alpha. No inpainting — the occluded-region fill is
    Fase 3b, deliberately deferred.

    SaveImageWithAlpha (KJNodes) computes alpha as `1 - mask` — it expects the
    "inpaint" convention where mask=1 means *hole*. Our part masks use the
    opposite convention (1 = keep this part), so the mask is inverted with a
    plain InvertMask right before the save, or every extracted layer comes
    out with the part transparent and everything else opaque (verified by
    generating an actual layer during Fase 0-3 testing — see plan history)."""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": base_image_filename}},
        "2": {"class_type": "LoadImage", "inputs": {"image": mask_image_filename}},
        "3": {"class_type": "ImageToMask", "inputs": {"image": ["2", 0], "channel": "red"}},
        "4": {
            "class_type": "LayerMask: MaskGrow",
            "inputs": {"mask": ["3", 0], "invert_mask": False, "grow": 0, "blur": 3},
        },
        "4b": {"class_type": "InvertMask", "inputs": {"mask": ["4", 0]}},
        "5": {
            "class_type": "SaveImageWithAlpha",
            "inputs": {"images": ["1", 0], "mask": ["4b", 0], "filename_prefix": output_prefix},
        },
    }


def build_part_extract_occluded_graph(
    base_image_filename: str,
    part_mask_filename: str,
    occluder_mask_filenames: list[str],
    checkpoint: str,
    positive_prompt: str,
    output_prefix: str,
    seed: int,
) -> dict:
    """Fase 3b: same as build_part_extract_graph, but the region of this
    part's mask that falls under a higher-stacked part (an "occluder") gets
    inpainted instead of left as a transparent hole — see plan §1.

    occluder_mask_filenames: masks (white-on-black PNGs, same convention as
    part_mask_filename) of every OTHER layer whose order_index is higher
    than this one's, i.e. whatever the caller determined actually sits in
    front of this part. Empty list means nothing occludes it — the caller
    should use build_part_extract_graph instead in that case, this function
    doesn't special-case it (a KSampler pass over an all-zero mask is wasted
    GPU work for no benefit).
    """
    nodes = {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "base": {"class_type": "LoadImage", "inputs": {"image": base_image_filename}},
        "part_img": {"class_type": "LoadImage", "inputs": {"image": part_mask_filename}},
        "part_mask": {"class_type": "ImageToMask", "inputs": {"image": ["part_img", 0], "channel": "red"}},
    }

    # Union every occluder's mask into one (chained pairwise "or" — order
    # among themselves doesn't matter, only their combined coverage does).
    union_ref = None
    for i, filename in enumerate(occluder_mask_filenames):
        img_id, mask_id = f"occ_img_{i}", f"occ_mask_{i}"
        nodes[img_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        nodes[mask_id] = {"class_type": "ImageToMask", "inputs": {"image": [img_id, 0], "channel": "red"}}
        if union_ref is None:
            union_ref = [mask_id, 0]
        else:
            or_id = f"occ_union_{i}"
            nodes[or_id] = {
                "class_type": "MaskComposite",
                "inputs": {"destination": union_ref, "source": [mask_id, 0], "x": 0, "y": 0, "operation": "or"},
            }
            union_ref = [or_id, 0]

    nodes["occluded_mask"] = {
        "class_type": "MaskComposite",
        "inputs": {"destination": ["part_mask", 0], "source": union_ref, "x": 0, "y": 0, "operation": "and"},
    }
    nodes["visible_mask"] = {
        "class_type": "MaskComposite",
        "inputs": {
            "destination": ["part_mask", 0], "source": ["occluded_mask", 0], "x": 0, "y": 0, "operation": "subtract",
        },
    }

    nodes.update({
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"text": positive_prompt, "clip": ["ckpt", 1]}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"text": DEFAULT_NEGATIVE, "clip": ["ckpt", 1]}},
        "inpaint_latent": {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {
                "pixels": ["base", 0], "vae": ["ckpt", 2], "mask": ["occluded_mask", 0], "grow_mask_by": 8,
            },
        },
        "sampled": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["ckpt", 0], "positive": ["pos", 0], "negative": ["neg", 0],
                "latent_image": ["inpaint_latent", 0], "seed": seed, "steps": 30, "cfg": 5.5,
                "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 0.85,
            },
        },
        "inpainted_image": {"class_type": "VAEDecode", "inputs": {"samples": ["sampled", 0], "vae": ["ckpt", 2]}},
        # Wherever visible_mask=1, keep the *original* pixels untouched (denoise=0
        # in spirit) instead of whatever the sampler produced there too — the
        # inpaint pass runs over the whole image but only its occluded-region
        # output is ever used, exactly per plan §1's "visible region must not
        # be regenerated" rule.
        "composited": {
            "class_type": "ImageCompositeMasked",
            "inputs": {
                "destination": ["inpainted_image", 0], "source": ["base", 0],
                "x": 0, "y": 0, "resize_source": False, "mask": ["visible_mask", 0],
            },
        },
        "alpha_mask": {
            "class_type": "LayerMask: MaskGrow",
            "inputs": {"mask": ["part_mask", 0], "invert_mask": False, "grow": 0, "blur": 3},
        },
        "alpha_inverted": {"class_type": "InvertMask", "inputs": {"mask": ["alpha_mask", 0]}},
        "save": {
            "class_type": "SaveImageWithAlpha",
            "inputs": {
                "images": ["composited", 0], "mask": ["alpha_inverted", 0], "filename_prefix": output_prefix,
            },
        },
    })
    return nodes
