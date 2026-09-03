# Parser Validation & Analytics Platform

A high-performance validation, DeepDiff, and analytics platform for comparing Parser V1 vs V3 outputs from MongoDB collections.

---

## 🚀 Cloud Deployment


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
