# Linkstream Backend

A fast, lightweight FastAPI backend that wraps `yt-dlp` and `ffmpeg` to extract video formats and download media streams.

## 🚀 Why Render Was Not Finding the Dockerfile (Fixed!)

If you previously encountered the error **"Render is not finding the Dockerfile"** or build failures on Render, it happened because:
1. **Missing `requirements.txt` & Incorrect COPY paths**: The `Dockerfile` previously attempted to copy `backend/requirements.txt` and `backend/main.py`. However, `main.py` and `requirements.txt` reside in the root of this folder (`./`), not inside a `backend/` subdirectory. Furthermore, `requirements.txt` was missing.
2. **Root Directory Mismatch on Render**: If `linkstream-backend` was pushed as a subfolder inside a larger repository (like `linkstream/linkstream-backend`), Render by default checks the top-level root (`./`) for a `Dockerfile`.

### ✅ What We Fixed:
- Created the required `requirements.txt` (`fastapi`, `uvicorn`, `yt-dlp`, `starlette`).
- Fixed `Dockerfile` `COPY` paths to correctly copy `./requirements.txt` and `./main.py`.
- Added dynamic `$PORT` handling (`CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"`) so Render can bind dynamically to whichever port it assigns.
- Added `render.yaml` (Render Blueprint) so Render automatically configures the Docker environment and `Dockerfile` path correctly without guessing.

---

## 🛠️ How to Deploy on GitHub & Render

### Step 1: Push `linkstream-backend` to GitHub
If pushing `linkstream-backend` as its own dedicated GitHub repository:
```bash
cd linkstream-backend
git init -b main
git add .
git commit -m "Initial commit: Linkstream Dockerized backend"
git remote add origin https://github.com/YOUR_USERNAME/linkstream-backend.git
git push -u origin main -f
```

*(If pushing as part of a multi-folder repository containing both `linkstream` and `linkstream-backend`, simply commit and push the parent repository).*

### Step 2: Deploy on Render
You have two easy options on Render:

#### Option A: Using Blueprints (Automatic & Recommended)
1. In your Render Dashboard, click **New** → **Blueprint**.
2. Connect your `linkstream-backend` repository.
3. Render will automatically detect `render.yaml` and set up the Web Service (`runtime: docker`, exposed on port `8000`).

#### Option B: Manual Web Service Setup
1. In your Render Dashboard, click **New** → **Web Service**.
2. Connect your GitHub repository.
3. Choose **Docker** as the Runtime.
4. **Important**:
   - If your GitHub repository is **only** `linkstream-backend`: leave **Root Directory** empty (`.`) and **Dockerfile Path** as `./Dockerfile`.
   - If your GitHub repository is a monorepo/parent containing `linkstream-backend/`: set **Root Directory** to `linkstream-backend`.

---

## 💻 Running Locally

1. **Install FFmpeg** (Required by `yt-dlp` to merge video + audio):
   - **Windows**: Install via winget (`winget install Gyan.FFmpeg`) or chocolatey (`choco install ffmpeg`), and ensure `ffmpeg` is on your `PATH`.
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt install ffmpeg`

2. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the API Server**:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

The API will run at `http://localhost:8000`. Test endpoint: `http://localhost:8000/api/health` (`{"status": "ok"}`).
