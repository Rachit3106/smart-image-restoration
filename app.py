import base64
import os
import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


def remove_shadows_pipeline(img):
  background = cv2.GaussianBlur(img, (101, 101), 0)
  normalized = cv2.divide(img, background, scale=255.0)
  normalized_uint8 = normalized.astype(np.uint8)
  smoothed = cv2.bilateralFilter(
      normalized_uint8, d=9, sigmaColor=75, sigmaSpace=75
  )
  hsv = cv2.cvtColor(smoothed, cv2.COLOR_BGR2HSV)
  h, s, v = cv2.split(hsv)
  s = np.multiply(s.astype(np.float32), 1.3)
  s = np.clip(s, 0, 255).astype(np.uint8)
  clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
  v = clahe.apply(v)
  enhanced_hsv = cv2.merge((h, s, v))
  final_output = cv2.cvtColor(enhanced_hsv, cv2.COLOR_HSV2BGR)
  return final_output


def enhance_pipeline(img):
  try:
    # Step 1: Gentle denoising while preserving major edges
    denoised = cv2.bilateralFilter(img, d=7, sigmaColor=50, sigmaSpace=50)

    # Step 2: Stronger Unsharp Masking for maximum edge definition and clarity
    gaussian = cv2.GaussianBlur(denoised, (0, 0), 1.5)
    sharpened = cv2.addWeighted(denoised, 2.2, gaussian, -1.2, 0)

    # Step 3: High-contrast CLAHE enhancement on the Luminance channel to make details pop
    lab = cv2.cvtColor(sharpened, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l)
    merged = cv2.merge((enhanced_l, a, b))

    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
  except Exception as e:
    print(f"Error in enhance_pipeline: {e}")
    return img


def remove_object_sharp_patch(img, mask_img):
  if mask_img.shape[:2] != img.shape[:2]:
    mask_img = cv2.resize(
        mask_img,
        (img.shape[1], img.shape[0]),
        interpolation=cv2.INTER_NEAREST,
    )

  if len(mask_img.shape) == 3:
    mask_gray = cv2.cvtColor(mask_img, cv2.COLOR_BGR2GRAY)
  else:
    mask_gray = mask_img

  _, user_mask = cv2.threshold(mask_gray, 50, 255, cv2.THRESH_BINARY)
  kernel = np.ones((5, 5), np.uint8)
  user_mask = cv2.dilate(user_mask, kernel, iterations=2)

  base_inpainted = cv2.inpaint(
      img, user_mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA
  )

  smooth_patch = cv2.bilateralFilter(
      base_inpainted, d=15, sigmaColor=75, sigmaSpace=75
  )
  smooth_patch = cv2.GaussianBlur(smooth_patch, (11, 11), 0)

  mask_float = (
      cv2.GaussianBlur(user_mask.astype(np.float32), (15, 15), 0) / 255.0
  )
  mask_3ch = cv2.merge([mask_float, mask_float, mask_float])

  result = (
      img.astype(np.float32) * (1.0 - mask_3ch)
      + smooth_patch.astype(np.float32) * mask_3ch
  )
  return np.clip(result, 0, 255).astype(np.uint8)


@app.route("/")
def index():
  return render_template("index.html")


@app.route("/process", methods=["POST"])
def process_image():
  try:
    file = request.files.get("image")
    action = request.form.get("action")
    mask_file = request.files.get("mask")

    if not file:
      return jsonify({"error": "No image uploaded"}), 400

    npimg = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)

    if action == "shadow":
      result = remove_shadows_pipeline(img)
    elif action == "enhance":
      result = enhance_pipeline(img)
    elif action == "remove_object" and mask_file:
      npmask = np.frombuffer(mask_file.read(), np.uint8)
      mask_img = cv2.imdecode(npmask, cv2.IMREAD_COLOR)
      result = remove_object_sharp_patch(img, mask_img)
    else:
      result = img

    _, buffer = cv2.imencode(".jpg", result)
    encoded_image = base64.b64encode(buffer).decode("utf-8")
    return jsonify({"processed_image": f"data:image/jpeg;base64,{encoded_image}"})
  except Exception as e:
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
  app.run(debug=True, port=5000)