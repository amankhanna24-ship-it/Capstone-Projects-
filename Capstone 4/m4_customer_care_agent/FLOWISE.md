# Optional: the same agent as a Flowise chatflow

Flowise is a drag-and-drop builder for LangChain agents. The Python agent is the main deliverable. Use this if your course wants to see Flowise, or if you'd like a visual version to demo.

Flowise's screens change between versions, so if a label below doesn't match exactly, look for the nearest equivalent.

## 1. Start both servers
Terminal 1 (in this project, venv active):
```bash
uvicorn mock_api:app --port 8000
```
Terminal 2 (needs Node.js 18+; install from nodejs.org if `node -v` fails):
```bash
npx flowise start
```
Open http://localhost:3000.

## 2. Create the tools
**Tools → Create** for each tool. Use the same name and description as `tools.py` so the model behaves the same way. Here's `get_order` as a worked example.

- **Name:** `get_order`
- **Description:** `Get an order's status, items, total and any refunds.`
- **Input schema:** one property `order_id`, type string, required
- **JavaScript function:**
```javascript
const id = String($order_id).trim().toUpperCase();
if (!/^NS-\d{5}$/.test(id)) {
  return JSON.stringify({ error: "VALIDATION_ERROR", details: "order_id must look like NS-12345" });
}
const res = await fetch(`http://localhost:8000/orders/${id}`, {
  headers: { "X-Customer-Id": "CUST-0002" }
});
return JSON.stringify(await res.json());
```
Repeat the same pattern for `get_shipping_status` (`/orders/${id}/shipping`) and `check_refund_eligibility` (`/orders/${id}/refund-eligibility?reason=${$reason}`). Validate `reason` against the five allowed values first.

For `issue_refund`, send a `POST` to `/orders/${id}/refund` with a body of `{amount, reason, approved_by}`. Check that `amount` is above 0 and no more than 5000 before calling.

## 3. Build the chatflow
**Chatflows → Add New**, then drag in:
- **ChatOpenAI**: model `gpt-4o-mini`, temperature 0.1
- **Tool Agent**: connect the model, plus each Custom Tool node (pick your tools)
- **Memory**: an Upstash Redis-backed chat memory node if your version has one (use the same URL and token as `.env`), otherwise Buffer Memory

Paste the `SYSTEM_PROMPT` rules from `agent.py` into the agent's system message.

## 4. Human approval
If your Flowise version has a **Require Human Input** option on tools or agent nodes, switch it on for `issue_refund` and `cancel_order`. If it doesn't, leave the write tools out of the Flowise version and say so in your write-up. The Python agent's gate and audit log are the real HITL deliverable either way.

## 5. What to screenshot
The canvas with all nodes connected, and one chat where the agent looks up `NS-10004` and checks eligibility.
