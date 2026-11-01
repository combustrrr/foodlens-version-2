"""FoodLens Flask application.

Routes:
  GET  /           -> responsive web UI
  POST /api/predict -> image upload -> {top3, ingredients, warnings}
  GET  /api/classes -> 101-class list
  GET  /api/health  -> heartbeat
"""
import io
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_compress import Compress
from PIL import Image, UnidentifiedImageError

# Add webapp directory to path for imports
webapp_dir = Path(__file__).resolve().parent
if str(webapp_dir) not in sys.path:
    sys.path.insert(0, str(webapp_dir))

# Import FoodLensModel from the same directory
from inference import FoodLensModel

app = Flask(
    __name__,
    static_folder=str(Path(__file__).resolve().parent / "static"),
    template_folder=str(Path(__file__).resolve().parent / "templates"),
)
app.config.update(
    COMPRESS_MIMETYPES=[
        "application/json",
        "application/javascript",
        "image/svg+xml",
        "text/css",
        "text/html",
        "text/javascript",
    ],
    COMPRESS_MIN_SIZE=500,
)
Compress(app)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "foodlens-dev-key-change-in-production")
app.config["UPLOAD_FOLDER"] = Path(__file__).resolve().parent / "uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
FEEDBACK_PATH = Path(os.environ.get("FEEDBACK_PATH", webapp_dir / "feedback" / "feedback.jsonl"))
EVALUATION_PATH = webapp_dir / "data" / "evaluation_summary.json"
feedback_lock = threading.Lock()

# Ensure upload folder exists
app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load model once at startup
lens = FoodLensModel()

@app.after_request
def add_cors_headers(response):
    allowed_origin = os.environ.get("CORS_ALLOWED_ORIGIN")
    if allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = allowed_origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "img-src 'self' blob: data:; "
        "media-src 'self' blob:; "
        "object-src 'none'; "
        "script-src 'self'; "
        "script-src-attr 'none'; "
        "style-src 'self'; "
        "style-src-attr 'unsafe-inline';"
    )
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    if request.is_secure or forwarded_proto == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response



@app.get("/")
def index():
    return send_from_directory(str(app.template_folder), "index.html")


@app.get("/v2")
@app.get("/v2/")
def index_v2():
    return send_from_directory(str(app.template_folder), "v2.html")


@app.get("/about")
def about():
    return send_from_directory(str(app.template_folder), "index.html")


@app.get("/history")
def history():
    return send_from_directory(str(app.template_folder), "index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "model_ready": lens.ready,
        "model": lens.model_name,
        "classes": lens.class_count,
    })


@app.get("/api/model")
def model_metadata():
    return jsonify(lens.metadata())


@app.get("/api/evaluation")
def evaluation():
    return jsonify(json.loads(EVALUATION_PATH.read_text(encoding="utf-8")))


@app.get("/api/classes")
def classes():
    return jsonify(lens.class_map)


@app.post("/api/feedback")
def feedback():
    payload = request.form if request.files else (request.get_json(silent=True) or {})
    known_classes = set(lens.class_map["index_to_name"].values())
    predicted = str(payload.get("predicted_class", "")).strip()
    corrected = str(payload.get("corrected_class", "")).strip()
    if predicted not in known_classes or corrected not in known_classes:
        return jsonify({"status": "error", "message": "Feedback labels must be valid Food-101 classes."}), 400
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0))))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Confidence must be numeric."}), 400
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "predicted_class": predicted,
        "corrected_class": corrected,
        "confidence": round(confidence, 4),
        "confirmed": predicted == corrected,
        "model_version": lens.model_version,
        "source": "automated_smoke" if payload.get("source") == "automated_smoke" else "user",
        "image_path": None,
    }
    image = request.files.get("image")
    if image:
        if image.mimetype not in ALLOWED_IMAGE_TYPES:
            return jsonify({"status": "error", "message": "Training photo must be JPEG, PNG, or WebP."}), 415
        raw = image.read()
        try:
            decoded = Image.open(io.BytesIO(raw)).convert("RGB")
        except (UnidentifiedImageError, OSError):
            return jsonify({"status": "error", "message": "Training photo could not be decoded."}), 400
        image_dir = FEEDBACK_PATH.parent / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_name = f"{uuid.uuid4().hex}.jpg"
        decoded.save(image_dir / image_name, format="JPEG", quality=92)
        record["image_path"] = f"images/{image_name}"
    with feedback_lock:
        with FEEDBACK_PATH.open("a", encoding="utf-8") as feedback_file:
            feedback_file.write(json.dumps(record, separators=(",", ":")) + "\n")
    message = "Correction and opted-in photo saved for a future training review." if image else "Correction saved; the photo was not stored."
    return jsonify({"status": "ok", "message": message}), 201


@app.get("/api/feedback/stats")
def feedback_stats():
    if not FEEDBACK_PATH.exists():
        return jsonify({"count": 0})
    with feedback_lock:
        count = sum(1 for line in FEEDBACK_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
    return jsonify({"count": count})


@app.post("/api/predict")
def predict():
    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image provided"}), 400
    upload = request.files["image"]
    if upload.mimetype not in ALLOWED_IMAGE_TYPES:
        return jsonify({
            "status": "error",
            "message": "Unsupported image type. Use JPEG, PNG, or WebP.",
        }), 415
    raw = upload.read()
    if len(raw) == 0:
        return jsonify({"status": "error", "message": "Empty image"}), 400
    try:
        use_tta = request.form.get("tta", "true").lower() not in {"false", "0", "off"}
        threshold = float(request.form.get("threshold", "0.45"))
        return jsonify(lens.predict_bytes(raw, use_tta=use_tta, confidence_threshold=threshold))
    except (UnidentifiedImageError, OSError, ValueError):
        return jsonify({
            "status": "error",
            "message": "The uploaded file could not be decoded as an image.",
        }), 400


@app.post("/api/explain")
def explain():
    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image provided"}), 400
    upload = request.files["image"]
    if upload.mimetype not in ALLOWED_IMAGE_TYPES:
        return jsonify({"status": "error", "message": "Unsupported image type."}), 415
    try:
        return jsonify(lens.gradcam_bytes(upload.read(), request.form.get("class") or None))
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@app.post("/api/compare-tta")
def compare_tta():
    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image provided"}), 400
    raw = request.files["image"].read()
    try:
        single = lens.predict_bytes(raw, use_tta=False)
        ensemble = lens.predict_bytes(raw, use_tta=True)
        return jsonify({
            "status": "ok",
            "single": {"top": single["top"], "uncertainty": single["uncertainty"], "latency_ms": single["inference"]["latency_ms"]},
            "ensemble": {"top": ensemble["top"], "uncertainty": ensemble["uncertainty"], "latency_ms": ensemble["inference"]["latency_ms"]},
        })
    except (UnidentifiedImageError, OSError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400


@app.errorhandler(413)
def image_too_large(_error):
    return jsonify({
        "status": "error",
        "message": "Image is too large. Maximum size is 16 MB.",
    }), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
