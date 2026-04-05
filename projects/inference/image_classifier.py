# projects/inference/image_classifier.py
"""
Generic image classification handler.
Works for any CNN model trained on fixed-size images (e.g., skin lesion, X-ray).

Config example:
{
  "handler": "image_classifier",
  "accepted_formats": ["jpg", "jpeg", "png"],
  "description": "Upload a skin lesion image (JPG or PNG, at least 224×224 px).",
  "target_size": [224, 224],
  "normalize_mean": [0.485, 0.456, 0.406],
  "normalize_std":  [0.229, 0.224, 0.225],
  "label_map": {"0": "Benign", "1": "Malignant"},
  "expected_n_features": 150528
}
"""

import numpy as np
import pandas as pd
from .registry import register
from .base import InferenceHandler, InferenceError


@register("image_classifier")
class ImageClassifierHandler(InferenceHandler):

    accepted_extensions = ["jpg", "jpeg", "png", "bmp", "webp"]

    def validate_file(self, file, filename: str) -> None:
        super().validate_file(file, filename)
        if hasattr(file, "size") and file.size > 20 * 1024 * 1024:
            raise InferenceError("Image file too large (max 20 MB).")

    def load_and_preprocess(self, file, filename: str):
        target_size = tuple(self.cfg.get("target_size", [224, 224]))
        img_array   = self.read_image(file, target_size=target_size)

        if img_array.ndim == 2:
            # Greyscale → RGB
            img_array = np.stack([img_array] * 3, axis=-1)
        if img_array.shape[2] == 4:
            # RGBA → RGB
            img_array = img_array[:, :, :3]

        # Normalize
        img_float = img_array.astype(np.float32) / 255.0
        mean = np.array(self.cfg.get("normalize_mean", [0.5, 0.5, 0.5]))
        std  = np.array(self.cfg.get("normalize_std",  [0.5, 0.5, 0.5]))
        img_float = (img_float - mean) / std

        flat        = img_float.flatten().reshape(1, -1)
        feature_df  = pd.DataFrame(flat, columns=[f"px_{i}" for i in range(flat.shape[1])])

        summary = {
            "format":           filename.rsplit(".", 1)[-1].upper(),
            "original_size":    f"{img_array.shape[1]}×{img_array.shape[0]} px",
            "resized_to":       f"{target_size[0]}×{target_size[1]} px",
            "channels":         img_array.shape[2],
            "pixel_range":      "normalised",
        }
        return feature_df, summary
