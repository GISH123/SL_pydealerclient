# encoding=utf-8

"""Model output index -> pydealer predict_classid compatibility mapping."""

import xml.dom.minidom as xmldom

MAPPING_LEGACY_IDENTITY = "legacy_identity"
MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC = "numeric_folder_lexicographic"
MAPPING_NUMERIC_FOLDER_NUMBER_ORDER = "numeric_folder_number_order"

# Current/Yolo-style 54-class dataset folder names.
_NUMERIC_FOLDER_NAMES = [str(i) for i in range(53)] + ["99"]

# This matches the existing legacy Training Tool behavior when it sorts
# folder names as strings (e.g. 0, 1, 10, 11, ..., 2, 20, ...).
_NUMERIC_LEXICOGRAPHIC_TO_PREDICT_CLASSID = tuple(
    int(name) for name in sorted(_NUMERIC_FOLDER_NAMES)
)

# Optional future mode if Training Tool changes to sorted(..., key=int).
_NUMERIC_NUMBER_ORDER_TO_PREDICT_CLASSID = tuple(range(53)) + (99,)

SUPPORTED_MAPPING_MODES = {
    MAPPING_LEGACY_IDENTITY,
    MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC,
    MAPPING_NUMERIC_FOLDER_NUMBER_ORDER,
}


def normalize_mapping_mode(mapping_mode, default_mode=MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC):
    """Normalize config text, using the supplied mode when the value is blank."""
    default_mode = str(default_mode or MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC).strip().lower()
    if default_mode not in SUPPORTED_MAPPING_MODES:
        raise ValueError("Invalid default mapping mode: %r" % default_mode)

    mode = str(mapping_mode or "").strip().lower()
    if not mode:
        return default_mode
    if mode not in SUPPORTED_MAPPING_MODES:
        raise ValueError(
            "Unknown model_class_mapping_mode=%r; supported=%s"
            % (mapping_mode, sorted(SUPPORTED_MAPPING_MODES))
        )
    return mode


def default_mapping_mode_for_gametype(gametype):
    """
    Preserve the existing 3-class latency model automatically.
    Normal BAC/DT IV4 defaults to the current 0..52,99 numeric-folder model.
    """
    if str(gametype or "").strip().lower() == "lattest":
        return MAPPING_LEGACY_IDENTITY
    return MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC


def read_mapping_mode_from_config(config_filename, default_mode=MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC):
    """
    Read optional <model_class_mapping_mode> from config.xml.

    An explicit config value always wins. When missing/blank, default_mode is used.
    """
    try:
        xml_file = xmldom.parse(config_filename)
        root = xml_file.documentElement
        nodes = root.getElementsByTagName("model_class_mapping_mode")
        if not nodes or not nodes[0].childNodes:
            return normalize_mapping_mode(None, default_mode)
        text = "".join(
            node.nodeValue
            for node in nodes[0].childNodes
            if node.nodeType == node.TEXT_NODE
        )
        return normalize_mapping_mode(text, default_mode)
    except ValueError:
        raise
    except Exception:
        # config.py already validates the runtime config before Detector starts.
        # Keep the mapping layer robust and use the caller-selected default.
        return normalize_mapping_mode(None, default_mode)


def model_idx_to_predict_classid(model_idx, mapping_mode=None):
    """Convert model output index to the canonical pydealer predict_classid."""
    idx = int(model_idx)
    mode = normalize_mapping_mode(mapping_mode)

    if mode == MAPPING_LEGACY_IDENTITY:
        # Original Jieqi behavior: legacy class folder names were designed so
        # sorted(folder_names) produced class index == predict_classid.
        return idx

    if mode == MAPPING_NUMERIC_FOLDER_LEXICOGRAPHIC:
        mapping = _NUMERIC_LEXICOGRAPHIC_TO_PREDICT_CLASSID
    else:  # MAPPING_NUMERIC_FOLDER_NUMBER_ORDER
        mapping = _NUMERIC_NUMBER_ORDER_TO_PREDICT_CLASSID

    if idx < 0 or idx >= len(mapping):
        raise ValueError("model_idx out of range: %d (mode=%s)" % (idx, mode))

    return mapping[idx]
