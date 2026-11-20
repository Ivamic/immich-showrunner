# SPDX-License-Identifier: AGPL-3.0-or-later
"""Make src/showrunner/slideshow/prompts.json: CLIP embeddings of the words slideshows compare
photos with (a screenshot, a document… against people, a beach…).

The app has only the image half of CLIP; the text half is needed once, here. OpenCV 4 reads the
text model but gives the same vector for every text, so ONNX Runtime runs it, in a container
without a network (ONNX Runtime sends telemetry to Microsoft unless told not to). The text model
and its tokenizer come from the same revision as the image model (`showrunner.slideshow.models`):

    B=https://huggingface.co/immich-app/ViT-B-32__laion2b-s34b-b79k/resolve/19a057a0fb927cf239541300e74237cd56c7ffe2/textual
    curl -L -o textual.onnx $B/model.onnx && curl -L -o tokenizer.json $B/tokenizer.json
    docker run --rm -v "$PWD/pkgs:/p" python:3.12-slim \\
        pip install --target /p onnxruntime==1.31.1 tokenizers==0.22.1 numpy
    docker run --rm --network none -e ORT_DISABLE_TELEMETRY=1 -e PYTHONPATH=/p \\
        -v "$PWD/pkgs:/p" -v "$PWD:/m" -v "$PWD/tools:/t" -v "$PWD/src:/s" \\
        python:3.12-slim python /t/clip_prompts.py /m /s
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")  # before onnxruntime is imported

import numpy as np
import onnxruntime  # type: ignore[import-not-found]
from tokenizers import Tokenizer  # type: ignore[import-not-found]

TEXT_MODEL_SHA256 = "48c25be37b352398f2533c9426dab6f9340535e14e46f884cc894236a5060722"
IMAGE_MODEL = "clip-vit-b-32-laion2b@b9ce24b91a8c"
CONTEXT = 77

PROMPTS: dict[str, list[str]] = {
    # Not for a slideshow.
    "junk": [
        "a screenshot of a phone screen",
        "a screenshot of a computer screen",
        "a photo of a document",
        "a scanned page of text",
        "a photo of a receipt",
        "a photo of a whiteboard with notes",
        "a QR code",
        "a meme with text",
        "a slide of a presentation",
        "a photo of a form or a ticket",
    ],
    # What family photos show.
    "photo": [
        "a photo of people",
        "a family photo",
        "a selfie",
        "a photo of a child",
        "a group photo at a party",
        "a landscape photo",
        "a photo of the sea and a beach",
        "a photo of mountains",
        "a photo of a city street",
        "a photo of a building",
        "a photo of a room",
        "a photo of food on a table",
        "a photo of an animal",
        "a photo of flowers and plants",
        "a photo of snow in winter",
        "a photo taken at night",
    ],
}


def main(models: Path, src: Path) -> None:
    text_model = models / "textual.onnx"
    digest = hashlib.sha256(text_model.read_bytes()).hexdigest()
    if digest != TEXT_MODEL_SHA256:
        sys.exit(f"{text_model} is not the text model: sha256 {digest}")
    tokenizer = Tokenizer.from_file(str(models / "tokenizer.json"))
    session = onnxruntime.InferenceSession(str(text_model), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    entries: list[dict[str, str]] = []
    rows: list[np.ndarray] = []
    for group, texts in PROMPTS.items():
        for text in texts:
            # The tokenizer adds the start and end tokens; the rest is 0, as in OpenCLIP.
            ids = tokenizer.encode(text).ids[:CONTEXT]
            tokens = np.zeros((1, CONTEXT), np.int32)
            tokens[0, : len(ids)] = ids
            vector = np.asarray(session.run(None, {name: tokens})[0], dtype=np.float32).reshape(-1)
            vector /= np.linalg.norm(vector)
            rows.append(vector)
            entries.append(
                {
                    "group": group,
                    "text": text,
                    "vector": base64.b64encode(vector.astype("<f2").tobytes()).decode(),
                }
            )
    vectors = np.stack(rows)
    alike = vectors @ vectors.T - np.eye(len(rows))
    if float(alike.max()) > 0.98:
        sys.exit(f"two texts got the same vector (similarity {float(alike.max()):.3f})")
    target = src / "showrunner" / "slideshow" / "prompts.json"
    data = {"model": IMAGE_MODEL, "prompts": entries}
    target.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} prompts to {target}; most alike pair {float(alike.max()):.3f}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
