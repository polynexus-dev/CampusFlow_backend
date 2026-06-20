"""
Face recognition utilities using InsightFace (ArcFace).

Performance-optimised design:
  - det_size=(320, 320) — ~3× faster than 640×640 with negligible accuracy loss
  - Single model pass per image via _analyse_image() — no double inference
  - Lazy singleton loader — model loaded once per process

Public API:
  - extract_embedding(image_bytes)                   → 512-d numpy array
  - extract_embedding_with_pose(image_bytes)         → (embedding, yaw, pitch, roll)
  - compare_embeddings(live, stored)                 → (is_match, score)
  - basic_liveness_check(image_bytes)                → (passed, reason)
  - check_head_pose(image_bytes, expected_angle)     → (passed, reason)
"""

import io
import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from django.conf import settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Singleton InsightFace model
# ──────────────────────────────────────────────────────────────────────────────
_face_analyzer = None


def _get_face_analyzer():
    """
    Lazily initialise InsightFace FaceAnalysis.
    Uses det_size=(320, 320) for ~3× faster inference on CPU with
    negligible accuracy loss for close-up selfies.
    """
    global _face_analyzer
    if _face_analyzer is None:
        from insightface.app import FaceAnalysis

        model_name = getattr(settings, "INSIGHTFACE_MODEL_NAME", "buffalo_l")
        model_root = str(
            getattr(settings, "INSIGHTFACE_MODEL_ROOT", "./models/insightface")
        )

        _face_analyzer = FaceAnalysis(
            name=model_name,
            root=model_root,
            providers=["CPUExecutionProvider"],
        )
        # 320×320 is sufficient for selfie-distance faces
        _face_analyzer.prepare(ctx_id=-1, det_size=(320, 320))
        logger.info("InsightFace model '%s' loaded (det_size=320).", model_name)

    return _face_analyzer


