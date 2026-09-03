# Parser Validation & Analytics Platform

A high-performance validation, DeepDiff, and analytics platform for comparing Parser V1 vs V3 outputs from MongoDB collections.

---

## 🚀 Cloud Deployment

### Deploy on Render (Recommended)

1. **Push to GitHub**:
   ```bash
   git add .
   git commit -m "Initial commit for deployment"
   git branch -M main
   git remote add origin <your-github-repo-url>
   git push -u origin main
   ```

2. **Deploy on Render**:
   - Log in to [Render](https://render.com/).
   - Click **New +** -> **Web Service**.
   - Connect your GitHub repository.
   - Render will automatically detect [`render.yaml`](render.yaml) or you can set:
     - **Runtime**: Python 3
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `uvicorn core.main:app --host 0.0.0.0 --port $PORT`
   - Click **Create Web Service**.

> **Note on MongoDB in the Cloud**:  
> When deployed to Render or Railway, the server cannot connect to your laptop's `mongodb://localhost:27017`. Use a cloud database connection string like **MongoDB Atlas** (`mongodb+srv://<user>:<password>@cluster.mongodb.net/`) or a remotely accessible MongoDB instance.

---

### Deploy on Railway

1. Log in to [Railway](https://railway.app/).
2. Click **New Project** -> **Deploy from GitHub repo**.
3. Select your repository. Railway will detect the [`Procfile`](Procfile) and [`requirements.txt`](requirements.txt) or the [`Dockerfile`](Dockerfile) and build automatically.

---

## 🐳 Docker Deployment

To build and run as a Docker container locally or on a VPS / Cloud VM:

```bash
# Build image
docker build -t parser-validation-platform .

# Run container
docker run -d -p 8000:8000 --name parser-platform parser-validation-platform
```

Access the UI at `http://localhost:8000`.

---

## 💻 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run server with auto-reload
uvicorn core.main:app --reload --host 0.0.0.0 --port 8000
```
