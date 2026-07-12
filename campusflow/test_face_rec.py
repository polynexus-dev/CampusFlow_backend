import os
import django

# Setup Django configuration
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
django.setup()

from campusflow_app.face_utils import (
    extract_embedding,
    compare_embeddings,
    check_head_pose
)

def run_test():
    print("==================================================")
    print("CampusFlow Biometrics Local Integration Test")
    print("==================================================")

    # Path to test images
    test_images_dir = "D:/Polynexus/Servers/Campusnexus/New folder/campusflow_mobile_new/test_images"
    
    front_path = os.path.join(test_images_dir, "front.png")
    left_path = os.path.join(test_images_dir, "left.png")
    right_path = os.path.join(test_images_dir, "right.png")

    if not (os.path.exists(front_path) and os.path.exists(left_path) and os.path.exists(right_path)):
        print(f"Error: One or more test images not found in {test_images_dir}")
        return

    # 1. Load Images
    print("1. Loading test images...")
    with open(front_path, "rb") as f:
        front_bytes = f.read()
    with open(left_path, "rb") as f:
        left_bytes = f.read()
    with open(right_path, "rb") as f:
        right_bytes = f.read()
    print("✓ Images loaded successfully.")

    # 2. Test Pose Validation (check_head_pose)
    print("\n2. Running Pose Angle checks...")
    for angle, img_bytes in [("front", front_bytes), ("left", left_bytes), ("right", right_bytes)]:
        passed, reason = check_head_pose(img_bytes, angle)
        status = "PASS ✓" if passed else "FAIL ✗"
        print(f"   [{angle.upper()}] Pose check: {status} | Detail: {reason}")

    # 3. Test Embedding Extraction
    print("\n3. Extracting face embeddings...")
    try:
        front_emb = extract_embedding(front_bytes)
        print("   ✓ Front embedding extracted.")
        left_emb = extract_embedding(left_bytes)
        print("   ✓ Left embedding extracted.")
        right_emb = extract_embedding(right_bytes)
        print("   ✓ Right embedding extracted.")
    except Exception as e:
        print(f"   ✗ Extraction failed: {e}")
        return

    # 4. Compare Embeddings
    print("\n4. Running Face Similarity Matching...")
    # Compare front against itself (should match perfectly)
    is_match, score, index = compare_embeddings(front_emb, [front_emb])
    print(f"   [Front vs Front] Match: {is_match} | Similarity Score: {score:.4f}")

    # Compare front against side angles (should show moderate to high similarity since it's the same person)
    is_match_left, score_left, _ = compare_embeddings(front_emb, [left_emb])
    print(f"   [Front vs Left] Match: {is_match_left} | Similarity Score: {score_left:.4f}")

    is_match_right, score_right, _ = compare_embeddings(front_emb, [right_emb])
    print(f"   [Front vs Right] Match: {is_match_right} | Similarity Score: {score_right:.4f}")

    print("\n==================================================")
    print("Biometrics Local Integration Test Complete.")
    print("==================================================")

if __name__ == "__main__":
    run_test()