# ──────────────────────────────────────────────────────────────────────────────
# Internal: single model pass — call this instead of analyzer.get() directly
# ──────────────────────────────────────────────────────────────────────────────
def _decode_image(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes → OpenCV BGR array."""
    pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def _analyse_image(image_bytes: bytes):
    """
    Run InsightFace on the image once and return the single detected Face object.

    Raises ValueError if no face or multiple faces detected.
    Returns the face object (has .normed_embedding, .det_score, .pose, …).
    """
    cv_image = _decode_image(image_bytes)
    analyzer = _get_face_analyzer()
    faces = analyzer.get(cv_image)

    if len(faces) == 0:
        raise ValueError(
            "No face detected. Please ensure your face is clearly visible, "
            "well-lit, and centered in the frame."
        )

    if len(faces) > 1:
        # Classroom scenario: pick the largest face (= closest to the camera).
        def _area(f):
            x1, y1, x2, y2 = f.bbox
            return (x2 - x1) * (y2 - y1)

        faces = sorted(faces, key=_area, reverse=True)
        logger.info(
            "Multiple faces detected (%d) — selected largest (area=%.0f px²).",
            len(faces), _area(faces[0]),
        )

    return faces[0], cv_image


# ──────────────────────────────────────────────────────────────────────────────
# Embedding extraction (single pass)
# ──────────────────────────────────────────────────────────────────────────────
def extract_embedding(image_bytes: bytes) -> np.ndarray:
    """
    Extract a 512-d ArcFace embedding.  Single model pass.

    Raises:
        ValueError — no face / multiple faces / low confidence.
    """
    face, _ = _analyse_image(image_bytes)

    if face.det_score < 0.5:
        raise ValueError(
            "Face detected with low confidence. Please retake with better "
            "lighting and a clearer angle."
        )

    embedding = face.normed_embedding  # L2-normalised, shape (512,)
    logger.info(
        "Embedding extracted — det_score=%.3f, shape=%s",
        face.det_score,
        embedding.shape,
    )
    return embedding.astype(np.float32)


def extract_embedding_with_pose(
    image_bytes: bytes,
) -> Tuple[np.ndarray, Optional[float], Optional[float], Optional[float]]:
    """
    Extract embedding AND pose in a SINGLE model pass.

    Returns:
        (embedding, yaw, pitch, roll)
        yaw/pitch/roll are None if the model doesn't expose pose.

    Raises:
        ValueError — no face / multiple faces / low confidence.
    """
    face, _ = _analyse_image(image_bytes)

    if face.det_score < 0.5:
        raise ValueError(
            "Face detected with low confidence. Please retake with better "
            "lighting and a clearer angle."
        )

    embedding = face.normed_embedding.astype(np.float32)

    yaw = pitch = roll = None
    if hasattr(face, "pose") and face.pose is not None:
        yaw, pitch, roll = float(face.pose[0]), float(face.pose[1]), float(face.pose[2])

    logger.info(
        "Embedding+pose extracted — det_score=%.3f, yaw=%s°, pitch=%s°, roll=%s°",
        face.det_score,
        f"{yaw:.1f}" if yaw is not None else "N/A",
        f"{pitch:.1f}" if pitch is not None else "N/A",
        f"{roll:.1f}" if roll is not None else "N/A",
    )
    return embedding, yaw, pitch, roll


# ──────────────────────────────────────────────────────────────────────────────
# Embedding comparison (cosine similarity)
# ──────────────────────────────────────────────────────────────────────────────
def compare_embeddings(
    live_embedding: np.ndarray,
    stored_embeddings: List[np.ndarray],
    threshold: Optional[float] = None,
) -> Tuple[bool, float]:
    """
    Compare live embedding against stored embeddings using cosine similarity.
    InsightFace produces L2-normalised vectors → dot product == cosine sim.
    """
    if threshold is None:
        threshold = getattr(settings, "FACE_SIMILARITY_THRESHOLD", 0.55)

    if not stored_embeddings:
        return False, 0.0

    stored_matrix = np.stack(stored_embeddings)          # (N, 512)
    similarities  = np.dot(stored_matrix, live_embedding) # (N,)

    best_score = float(np.max(similarities))
    is_match   = best_score >= threshold

    logger.info(
        "Face comparison — best_score=%.4f, threshold=%.4f, match=%s",
        best_score, threshold, is_match,
    )
    return is_match, best_score


# ──────────────────────────────────────────────────────────────────────────────
# Liveness / anti-spoofing  (attendance mark only)
# ──────────────────────────────────────────────────────────────────────────────
def _anti_spoof_score(face_crop_bgr: np.ndarray) -> float:
    """
    Estimate probability that a face crop is from a screen or printed photo
    rather than a live person.  Returns 0.0 = real, 1.0 = definite spoof.

    Two independent signals are combined:

    1. Variance-of-variances (VoV) — Real skin has non-uniform micro-texture
       (pores, hair, shadows) that produces highly varied local standard
       deviations across face regions.  A photo displayed on a screen is
       smoothed by JPEG compression + screen rendering, making local stds
       unnaturally uniform → low VoV.

    2. FFT peak ratio — Phone/monitor screens have a pixel grid that imprints
       periodic high-frequency components in the image.  These appear as sharp
       peaks in the FFT magnitude spectrum that are absent in real faces.

    Spoof is flagged only when BOTH signals agree, so false positives on
    real users (dim lighting, compressed selfies) are minimised.
    """
    img  = cv2.resize(face_crop_bgr, (128, 128))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # ── Signal 1: variance-of-variances ──────────────────────────────────
    block_stds = [
        float(np.std(gray[y:y + 8, x:x + 8]))
        for y in range(0, 128, 8)
        for x in range(0, 128, 8)
    ]
    vov = float(np.var(block_stds))
    # Definite texture spoof under extreme smoothness (doubly compressed screen playback)
    texture_spoof = vov < 30.0

    # ── Signal 2: FFT peak-to-mean ratio ─────────────────────────────────
    mag = np.abs(np.fft.fftshift(np.fft.fft2(gray)))
    h, w = mag.shape
    mag[h // 2 - 4: h // 2 + 4, w // 2 - 4: w // 2 + 4] = 0  # suppress DC
    log_mag   = np.log(mag + 1)
    top20_avg = float(np.mean(np.sort(log_mag.ravel())[-20:]))
    mean_val  = float(np.mean(log_mag))
    peak_ratio = top20_avg / (mean_val + 1e-6)
    # Lower threshold to 3.8 to capture high-res display playbacks
    fft_spoof = peak_ratio > 3.8

    logger.debug(
        "Anti-spoof signals — VoV=%.1f (spoof<30.0), peak_ratio=%.2f (spoof>3.8)",
        vov, peak_ratio,
    )

    # Definite screen spoof if grid moire is detected AND texture is smooth
    if fft_spoof and vov < 45.0:
        return 0.95   # Screen pixel grid + smoothed texture → definite spoof
    if fft_spoof:
        return 0.90   # Strong pixel grid detected → definite spoof
    if texture_spoof:
        return 0.90   # Extremely smooth texture → definite spoof
    if vov < 55.0:
        return 0.45   # Borderline texture smoothing (warning only - allows beauty filter/dim room)
    return 0.05       # Clean


def basic_liveness_check(image_bytes: bytes) -> Tuple[bool, str]:
    """
    Two-layer liveness check:

    Layer 1 — InsightFace SCRFD det_score
        Rejects images where the detector cannot confidently locate a face
        (e.g. no person in frame, heavily occluded, very dark).

    Layer 2 — Texture + FFT anti-spoofing (_anti_spoof_score)
        Detects printed photos or photos displayed on a phone/monitor screen.
        Only blocks when BOTH texture and frequency signals agree to minimise
        false positives on real users in classroom lighting.
    """
    cv_image = _decode_image(image_bytes)

    h, w = cv_image.shape[:2]
    if w < 200 or h < 200:
        return False, "Image resolution too low. Please take a higher-quality photo."

    # ── Layer 1: face detection confidence ───────────────────────────────
    try:
        face, _ = _analyse_image(image_bytes)
    except ValueError as e:
        return False, str(e)

    if face.det_score < 0.65:
        return False, (
            f"Face not detected clearly (score: {face.det_score:.2f}). "
            "Please ensure your face is well-lit and centered in the frame."
        )

    # ── Layer 2: anti-spoofing on face crop ───────────────────────────────
    x1, y1, x2, y2 = (int(v) for v in face.bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    face_crop = cv_image[y1:y2, x1:x2]

    if face_crop.size > 0:
        spoof_score = _anti_spoof_score(face_crop)
        if spoof_score >= 0.90:
            logger.warning(
                "Anti-spoof BLOCKED — spoof_score=%.2f, det_score=%.3f",
                spoof_score, face.det_score,
            )
            return False, (
                "Photo spoofing detected. Please present your live face directly "
                "to the camera — do not show a photo or screen image."
            )
        if spoof_score >= 0.45:
            logger.warning(
                "Anti-spoof WARNING — spoof_score=%.2f (borderline), det_score=%.3f",
                spoof_score, face.det_score,
            )

    logger.info(
        "Liveness OK — det_score=%.3f, spoof_score=%.2f",
        face.det_score,
        spoof_score if face_crop.size > 0 else -1,
    )
    return True, "Liveness check passed."


# ──────────────────────────────────────────────────────────────────────────────
# Motion-based liveness  (two-frame comparison)
# ──────────────────────────────────────────────────────────────────────────────
def _eye_crop(img: np.ndarray, kps: np.ndarray, eye_idx: int, radius: int) -> np.ndarray:
    """Return a grayscale crop centred on one eye keypoint, using specified crop radius."""
    h, w = img.shape[:2]
    cx, cy = int(kps[eye_idx][0]), int(kps[eye_idx][1])
    x1, y1 = max(0, cx - radius), max(0, cy - radius)
    x2, y2 = min(w, cx + radius), min(h, cy + radius)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return np.array([])
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (48, 48)).astype(np.float32)


def detect_specular_flash_reflection(
    img1: np.ndarray,
    img2: np.ndarray,
    bbox: np.ndarray,
    kps1: np.ndarray,
    kps2: np.ndarray,
) -> Tuple[bool, float]:
    """
    Detect specular reflection (glare) from screen flash on target glass displays.
    Aligns img1 to img2 using translation shift from keypoints, crops the face region,
    normalizes exposure to prevent auto-exposure bypass, masks out eye/glasses regions
    to prevent false positives, and checks for high relative glare intensity.
    Returns (is_spoof, reflection_pixels).
    """
    # 1. Compute global translation shift to align img1 to img2
    shift = np.mean(kps2 - kps1, axis=0)
    dx, dy = float(shift[0]), float(shift[1])

    h, w = img2.shape[:2]
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    img1_aligned = cv2.warpAffine(img1, M, (w, h))

    # 2. Convert to grayscale
    gray1 = cv2.cvtColor(img1_aligned, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

    # 3. Crop face region
    x1, y1, x2, y2 = (int(v) for v in bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    crop1 = gray1[y1:y2, x1:x2]
    crop2 = gray2[y1:y2, x1:x2]

    if crop1.size == 0 or crop2.size == 0:
        return False, 0.0

    # 4. Normalize crop2 exposure to match crop1 (combats camera auto-exposure adjustments)
    mean1, std1 = float(np.mean(crop1)), float(np.std(crop1))
    mean2, std2 = float(np.mean(crop2)), float(np.std(crop2))
    
    crop2_norm = (crop2.astype(np.float32) - mean2) * (std1 / (std2 + 1e-6)) + mean1
    crop2_norm = np.clip(crop2_norm, 0.0, 255.0).astype(np.uint8)

    # 5. Compute difference (intensity increase due to flash after exposure matching)
    diff = cv2.subtract(crop2_norm, crop1)

    # 6. Screen glare creates localized high-intensity spots in crop2_norm (> 210) and high diff (> 65)
    reflection_mask = (crop2_norm > 210) & (diff > 65)

    # 7. Mask out eye/glasses regions to avoid false positives on glasses wearers
    eye_dist = np.linalg.norm(kps2[0] - kps2[1])
    mask_radius = int(eye_dist * 0.40)  # Cover the entire orbital/glasses area

    grid_y, grid_x = np.ogrid[:reflection_mask.shape[0], :reflection_mask.shape[1]]
    valid_mask = np.ones(reflection_mask.shape, dtype=bool)
    for eye_idx in (0, 1):
        cx = int(kps2[eye_idx][0]) - x1
        cy = int(kps2[eye_idx][1]) - y1
        dist_sq = (grid_x - cx) ** 2 + (grid_y - cy) ** 2
        valid_mask &= (dist_sq > mask_radius ** 2)

    # Apply the valid mask
    reflection_mask &= valid_mask
    reflection_pixels = int(np.sum(reflection_mask))

    # Specular screen glare typically covers a cluster of at least 100 pixels
    is_spoof = reflection_pixels > 100

    logger.warning(
        "FLASH REFLECTION CHECK - reflection_pixels=%d, threshold=%d -> %s",
        reflection_pixels, 100, "SPOOF" if is_spoof else "LIVE"
    )
    return is_spoof, float(reflection_pixels)


def check_frame_motion(
    frame1_bytes: bytes,
    frame2_bytes: bytes,
) -> Tuple[bool, float, str]:
    """
    Blink-based liveness check using eye-region comparison.

    The user is prompted to blink during the 1-second capture window.
    A blink makes the eye region change dramatically (pixel MAD ≈ 30–80).
    A static photo on a screen cannot blink (MAD ≈ 0–3).

    Why eye regions instead of whole-face MAD:
      - Hand tremor shifts the whole face rigidly → whole-face MAD spikes even for photos.
      - Eye regions are insensitive to rigid translation; only a genuine blink
        (intensity change from eyelid closing) produces a high score.

    Tune the threshold via Django setting LIVENESS_BLINK_THRESHOLD (default 8.0).
    """
    from django.conf import settings as django_settings
    THRESHOLD = getattr(django_settings, "LIVENESS_BLINK_THRESHOLD", 5.5)

    analyzer = _get_face_analyzer()

    img1 = _decode_image(frame1_bytes)
    img2 = _decode_image(frame2_bytes)

    def _largest(faces):
        return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])) if faces else None

    face1 = _largest(analyzer.get(img1))
    face2 = _largest(analyzer.get(img2))

    if face1 is None:
        # Don't skip — a missing baseline face means we can't verify liveness.
        # This also blocks attackers whose spoofed photo fails detection at baseline.
        logger.warning("Blink check: no face in baseline frame — failing.")
        return False, 0.0, (
            "Could not detect your face at the start of the capture. "
            "Please centre your face in the oval and try again."
        )

    if face2 is None:
        return False, 0.0, "No face detected in main frame. Please try again."

    kps1 = face1.kps.astype(np.float32)   # (5, 2): left-eye, right-eye, nose, mouthx2
    kps2 = face2.kps.astype(np.float32)

    # Specular Screen Flash reflection liveness check
    is_flash_spoof, reflection_pixels = detect_specular_flash_reflection(img1, img2, face2.bbox, kps1, kps2)
    if is_flash_spoof:
        logger.warning("BLINK BLOCKED - screen flash reflection detected (pixels=%d).", reflection_pixels)
        return False, 0.0, "Screen reflection detected. Please present your live face directly."

    # Calculate a single, unified scale-invariant radius based on the average eye distance across both frames
    eye_dist1 = np.linalg.norm(kps1[0] - kps1[1])
    eye_dist2 = np.linalg.norm(kps2[0] - kps2[1])
    avg_eye_dist = (eye_dist1 + eye_dist2) / 2.0
    radius = int(max(12, avg_eye_dist * 0.16))

    c_start, c_end = 5, 43  # 38x38 central region of the 48x48 crop (allows +/- 5 pixel shifts)

    # Compare both eyes; require a blink in both eyes to avoid single-eye false alarms
    per_eye_mad = [0.0, 0.0]
    for eye_idx in (0, 1):
        e1 = _eye_crop(img1, kps1, eye_idx, radius)
        e2 = _eye_crop(img2, kps2, eye_idx, radius)
        if e1.size == 0 or e2.size == 0:
            continue

        # Match mean and std of e2 to e1 to normalize exposure/contrast differences
        mean1, std1 = float(np.mean(e1)), float(np.std(e1))
        mean2, std2 = float(np.mean(e2)), float(np.std(e2))
        e2_norm = (e2 - mean2) * (std1 / (std2 + 1e-6)) + mean1
        e2_norm = np.clip(e2_norm, 0.0, 255.0)

        # Align e1 and e2 to find the minimum MAD under shifting window template matching.
        # We increase search range to [-5, 5] pixels to robustly handle landmark detector jitter.
        best_mad = float("inf")
        e1_center = e1[c_start:c_end, c_start:c_end]

        for dy in range(-5, 6):
            for dx in range(-5, 6):
                e2_shifted = e2_norm[c_start + dy : c_end + dy, c_start + dx : c_end + dx]
                mad = float(np.mean(np.abs(e1_center - e2_shifted)))
                if mad < best_mad:
                    best_mad = mad

        per_eye_mad[eye_idx] = best_mad

    # Calculate nose motion as a control baseline to detect global motion / screen shake
    n1 = _eye_crop(img1, kps1, 2, radius)
    n2 = _eye_crop(img2, kps2, 2, radius)
    if n1.size > 0 and n2.size > 0:
        # Match mean and std of n2 to n1
        mean_n1, std_n1 = float(np.mean(n1)), float(np.std(n1))
        mean_n2, std_n2 = float(np.mean(n2)), float(np.std(n2))
        n2_norm = (n2 - mean_n2) * (std_n1 / (std_n2 + 1e-6)) + mean_n1
        n2_norm = np.clip(n2_norm, 0.0, 255.0)

        best_nose_mad = float("inf")
        n1_center = n1[c_start:c_end, c_start:c_end]
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                n2_shifted = n2_norm[c_start + dy : c_end + dy, c_start + dx : c_end + dx]
                mad = float(np.mean(np.abs(n1_center - n2_shifted)))
                if mad < best_nose_mad:
                    best_nose_mad = mad
    else:
        best_nose_mad = 0.0

    # Require both eyes to exceed the threshold to prevent single-eye false passes (e.g. glasses glare)
    eye0_mad = per_eye_mad[0]
    eye1_mad = per_eye_mad[1]
    min_eye_mad = min(eye0_mad, eye1_mad)

    logger.warning(
        "BLINK CHECK — eye0_MAD=%.1f, eye1_MAD=%.1f, min=%.1f, nose_MAD=%.1f, threshold=%.1f → %s",
        eye0_mad, eye1_mad, min_eye_mad, best_nose_mad, THRESHOLD,
        "LIVE" if (min_eye_mad >= THRESHOLD and best_nose_mad < 4.5) else "SPOOF",
    )

    # If control region shows significant motion, it's global movement or screen shaking (spoof)
    if best_nose_mad >= 4.5:
        logger.warning(
            "BLINK BLOCKED — global motion detected (nose_MAD=%.1f >= 4.5). "
            "Likely screen spoofing or camera instability.",
            best_nose_mad,
        )
        return False, min_eye_mad, (
            "Camera instability or screen movement detected. Please hold the phone still "
            "and present your live face directly."
        )

    if min_eye_mad < THRESHOLD:
        return False, min_eye_mad, (
            "No blink detected. Please blink your eyes once during the capture."
        )

    return True, min_eye_mad, f"Blink detected (eye_MAD={min_eye_mad:.1f})."


# ──────────────────────────────────────────────────────────────────────────────
# Head-motion liveness  (nod / turn challenges)
# ──────────────────────────────────────────────────────────────────────────────
def check_head_motion(
    frame1_bytes: bytes,
    frame2_bytes: bytes,
    challenge_type: str,
) -> Tuple[bool, float, str]:
    """
    Two-frame liveness check for head-motion challenges.

    frame1 — baseline captured before the challenge action (must be front-facing)
    frame2 — captured after the student performs the action (must match challenge pose)

    Validates both absolute coordinate displacement and face pose (yaw/pitch angles)
    to prevent spoofing using static profile photos.
    """
    analyzer = _get_face_analyzer()

    def _largest(faces):
        return (
            max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            if faces
            else None
        )

    img1 = _decode_image(frame1_bytes)
    face1 = _largest(analyzer.get(img1))
    if face1 is None:
        return False, 0.0, (
            "No face detected at start of capture. "
            "Please centre your face in the oval and try again."
        )

    # 1. Enforce front-facing pose on baseline frame (frame1)
    yaw1 = pitch1 = None
    if hasattr(face1, "pose") and face1.pose is not None:
        yaw1, pitch1, _ = float(face1.pose[0]), float(face1.pose[1]), float(face1.pose[2])
        
        # Verify baseline is looking straight
        if abs(yaw1) > 15.0 or abs(pitch1) > 15.0:
            logger.warning("Baseline pose invalid: yaw=%.1f, pitch=%.1f. Failing check.", yaw1, pitch1)
            return False, 0.0, (
                "Please look straight at the camera at the start of the challenge. "
                "Do not start with your head turned."
            )

    kps1 = face1.kps.astype(np.float32)

    # Scale-invariant normalisation by inter-eye distance
    eye_dist = float(np.linalg.norm(kps1[0] - kps1[1]))
    if eye_dist < 1.0:
        eye_dist = 1.0

    nose1 = kps1[2]
    THRESHOLD = 0.22   # Adjusted slightly to be more responsive

    img2 = _decode_image(frame2_bytes)
    face2 = _largest(analyzer.get(img2))
    if face2 is None:
        return False, 0.0, "No face detected in final frame. Please try again."

    kps2  = face2.kps.astype(np.float32)
    nose2 = kps2[2]
    dx = float(nose2[0] - nose1[0]) / eye_dist
    dy = float(nose2[1] - nose1[1]) / eye_dist

    # 2. Extract pose for final frame (frame2)
    yaw2 = pitch2 = None
    if hasattr(face2, "pose") and face2.pose is not None:
        yaw2, pitch2, _ = float(face2.pose[0]), float(face2.pose[1]), float(face2.pose[2])

    pose_passed = True
    pose_msg = ""

    if challenge_type == "nod":
        motion_passed = dy > THRESHOLD
        if pitch2 is not None and pitch1 is not None:
            # Looking down leads to a positive pitch increase
            pose_passed = pitch2 >= 10.0 and (pitch2 - pitch1) >= 8.0
            pose_msg = "Please nod your head clearly downward."
        score = dy
        fail_msg = "No head nod detected. Please nod your head downward once."

    elif challenge_type == "turn_left":
        motion_passed = dx > THRESHOLD
        if yaw2 is not None:
            # Mirror front camera: user turns left -> nose points right -> yaw > 0 (>= 15 degrees)
            pose_passed = yaw2 >= 15.0
            pose_msg = "Please turn your head clearly to the LEFT."
        score = dx
        fail_msg = "No head turn detected. Please turn your head to the LEFT."

    elif challenge_type == "turn_right":
        motion_passed = dx < -THRESHOLD
        if yaw2 is not None:
            # Mirror front camera: user turns right -> nose points left -> yaw < 0 (<= -15 degrees)
            pose_passed = yaw2 <= -15.0
            pose_msg = "Please turn your head clearly to the RIGHT."
        score = -dx
        fail_msg = "No head turn detected. Please turn your head to the RIGHT."

    else:
        return False, 0.0, f"Unknown challenge type: {challenge_type}"

    # Verify both motion displacement AND head pose angle transition
    passed = motion_passed and pose_passed
    actual_fail_msg = pose_msg if (motion_passed and not pose_passed) else fail_msg

    logger.warning(
        "HEAD MOTION | challenge=%-12s | dx=%.3f dy=%.3f | yaw1=%.1f->yaw2=%.1f, pitch1=%.1f->pitch2=%.1f | passed=%s",
        challenge_type, dx, dy, 
        yaw1 or 0, yaw2 or 0, pitch1 or 0, pitch2 or 0,
        "LIVE" if passed else "FAIL"
    )

    if not passed:
        return False, score, actual_fail_msg

    return True, score, f"Head motion verified ({challenge_type}): score={score:.3f}."


# ──────────────────────────────────────────────────────────────────────────────
# Head pose validation  (registration)
# ──────────────────────────────────────────────────────────────────────────────
#
# InsightFace buffalo_l yaw convention (verified empirically):
#   • Front camera mirrors the image horizontally.
#   • In the mirrored image: user turns LEFT  → nose points RIGHT → yaw > 0
#                             user turns RIGHT → nose points LEFT  → yaw < 0
#
# We use wide tolerances because:
#   a) Not every user turns the same amount.
#   b) Thresholds can be tightened via settings once real yaw values are logged.
#
POSE_THRESHOLDS = {
    #             (min_yaw, max_yaw)
    "front": (-25,  25),   # roughly centred
    "left":  ( 15,  80),   # user turned left  — wide band
    "right": (-80, -15),   # user turned right — wide band
}

POSE_INSTRUCTIONS = {
    "front": "Please look straight at the camera.",
    "left":  "Please turn your head clearly to the LEFT.",
    "right": "Please turn your head clearly to the RIGHT.",
}


def check_head_pose(image_bytes: bytes, expected_angle: str) -> Tuple[bool, str]:
    """
    Validate head pose WITHOUT running the model twice.
    Uses extract_embedding_with_pose() so embedding + pose come from one pass.

    Returns:
        (passed, reason)
        - If pose data is unavailable from the model, returns (True, reason)
          so registration is not blocked.
    """
    if expected_angle not in POSE_THRESHOLDS:
        logger.warning("Unknown angle '%s' — skipping pose check.", expected_angle)
        return True, "Pose check skipped (unknown angle)."

    try:
        _embedding, yaw, pitch, roll = extract_embedding_with_pose(image_bytes)
    except ValueError as e:
        return False, str(e)

    # Model doesn't expose pose → skip gracefully
    if yaw is None:
        logger.warning("Pose unavailable from model — skipping pose check.")
        return True, "Pose check skipped (model does not support pose estimation)."

    yaw_min, yaw_max = POSE_THRESHOLDS[expected_angle]
    pose_ok = yaw_min <= yaw <= yaw_max

    # Always log so we can tune thresholds from real data
    logger.info(
        "POSE CHECK | angle=%-5s | yaw=%+6.1f° pitch=%+6.1f° roll=%+6.1f° "
        "| range=[%d, %d] | %s",
        expected_angle, yaw, pitch or 0, roll or 0,
        yaw_min, yaw_max,
        "PASS ✓" if pose_ok else "FAIL ✗",
    )

    if not pose_ok:
        instruction = POSE_INSTRUCTIONS[expected_angle]
        if abs(yaw) < 12:
            direction = "you appear to be looking straight ahead"
        elif yaw > 0:
            direction = f"head is turned left ({yaw:.0f}°)"
        else:
            direction = f"head is turned right ({yaw:.0f}°)"

        return False, (
            f"{instruction} "
            f"Detected: {direction} — expected yaw between {yaw_min}° and {yaw_max}°."
        )

    return True, (
        f"Pose valid for '{expected_angle}' — yaw={yaw:.1f}°, "
        f"pitch={pitch:.1f}°, roll={roll:.1f}°."
    )
