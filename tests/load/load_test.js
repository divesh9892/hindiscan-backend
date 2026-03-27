import http from "k6/http";
import { check, sleep } from "k6";
import { FormData } from "https://jslib.k6.io/formdata/0.0.2/index.js";

// 1. ENTERPRISE CONFIGURATION
export const options = {
  stages: [
    { duration: "10s", target: 5 }, // Ramp up to 5 users
    { duration: "30s", target: 15 }, // 🚀 LOWERED SPIKE: 15 concurrent users
    { duration: "10s", target: 0 }, // Cool down
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"], // Test fails if >1% of requests fail
    http_req_duration: ["p(95)<1500"], // 95% of uploads must complete under 1.5s
  },
};

// 2. ENVIRONMENT VARIABLES (Passed via command line)
const API_BASE_URL =
  __ENV.API_URL || "https://hindiscan-api.onrender.com/api/v1";
const CLERK_TOKEN = __ENV.CLERK_TEST_JWT;

// Ensure you have a real 'test_image.jpg' sitting next to this script!
const MOCK_FILE_CONTENT = open("./test_image.jpg", "b");

export default function () {
  // -------------------------------------------------------------
  // STEP 1: UPLOAD THE DOCUMENT
  // -------------------------------------------------------------
  const fd = new FormData();
  fd.append("file", http.file(MOCK_FILE_CONTENT, "test_doc.jpg", "image/jpeg"));
  fd.append("extract_tables_only", "true");
  fd.append("use_legacy_font", "false");

  const uploadParams = {
    headers: {
      Authorization: `Bearer ${CLERK_TOKEN}`,
      "Content-Type": `multipart/form-data; boundary=${fd.boundary}`,
    },
    timeout: "30s",
  };

  const uploadRes = http.post(
    `${API_BASE_URL}/extract/`,
    fd.body(),
    uploadParams,
  );

  let hasTaskId = false;
  let taskId = null;

  if (uploadRes.status === 200) {
    try {
      const parsedBody = JSON.parse(uploadRes.body);
      if (parsedBody.task_id) {
        hasTaskId = true;
        taskId = parsedBody.task_id; // ✅ ID captured securely
      }
    } catch (e) {
      console.error(`Failed to parse successful response: ${uploadRes.body}`);
    }
  } else {
    console.error(
      `🚨 UPLOAD FAILED! Status: ${uploadRes.status} | Body: ${uploadRes.body}`,
    );
  }

  check(uploadRes, {
    "upload status is 200": (r) => r.status === 200,
    "has task_id": () => hasTaskId === true,
  });

  if (!hasTaskId) {
    return; // Gracefully stop this virtual user's journey if the upload failed
  }

  // -------------------------------------------------------------
  // STEP 2: SIMULATE FRONTEND POLLING
  // -------------------------------------------------------------
  let extractionComplete = false;
  let attempts = 0;
  const maxAttempts = 15; // Don't poll forever

  const pollParams = {
    headers: { Authorization: `Bearer ${CLERK_TOKEN}` },
  };

  while (!extractionComplete && attempts < maxAttempts) {
    sleep(2);

    const statusRes = http.get(
      `${API_BASE_URL}/extract/status/${taskId}`,
      pollParams,
    );

    check(statusRes, {
      "status check is 200": (r) => r.status === 200,
    });

    if (statusRes.status === 200) {
      const statusData = JSON.parse(statusRes.body);
      if (statusData.status === "completed" || statusData.status === "failed") {
        extractionComplete = true;
      }
    }
    attempts++;
  }
}
