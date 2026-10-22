"""
ArgusFace Studio - Lightweight Local API Server
Provides high-performance local endpoints for external integrations
(such as the 24/7 Docker Telegram Bot, mobile clients, and webhooks).
"""

import base64
import io
import os
import sys
import threading
import uuid
from datetime import datetime
import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from PIL import Image, ImageOps

# Ensure project root and src are on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
for p in [CURRENT_DIR, PARENT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from src import config
    from src import db
    from src import face_engine
    from src.image_utils import save_image_dedup, imwrite_unicode
except ImportError:
    import config
    import db
    import face_engine
    from image_utils import save_image_dedup, imwrite_unicode

DATA_DIR = os.path.join(PARENT_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
CROPS_DIR = os.path.join(DATA_DIR, "crops")
WEBAPP_DIR = os.path.join(PARENT_DIR, "webapp")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(CROPS_DIR, exist_ok=True)
os.makedirs(WEBAPP_DIR, exist_ok=True)

app = FastAPI(
    title="ArgusFace AI Service API",
    description="Lokalni REST API za biometrijsku usporedbu lica i pretragu baze.",
    version="1.0.0"
)

# CORS middleware for local / docker access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Mini Web App (Single Screen Mobile UI)
app.mount("/webapp", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")

@app.get("/app")
def redirect_to_webapp():
    return RedirectResponse(url="/webapp/")

def verify_api_key(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Validates API key if configured in settings; otherwise permits local requests."""
    api_cfg = config.get_api_config()
    required_key = api_cfg.get("api_key", "").strip()
    if not required_key:
        return True  # No key configured -> open for local network / docker

    token = x_api_key
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        else:
            token = authorization

    if token != required_key:
        raise HTTPException(status_code=401, detail="Nevažeći ili nedostajući API ključ.")
    return True

def decode_image_bytes(raw_bytes: bytes) -> Optional[np.ndarray]:
    """
    Decodes raw byte buffer into an OpenCV BGR numpy array with EXIF orientation correction.
    Essential for mobile camera uploads (iOS/Android) where portrait photos have EXIF rotation tags.
    """
    if not raw_bytes:
        return None
    try:
        pil_img = Image.open(io.BytesIO(raw_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)
        pil_img = pil_img.convert("RGB")
        img_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return img_bgr
    except Exception:
        nparr = np.frombuffer(raw_bytes, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img_bgr

def resolve_stored_image(path: Optional[str]) -> Optional[np.ndarray]:
    """
    Safely resolves and loads an image from disk with path migration fallback
    (e.g., C:\\uniface-app -> C:\\ArgusFace Studio or relative paths).
    """
    if not path or not str(path).strip():
        return None
    raw_path = str(path).strip()
    # 1. Direct path check
    if os.path.exists(raw_path):
        img = cv2.imread(raw_path)
        if img is not None and img.size > 0:
            return img
    # 2. Check filename in CROPS_DIR
    fname = os.path.basename(raw_path)
    c_path = os.path.join(CROPS_DIR, fname)
    if os.path.exists(c_path):
        img = cv2.imread(c_path)
        if img is not None and img.size > 0:
            return img
    # 3. Check filename in UPLOADS_DIR
    u_path = os.path.join(UPLOADS_DIR, fname)
    if os.path.exists(u_path):
        img = cv2.imread(u_path)
        if img is not None and img.size > 0:
            return img
    # 4. Check relative to DATA_DIR
    d_path = os.path.join(DATA_DIR, fname)
    if os.path.exists(d_path):
        img = cv2.imread(d_path)
        if img is not None and img.size > 0:
            return img
    return None

def build_side_by_side_verification(query_crop_bgr: np.ndarray, db_crop_bgr: Optional[np.ndarray],
                                     person_name: str, sim_pct: float, role: str) -> Optional[np.ndarray]:
    """
    Constructs a cyber-style biometric verification card displaying query crop vs database reference.
    """
    try:
        card_w, card_h = 640, 360
        canvas = np.zeros((card_h, card_w, 3), dtype=np.uint8)
        canvas[:] = (18, 24, 38)  # Dark slate / carbon

        # Header bar
        cv2.rectangle(canvas, (0, 0), (card_w, 48), (11, 16, 26), -1)
        cv2.line(canvas, (0, 48), (card_w, 48), (45, 60, 90), 1)
        cv2.putText(canvas, "ARGUSFACE BIOMETRIC VERIFICATION", (20, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 229, 255), 2, cv2.LINE_AA)

        box_size = 200
        y_top = 70

        role_lower = (role or "standard").lower()
        if role_lower == "vip":
            accent_color = (0, 215, 255)  # Gold in BGR
            role_label = "VIP GOST"
        elif role_lower == "blacklist":
            accent_color = (68, 23, 255)  # Red
            role_label = "CRNA LISTA"
        else:
            accent_color = (118, 230, 0)  # Green / Cyan
            role_label = "STANDARD"

        # Left: Query face
        q_resized = cv2.resize(query_crop_bgr, (box_size, box_size), interpolation=cv2.INTER_AREA)
        x_left = 40
        canvas[y_top:y_top+box_size, x_left:x_left+box_size] = q_resized
        cv2.rectangle(canvas, (x_left, y_top), (x_left+box_size, y_top+box_size), (0, 229, 255), 2)
        cv2.rectangle(canvas, (x_left, y_top+box_size), (x_left+box_size, y_top+box_size+26), (11, 16, 26), -1)
        cv2.putText(canvas, "SKENIRANO LICE", (x_left+20, y_top+box_size+18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 220, 240), 1, cv2.LINE_AA)

        # Right: Database reference face
        x_right = card_w - box_size - 40
        if db_crop_bgr is not None and db_crop_bgr.size > 0:
            db_resized = cv2.resize(db_crop_bgr, (box_size, box_size), interpolation=cv2.INTER_AREA)
            canvas[y_top:y_top+box_size, x_right:x_right+box_size] = db_resized
        else:
            cv2.rectangle(canvas, (x_right, y_top), (x_right+box_size, y_top+box_size), (30, 40, 60), -1)
            cv2.putText(canvas, "NEMA SLIKE", (x_right+45, y_top+105),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 140, 160), 1, cv2.LINE_AA)
        cv2.rectangle(canvas, (x_right, y_top), (x_right+box_size, y_top+box_size), accent_color, 2)
        cv2.rectangle(canvas, (x_right, y_top+box_size), (x_right+box_size, y_top+box_size+26), (11, 16, 26), -1)
        cv2.putText(canvas, "BAZA PODATAKA", (x_right+20, y_top+box_size+18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 220, 240), 1, cv2.LINE_AA)

        # Center Comparison Badge
        cx = card_w // 2
        cy = y_top + box_size // 2 - 10
        cv2.circle(canvas, (cx, cy), 46, (26, 35, 54), -1, cv2.LINE_AA)
        cv2.circle(canvas, (cx, cy), 46, accent_color, 2, cv2.LINE_AA)
        sim_str = f"{sim_pct:.1f}%"
        (tw, th), _ = cv2.getTextSize(sim_str, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        cv2.putText(canvas, sim_str, (cx - tw // 2, cy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, "MATCH", (cx - 24, cy + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.42, accent_color, 1, cv2.LINE_AA)

        # Bottom banner with Person Name & Status
        cv2.rectangle(canvas, (0, card_h - 48), (card_w, card_h), (11, 16, 26), -1)
        cv2.line(canvas, (0, card_h - 48), (card_w, card_h - 48), (45, 60, 90), 1)
        cv2.putText(canvas, f"OSOBA: {person_name.upper()}", (20, card_h - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        (rw, rh), _ = cv2.getTextSize(role_label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        rx = card_w - rw - 30
        cv2.rectangle(canvas, (rx - 10, card_h - 38), (card_w - 15, card_h - 10), accent_color, 1)
        cv2.putText(canvas, role_label, (rx, card_h - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, accent_color, 2, cv2.LINE_AA)

        return canvas
    except Exception:
        return None

def build_side_by_side_comparison(crop1_bgr: np.ndarray, crop2_bgr: np.ndarray,
                                   sim_pct: float, same_person: bool) -> Optional[np.ndarray]:
    """Constructs a 1:1 side-by-side comparison card between two arbitrary faces."""
    try:
        card_w, card_h = 640, 360
        canvas = np.zeros((card_h, card_w, 3), dtype=np.uint8)
        canvas[:] = (18, 24, 38)

        # Header bar
        cv2.rectangle(canvas, (0, 0), (card_w, 48), (11, 16, 26), -1)
        cv2.line(canvas, (0, 48), (card_w, 48), (45, 60, 90), 1)
        cv2.putText(canvas, "ARGUSFACE 1:1 BIOMETRIC COMPARISON", (20, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 229, 255), 2, cv2.LINE_AA)

        box_size = 200
        y_top = 70

        accent_color = (118, 230, 0) if same_person else (68, 23, 255)
        match_label = "ISTO LICE (MATCH)" if same_person else "RAZLICITE OSOBE (NO MATCH)"

        # Left: Slika 1
        c1 = cv2.resize(crop1_bgr, (box_size, box_size), interpolation=cv2.INTER_AREA)
        x_left = 40
        canvas[y_top:y_top+box_size, x_left:x_left+box_size] = c1
        cv2.rectangle(canvas, (x_left, y_top), (x_left+box_size, y_top+box_size), (0, 229, 255), 2)
        cv2.rectangle(canvas, (x_left, y_top+box_size), (x_left+box_size, y_top+box_size+26), (11, 16, 26), -1)
        cv2.putText(canvas, "FOTOGRAFIJA #1", (x_left+20, y_top+box_size+18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 220, 240), 1, cv2.LINE_AA)

        # Right: Slika 2
        c2 = cv2.resize(crop2_bgr, (box_size, box_size), interpolation=cv2.INTER_AREA)
        x_right = card_w - box_size - 40
        canvas[y_top:y_top+box_size, x_right:x_right+box_size] = c2
        cv2.rectangle(canvas, (x_right, y_top), (x_right+box_size, y_top+box_size), (0, 229, 255), 2)
        cv2.rectangle(canvas, (x_right, y_top+box_size), (x_right+box_size, y_top+box_size+26), (11, 16, 26), -1)
        cv2.putText(canvas, "FOTOGRAFIJA #2", (x_right+20, y_top+box_size+18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 220, 240), 1, cv2.LINE_AA)

        # Center Comparison Badge
        cx = card_w // 2
        cy = y_top + box_size // 2 - 10
        cv2.circle(canvas, (cx, cy), 46, (26, 35, 54), -1, cv2.LINE_AA)
        cv2.circle(canvas, (cx, cy), 46, accent_color, 2, cv2.LINE_AA)
        sim_str = f"{sim_pct:.1f}%"
        (tw, th), _ = cv2.getTextSize(sim_str, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        cv2.putText(canvas, sim_str, (cx - tw // 2, cy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, "SIMILARITY", (cx - 32, cy + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.38, accent_color, 1, cv2.LINE_AA)

        # Bottom banner with Verdict
        cv2.rectangle(canvas, (0, card_h - 48), (card_w, card_h), (11, 16, 26), -1)
        cv2.line(canvas, (0, card_h - 48), (card_w, card_h - 48), (45, 60, 90), 1)
        cv2.putText(canvas, f"REZULTAT: {match_label}", (20, card_h - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, accent_color, 2, cv2.LINE_AA)

        return canvas
    except Exception:
        return None

# =========================================================================
# API ROUTES
# =========================================================================

@app.get("/health")
@app.get("/api/v1/status")
def get_status(_: bool = Depends(verify_api_key)):
    """Returns system status, active models, vector backend and database statistics."""
    try:
        idx = face_engine.get_face_index()
        info = idx.get_info() if hasattr(idx, "get_info") else {}
        persons = db.get_all_persons()
        
        return {
            "status": "online",
            "service": "ArgusFace Studio AI Engine",
            "version": "1.0.0",
            "total_persons": len(persons),
            "total_samples": info.get("total_samples", 0),
            "index_backend": info.get("backend", "NumPy BLAS"),
            "has_faiss": info.get("has_faiss", False),
            "anti_spoofing": config.get_anti_spoofing()
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e)
        }

@app.post("/api/v1/compare")
async def compare_faces(
    image1: UploadFile = File(..., description="Prva fotografija za usporedbu"),
    image2: UploadFile = File(..., description="Druga fotografija za usporedbu"),
    threshold: float = Form(0.50, description="Biometrijski prag sličnosti (0.0 - 1.0)"),
    _: bool = Depends(verify_api_key)
):
    """
    Compares two photos and verifies if they depict the same person.
    Extracts facial embeddings and calculates cosine similarity.
    """
    bytes1 = await image1.read()
    bytes2 = await image2.read()

    bgr1 = decode_image_bytes(bytes1)
    bgr2 = decode_image_bytes(bytes2)

    if bgr1 is None or bgr1.size == 0:
        return {"success": False, "error": "Neispravan format prve fotografije."}
    if bgr2 is None or bgr2.size == 0:
        return {"success": False, "error": "Neispravan format druge fotografije."}

    faces1 = face_engine.extract_faces_from_image(bgr1, with_attributes=True, check_spoofing=False)
    if not faces1:
        return {"success": False, "error": "Na prvoj fotografiji nije detektirano lice."}

    faces2 = face_engine.extract_faces_from_image(bgr2, with_attributes=True, check_spoofing=False)
    if not faces2:
        return {"success": False, "error": "Na drugoj fotografiji nije detektirano lice."}

    # Select the primary (largest / highest confidence) face from each
    f1 = max(faces1, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
    f2 = max(faces2, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))

    emb1 = f1["embedding"]
    emb2 = f2["embedding"]

    if emb1 is None or emb2 is None:
        return {"success": False, "error": "Nije moguće generirati biometrijski potpis za detektirano lice."}

    # Cosine similarity
    sim = float(np.dot(emb1, emb2))
    sim = max(-1.0, min(1.0, sim))
    sim_pct = round(sim * 100, 1)

    same_person = bool(sim >= threshold)

    if sim >= 0.70:
        confidence = "Visoka"
    elif sim >= 0.50:
        confidence = "Umjerena"
    elif sim >= 0.35:
        confidence = "Niska"
    else:
        confidence = "Vrlo niska / Nema podudaranja"

    # Generate 1:1 comparison visual card
    comparison_card_b64 = None
    try:
        b1_x1, b1_y1, b1_x2, b1_y2 = f1["bbox"]
        b2_x1, b2_y1, b2_x2, b2_y2 = f2["bbox"]
        c1 = bgr1[max(0, b1_y1):min(bgr1.shape[0], b1_y2), max(0, b1_x1):min(bgr1.shape[1], b1_x2)]
        c2 = bgr2[max(0, b2_y1):min(bgr2.shape[0], b2_y2), max(0, b2_x1):min(bgr2.shape[1], b2_x2)]
        if c1.size > 0 and c2.size > 0:
            card = build_side_by_side_comparison(c1, c2, sim_pct, same_person)
            if card is not None:
                ok, buf = cv2.imencode(".jpg", card, [cv2.IMWRITE_JPEG_QUALITY, 88])
                if ok:
                    comparison_card_b64 = base64.b64encode(buf).decode("utf-8")
    except Exception:
        comparison_card_b64 = None

    return {
        "success": True,
        "same_person": same_person,
        "similarity": round(sim, 4),
        "similarity_pct": sim_pct,
        "threshold": threshold,
        "threshold_pct": round(threshold * 100, 1),
        "confidence": confidence,
        "comparison_card_base64": comparison_card_b64,
        "face1": {
            "age": int(f1["age"]) if f1.get("age") is not None else None,
            "gender": str(f1.get("gender") or ""),
            "bbox": f1["bbox"]
        },
        "face2": {
            "age": int(f2["age"]) if f2.get("age") is not None else None,
            "gender": str(f2.get("gender") or ""),
            "bbox": f2["bbox"]
        }
    }

@app.post("/api/v1/search")
async def search_database(
    image: UploadFile = File(..., description="Fotografija lica za pretragu u bazi"),
    threshold: Optional[float] = Form(None, description="Biometrijski prag prepoznavanja"),
    check_spoofing: bool = Form(False, description="Provjeri liveness / anti-spoofing"),
    _: bool = Depends(verify_api_key)
):
    """
    Detects all faces in the provided photo and searches for matches in the ArgusFace database.
    """
    # Fallback to configured settings threshold (typically 0.45) if not explicitly set
    cfg = config.load_settings()
    if threshold is None or threshold <= 0:
        threshold = float(cfg.get("threshold", 0.45))

    img_bytes = await image.read()
    bgr = decode_image_bytes(img_bytes)

    if bgr is None or bgr.size == 0:
        return {"success": False, "error": "Neispravan format fotografije."}

    faces = face_engine.extract_faces_from_image(
        bgr,
        with_attributes=True,
        check_spoofing=bool(check_spoofing)
    )

    if not faces:
        return {
            "success": True,
            "faces_detected": 0,
            "total_faces": 0,
            "results": [],
            "matches": [],
            "message": "Na fotografiji nije detektirano niti jedno lice."
        }

    face_index = face_engine.get_face_index()
    results = []

    for idx, f in enumerate(faces):
        match_info = face_index.match(f["embedding"], threshold=threshold)
        person_name = match_info["best_name"]
        pid = match_info.get("person_id")
        role = db.get_person_role(person_name) if match_info["matched"] else "unknown"

        sim = float(match_info.get("similarity", 0.0))
        sim_pct = round(sim * 100, 1)

        # Extract face crop from query image
        q_b64 = None
        try:
            qx1, qy1, qx2, qy2 = f["bbox"]
            h_img, w_img = bgr.shape[:2]
            q_crop = bgr[max(0, qy1):min(h_img, qy2), max(0, qx1):min(w_img, qx2)]
            if q_crop is not None and q_crop.size > 0:
                ok_q, buf_q = cv2.imencode(".jpg", q_crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok_q:
                    q_b64 = base64.b64encode(buf_q).decode("utf-8")
        except Exception:
            pass

        # Extract DB sample reference crop
        db_b64 = None
        if pid:
            try:
                samples = db.get_person_samples(pid)
                if samples:
                    for s in samples:
                        db_c = resolve_stored_image(s.get("crop_path"))
                        if db_c is None:
                            db_c = resolve_stored_image(s.get("image_path"))
                        if db_c is not None and db_c.size > 0:
                            ok_db, buf_db = cv2.imencode(".jpg", db_c, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            if ok_db:
                                db_b64 = base64.b64encode(buf_db).decode("utf-8")
                                break
            except Exception:
                pass

        results.append({
            "face_index": idx + 1,
            "matched": bool(match_info["matched"]),
            "person_name": person_name,
            "name": person_name,
            "person_id": pid,
            "role": role,
            "status": match_info.get("status", "Nepoznat"),
            "similarity": round(sim, 4),
            "similarity_pct": sim_pct,
            "threshold": threshold,
            "margin_pct": round(float(match_info.get("margin", 0.0)) * 100, 1),
            "sample_count": match_info.get("sample_count", 0),
            "age": int(f["age"]) if f.get("age") is not None else None,
            "gender": str(f.get("gender") or ""),
            "is_real": bool(f.get("is_real", True)),
            "liveness_conf": round(float(f.get("liveness_conf", 1.0)), 2),
            "bbox": f["bbox"],
            "query_crop_base64": q_b64,
            "sample_image_base64": db_b64
        })

    # Generate visual annotated image with bounding boxes & landmarks
    annotated_b64 = None
    verification_card_b64 = None
    try:
        annotated_bgr, _ = face_engine.process_and_annotate(
            bgr,
            threshold=threshold,
            draw_landmarks=True,
            cached_faces=faces,
            face_index=face_index
        )
        if annotated_bgr is not None and annotated_bgr.size > 0:
            ok, buf = cv2.imencode(".jpg", annotated_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                annotated_b64 = base64.b64encode(buf).decode("utf-8")
    except Exception:
        annotated_b64 = None

    # If top face is matched, generate side-by-side biometric verification card
    if results and results[0].get("matched") and results[0].get("person_id"):
        try:
            top_res = results[0]
            pid = top_res["person_id"]
            pname = top_res["person_name"]
            prole = top_res["role"]
            psim = top_res["similarity_pct"]

            # Query crop
            qx1, qy1, qx2, qy2 = top_res["bbox"]
            h_img, w_img = bgr.shape[:2]
            q_crop = bgr[max(0, qy1):min(h_img, qy2), max(0, qx1):min(w_img, qx2)]

            # DB sample crop
            db_crop = None
            samples = db.get_person_samples(pid)
            if samples:
                for s in samples:
                    db_crop = resolve_stored_image(s.get("crop_path"))
                    if db_crop is None:
                        db_crop = resolve_stored_image(s.get("image_path"))
                    if db_crop is not None and db_crop.size > 0:
                        break

            if q_crop is not None and q_crop.size > 0:
                card = build_side_by_side_verification(q_crop, db_crop, pname, psim, prole)
                if card is not None:
                    ok_card, buf_card = cv2.imencode(".jpg", card, [cv2.IMWRITE_JPEG_QUALITY, 88])
                    if ok_card:
                        verification_card_b64 = base64.b64encode(buf_card).decode("utf-8")
        except Exception:
            verification_card_b64 = None

    matches = [r for r in results if r.get("matched")]

    return {
        "success": True,
        "faces_detected": len(faces),
        "total_faces": len(faces),
        "results": results,
        "matches": matches,
        "matched_count": len(matches),
        "annotated_image_base64": annotated_b64,
        "verification_card_base64": verification_card_b64
    }

@app.post("/api/v1/enroll")
@app.post("/api/v1/persons/enroll")
@app.post("/api/v1/person/add")
async def enroll_person(
    image: UploadFile = File(...),
    name: str = Form(...),
    role: str = Form("standard"),
    notes: str = Form(""),
    _: bool = Depends(verify_api_key)
):
    """
    Dodaje novu osobu ili dodatni uzorak lica postojećoj osobi u ArgusFace bazu.
    Automatski ekstrahira biometrijski embedding, sprema crop i originalnu sliku,
    te ažurira FAISS / NumPy indeks.
    """
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Ime osobe ne smije biti prazno.")

    clean_role = (role or "standard").strip().lower()
    if clean_role not in ["standard", "vip", "blacklist"]:
        clean_role = "standard"

    clean_notes = (notes or "").strip()

    contents = await image.read()
    img_bgr = decode_image_bytes(contents)
    if img_bgr is None:
        raise HTTPException(status_code=400, detail="Neispravan format slike. Pošaljite JPEG ili PNG sliku.")

    faces = face_engine.extract_faces_from_image(img_bgr, with_attributes=True, check_spoofing=True)
    if not faces:
        return {
            "success": False,
            "error": "Na poslanoj slici nije detektirano niti jedno lice. Pošaljite jasniju fotografiju."
        }

    # Ako je detektirano više lica, odaberi najveće lice (površina bbox-a)
    target_face = max(faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))

    # Dohvati ili kreiraj osobu u SQLite bazi
    person_id = db.get_or_create_person(clean_name, clean_notes, role=clean_role)
    try:
        db.update_person(person_id, clean_name, clean_notes, role=clean_role)
    except Exception:
        pass

    # Trajno spremi originalnu sliku i crop lica
    orig_path = save_image_dedup(img_bgr, UPLOADS_DIR, prefix="orig_bot")
    crop_filename = f"crop_{person_id}_{uuid.uuid4().hex[:8]}.jpg"
    crop_path = os.path.join(CROPS_DIR, crop_filename)
    imwrite_unicode(crop_path, target_face["crop_bgr"])

    # Dodaj uzorak lica (automatski poziva callback za osvježavanje indeksa)
    sample_id = db.add_face_sample(
        person_id=person_id,
        image_path=orig_path,
        crop_path=crop_path,
        embedding=target_face["embedding"],
        confidence=target_face.get("confidence", 1.0)
    )

    all_samples = db.get_person_samples(person_id)

    return {
        "success": True,
        "person_id": person_id,
        "name": clean_name,
        "role": clean_role,
        "notes": clean_notes,
        "sample_id": sample_id,
        "total_samples": len(all_samples),
        "age": int(target_face["age"]) if target_face.get("age") is not None else None,
        "gender": str(target_face.get("gender") or ""),
        "is_real": bool(target_face.get("is_real", True)),
        "liveness_conf": round(float(target_face.get("liveness_conf", 1.0)), 2),
        "faces_detected_count": len(faces)
    }

# =========================================================================
# PERSONS DIRECTORY & DATABASE SEARCH ROUTES
# =========================================================================

@app.get("/api/v1/persons")
def get_persons_directory(
    query: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    with_thumbnail: bool = True,
    _: bool = Depends(verify_api_key)
):
    """
    Vraća popis i pretragu svih osoba u ArgusFace bazi podataka.
    Omogućuje filtriranje po imenu, bilješkama i sigurnosnoj ulozi.
    """
    all_p = db.get_all_persons()

    # Pretraga po ključnoj riječi (ime ili bilješke)
    if query:
        q_clean = query.strip().lower()
        all_p = [
            p for p in all_p
            if q_clean in (p.get("name") or "").lower() or q_clean in (p.get("notes") or "").lower()
        ]

    # Filtriranje po ulozi (standard, vip, blacklist)
    if role and role.strip().lower() not in ["all", "sve", ""]:
        r_clean = role.strip().lower()
        all_p = [p for p in all_p if (p.get("role") or "standard").lower() == r_clean]

    total_count = len(all_p)
    paginated = all_p[offset : offset + limit]

    items = []
    for p in paginated:
        thumb_b64 = None
        if with_thumbnail:
            try:
                samples = db.get_person_samples(p["id"])
                if samples:
                    for s in samples:
                        c_img = resolve_stored_image(s.get("crop_path"))
                        if c_img is None:
                            c_img = resolve_stored_image(s.get("image_path"))
                        if c_img is not None and c_img.size > 0:
                            c_thumb = cv2.resize(c_img, (96, 96), interpolation=cv2.INTER_AREA)
                            ok, buf = cv2.imencode(".jpg", c_thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
                            if ok:
                                thumb_b64 = base64.b64encode(buf).decode("utf-8")
                                break
            except Exception:
                pass

        items.append({
            "id": p["id"],
            "name": p["name"],
            "role": p.get("role", "standard"),
            "notes": p.get("notes") or "",
            "sample_count": p.get("sample_count", 0),
            "created_at": str(p.get("created_at") or ""),
            "last_sample_at": str(p.get("last_sample_at") or ""),
            "thumbnail_base64": thumb_b64
        })

    return {
        "success": True,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "persons": items
    }

@app.get("/api/v1/persons/{person_id}")
def get_person_details(person_id: int, _: bool = Depends(verify_api_key)):
    """Dohvaća detalje pojedine osobe i uzorke lica."""
    p = db.get_person(person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Osoba nije pronađena.")

    raw_samples = db.get_person_samples(person_id)
    samples = []
    for s in raw_samples:
        thumb_b64 = None
        try:
            c_img = resolve_stored_image(s.get("crop_path"))
            if c_img is None:
                c_img = resolve_stored_image(s.get("image_path"))
            if c_img is not None and c_img.size > 0:
                ok, buf = cv2.imencode(".jpg", c_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    thumb_b64 = base64.b64encode(buf).decode("utf-8")
        except Exception:
            pass

        samples.append({
            "id": s["id"],
            "confidence": float(s.get("confidence") or 1.0),
            "created_at": str(s.get("created_at") or ""),
            "crop_base64": thumb_b64
        })

    return {
        "success": True,
        "person": {
            "id": p["id"],
            "name": p["name"],
            "role": p.get("role", "standard"),
            "notes": p.get("notes") or "",
            "created_at": str(p.get("created_at") or ""),
            "sample_count": len(samples),
            "samples": samples
        }
    }

@app.delete("/api/v1/persons/{person_id}")
def delete_person_endpoint(person_id: int, _: bool = Depends(verify_api_key)):
    """Briše osobu i sve njezine uzorke iz baze podataka."""
    p = db.get_person(person_id)
    if not p:
        raise HTTPException(status_code=404, detail="Osoba ne postoji.")

    name = p["name"]
    db.delete_person(person_id)

    # Force rebuild of face search index so deleted person is immediately purged from search
    try:
        idx = face_engine.get_face_index()
        if hasattr(idx, "rebuild"):
            idx.rebuild()
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Osoba '{name}' (ID #{person_id}) uspješno obrisana iz baze."
    }

# =========================================================================
# BOT ADMIN & ACCESS CONTROL ROUTES
# =========================================================================

@app.get("/api/v1/bot/users")
def get_bot_users(_: bool = Depends(verify_api_key)):
    """Dohvaća trenutne postavke pristupa Telegram botu, listu ovlaštenih korisnika i administratora."""
    return config.get_bot_config()

@app.post("/api/v1/bot/users/add")
def add_bot_user(
    chat_id: int = Form(...),
    name: str = Form("Korisnik"),
    role: str = Form("user"),
    _: bool = Depends(verify_api_key)
):
    """Dodaje ili ažurira ovlaštenog Telegram korisnika."""
    cfg = config.get_bot_config()
    allowed = cfg.get("allowed_users", [])
    admin_ids = set(cfg.get("admin_chat_ids", []))

    clean_role = (role or "user").strip().lower()
    clean_name = (name or "Korisnik").strip()

    if clean_role == "admin":
        admin_ids.add(chat_id)
    else:
        # If demoting or adding as regular user, ensure not in admin list unless intentional
        if chat_id in admin_ids and clean_role != "admin":
            admin_ids.discard(chat_id)

    # Filter out if already present to update
    allowed = [u for u in allowed if u.get("chat_id") != chat_id]
    allowed.append({
        "chat_id": chat_id,
        "name": clean_name,
        "role": clean_role,
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    cfg["allowed_users"] = allowed
    cfg["admin_chat_ids"] = list(admin_ids)
    config.save_bot_config(cfg)

    return {
        "success": True,
        "message": f"Korisnik '{clean_name}' ({chat_id}) uspješno dodan.",
        "config": cfg
    }

@app.post("/api/v1/bot/users/remove")
def remove_bot_user(
    chat_id: int = Form(...),
    _: bool = Depends(verify_api_key)
):
    """Uklanja ovlaštenog korisnika iz pristupa Telegram botu."""
    cfg = config.get_bot_config()
    allowed = cfg.get("allowed_users", [])
    admin_ids = set(cfg.get("admin_chat_ids", []))

    admin_ids.discard(chat_id)
    cfg["allowed_users"] = [u for u in allowed if u.get("chat_id") != chat_id]
    cfg["admin_chat_ids"] = list(admin_ids)
    config.save_bot_config(cfg)

    return {
        "success": True,
        "message": f"Korisnik s Chat ID {chat_id} je uklonjen.",
        "config": cfg
    }

@app.post("/api/v1/bot/pin")
def update_bot_pin(
    pin: str = Form(...),
    _: bool = Depends(verify_api_key)
):
    """Ažurira sigurnosni PIN za pristup Telegram botu."""
    clean_pin = pin.strip()
    if len(clean_pin) < 4:
        raise HTTPException(status_code=400, detail="PIN mora sadržavati najmanje 4 znaka.")

    cfg = config.get_bot_config()
    cfg["pin"] = clean_pin
    config.save_bot_config(cfg)

    return {
        "success": True,
        "message": "Sigurnosni PIN je uspješno promijenjen.",
        "pin": clean_pin
    }

# =========================================================================
# BACKGROUND SERVER LIFECYCLE
# =========================================================================

_server_thread = None
_server_instance = None

def run_uvicorn_server(host: str, port: int):
    config_uv = uvicorn.Config(app=app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config_uv)
    global _server_instance
    _server_instance = server
    server.run()

def start_api_service_background(host: str = "0.0.0.0", port: int = 5055):
    """Starts the FastAPI server in a dedicated background daemon thread."""
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return True, f"API poslužitelj već radi na {host}:{port}"
    try:
        _server_thread = threading.Thread(
            target=run_uvicorn_server,
            args=(host, port),
            daemon=True,
            name="ArgusFace-API-Server"
        )
        _server_thread.start()
        return True, f"API poslužitelj je uspješno pokrenut na portu {port}."
    except Exception as e:
        return False, f"Greška pri pokretanju API poslužitelja: {e}"

def stop_api_service():
    """Stops the running API server."""
    global _server_instance
    if _server_instance is not None:
        _server_instance.should_exit = True
        _server_instance = None
        return True, "API poslužitelj je zaustavljen."
    return False, "API poslužitelj nije bio aktivan."

if __name__ == "__main__":
    api_cfg = config.get_api_config()
    host = api_cfg.get("host", "0.0.0.0")
    port = api_cfg.get("port", 5055)
    print(f"[*] Pokrećem ArgusFace lokalni API poslužitelj na http://{host}:{port} ...")
    uvicorn.run("src.api_server:app", host=host, port=port, reload=False)
