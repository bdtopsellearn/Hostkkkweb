# 💳 Merchant API Setup Guide (OxaPay)

This guide explains how to integrate **OxaPay** into your Lord Cipher hosting platform for automated crypto payments.

---

## 1. Get Your OxaPay API Key
1.  **Create an Account:** Sign up at [OxaPay.com](https://oxapay.com/).
2.  **Merchant Dashboard:** Go to your Merchant Dashboard.
3.  **Create Merchant:** Create a new merchant profile for your bot.
4.  **Copy API Key:** Locate your **Merchant API Key** (usually looks like `XXXXXX-XXXXXX-XXXXXX-XXXXXX`).

---

## 2. Configure Environment Variables
Add your key to your `.env` file or your hosting provider's environment settings:

```env
OXAPAY_API_KEY=YOUR_MERCHANT_KEY_HERE
```

*   **Railway:** Go to Variables -> New Variable -> `OXAPAY_API_KEY`.
*   **VPS:** Edit your `.env` file and restart the bot.

---

## 3. Enable Automatic Payments
Once the key is set, you can manage payment modes via the **Admin Panel**:

1.  Open the **Admin Panel** in your bot.
2.  Navigate to **🔘 Payment Modes**.
3.  Ensure **Automatic Mode** is set to **✅ ON**.
    *   **Blue/Primary:** Manual payments (User sends proof).
    *   **Green/Success:** Automatic payments (OxaPay generates links).

---

## 4. How It Works
*   **Automatic:** When a user selects a plan, the bot calls the OxaPay API to create an invoice. The user receives a "Pay Now" link. Once the crypto transaction is confirmed on the blockchain, OxaPay notifies your bot, and the plan is activated **instantly**.
*   **Manual:** Users send a screenshot of their payment. Admins must manually verify and approve the request in the **Pending Payments** section.

---

## 5. Troubleshooting
*   **"Failed to create invoice":** Ensure your `OXAPAY_API_KEY` is correct and your OxaPay merchant account is active.
*   **Payments not reflecting:** Ensure your bot has a public URL configured in the Admin Panel so OxaPay can send webhook notifications.
*   **API Timeout:** If you are on a VPS, ensure your firewall allows outgoing requests to `api.oxapay.com`.

---

**Note:** For security, never share your Merchant API Key with anyone. Admins can view the status of all transactions in the **Analytics** section of the Admin Panel. 🛡️🔐✅
