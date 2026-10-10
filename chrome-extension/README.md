# Archon CRM - LinkedIn Companion Chrome Extension

An enterprise-grade Manifest V3 Chrome Extension that connects LinkedIn directly to your local Archon CRM (PocketBase).

---

## 🌟 Key Features

1. **DOM Profile Scraper**: Automatically extracts Full Name, Job Title, Company, Location, Profile Image URL, and LinkedIn URL from `https://www.linkedin.com/in/*`.
2. **Interactive Profile Widget**: Injects a dark-glassmorphism badge directly onto LinkedIn profile headers:
   - **New Leads**: 1-Click "+ In Archon CRM speichern" button.
   - **Existing Contacts**: Displays active CRM status (`🤝 Vernetzt`, `💬 Erstnachricht`, `⛔ Gesperrt (1 Jahr)`, etc.) with a live status dropdown to update status directly from LinkedIn!
3. **Popup Companion**:
   - Live PocketBase connection status indicator (`http://localhost:8090`).
   - Quick contact search across your CRM database directly from Chrome toolbar.
   - Active page inspector.
   - Custom server URL setting.

---

## 🛠️ Installation Guide

### Step 1: Open Extensions in Google Chrome
1. Open Google Chrome (or Edge / Brave / Vivaldi).
2. Navigate to `chrome://extensions` in the address bar.
3. Enable **Developer mode** using the toggle switch in the top-right corner.

### Step 2: Load Unpacked Extension
1. Click the **Load unpacked** button in the top-left.
2. Select the `chrome-extension/` folder located in your project directory:
   `C:\.Antigravity-projekte\AgenticOS-2026\chrome-extension`
3. Click **Select Folder**.

---

## 🚀 How to Use

1. Ensure Archon CRM / PocketBase is running on `http://localhost:8090`.
2. Open any LinkedIn profile page (e.g. `https://www.linkedin.com/in/some-profile/`).
3. Notice the **Archon CRM Status Widget** injected automatically right below the profile headline/buttons:
   - If the contact is not in your CRM, click **+ In Archon CRM speichern**.
   - If the contact already exists, select any status from the dropdown to instantly update your CRM database.
4. Click the extension icon in your Chrome toolbar to search existing contacts or adjust server settings.
