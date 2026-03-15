# 🇮🇳 HindiScan Enterprise Backend 🚀

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Clerk](https://img.shields.io/badge/Clerk-6C47FF?style=for-the-badge&logo=clerk&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)

An asynchronous, highly scalable Python backend designed for extracting complex Hindi tables and text from PDFs and Images using Google's Gemini Flash. Built from the ground up with enterprise-grade architecture, strict stateless memory management, and secure payment handling.

## ✨ Core Architecture Features

- **Asynchronous AI Pipeline:** Leverages `asyncio` and `BackgroundTasks` to prevent long-running Gemini API calls from blocking the main FastAPI event loop, enabling high concurrency.
- **Stateless Task Engine:** Extraction tickets are managed via a robust PostgreSQL database, making the application 100% immune to multi-worker (Gunicorn) memory fragmentation and server reboots.
- **Out-of-Band Garbage Collection:** Features a highly secure, cron-triggered HTTP endpoint that automatically sweeps and shreds temporary workspaces and expired JSON/Excel artifacts to prevent memory leaks.
- **Deep Payload Unwrapper:** Implements aggressive `while`-loop parsing to safely decode double or triple-stringified JSON payloads sent from complex frontend code editors.
- **Enterprise Adapter Pattern:** Razorpay payments are mocked via a strict Gateway Adapter. This allows instant swapping to live production keys with zero API route changes.
- **Idempotent Webhooks:** Database-level Row Locking (`with_for_update`) completely prevents concurrent double-spend attacks and race conditions on the billing ledger.

## 🛠️ Tech Stack

- **Framework:** FastAPI
- **Database:** Neon Serverless PostgreSQL + SQLAlchemy (AsyncPG)
- **Authentication:** Clerk + JWT RSA Cryptography
- **AI Engine:** Google Gemini 2.5 Flash
- **Document Processing:** PyMuPDF (`fitz`) & OpenPyXL
- **Testing:** Pytest & FastAPI TestClient

---

## 🚀 Local Development Setup

### 1. Clone the Repository

git clone https://github.com/divesh9892/hindiscan-backend.git
cd hindiscan-backend

### 2. Create a Virtual Environment

python -m venv venv

# On Windows:

venv\Scripts\activate

# On macOS/Linux:

source venv/bin/activate

### 3. Install Dependencies

pip install -r requirements.txt

### 4. Configure Environment Variables

Create a `.env` file in the root directory and configure the following absolute requirements:

# AI & Database

GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql+asyncpg://user:password@ep-cool-snowflake-123.ap-southeast-1.aws.neon.tech/dbname

# Authentication (Clerk)

CLERK_SECRET_KEY=your_clerk_secret_key
CLERK_PUBLIC_KEY=your_clerk_public_key

# Payments (Test Mode)

USE_MOCK_PAYMENTS=True
RAZORPAY_KEY_ID=your_razorpay_test_id
RAZORPAY_KEY_SECRET=your_razorpay_test_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# Infrastructure Security

CRON_SECRET=dev_secret_123

### 5. Initialize the Database

Before booting the server for the first time, build the PostgreSQL tables:
python init_db.py

### 6. Run the Server

Boot the async server using Uvicorn:
uvicorn app.main:app --reload --port 8400

The API documentation will be instantly available at `http://localhost:8400/docs`.

---

## 🧪 Automated Testing

This repository maintains a strict Pytest suite covering the AI vault bypass logic, billing schemas, auth gateways, and async dependencies.

To run the entire suite locally:
pytest -v

_(Note: A GitHub Actions workflow is also configured to run this suite automatically on every push to the main branch.)_

---

## 🧹 Manual Garbage Collection

To test the out-of-band garbage collector locally, use cURL or Postman to ping the secure endpoint. It requires the `X-Cron-Secret` header to match your `.env` file.

curl -X POST http://localhost:8400/api/v1/extract/garbage-collect \
 -H "X-Cron-Secret: dev_secret_123"
