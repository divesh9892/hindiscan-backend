# HindiScan Load Testing

## 1. How to Generate the Auth Token

We use Clerk Custom JWT Templates to generate a 60-minute token without altering the backend.

1. Run the Next.js frontend locally (`npm run dev`).
2. Log into the local dashboard using a dedicated test account.
3. Open the browser DevTools (F12) -> Console.
4. Run this exact command:
   ```javascript
   await window.Clerk.session.getToken({ template: "load_test_token" });
   ```
5. Copy the output string (without the quotes).

## 2. How to Run k6

Run this command from the root backend directory, passing the token via the `-e` flag:

```bash
k6 run -e CLERK_TEST_JWT="your_token_here" -e API_URL="https://hindiscan-backend.onrender.com/api/v1" tests/load/load_test.js
```
