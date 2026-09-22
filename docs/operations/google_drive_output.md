# Google Drive Output - Team Setup

The SVCS dashboard can auto-route demo outputs to a shared Google Drive folder so
the sponsor can view compressed video clips without anyone needing to send files
manually.

## Shared folder

https://drive.google.com/drive/folders/1r032XVGXJeUYDZrw4eDdyXwZYCsbiH99

## One-time setup (each team machine)

1. **Install Google Drive for Desktop** (if not already installed)
   https://drive.google.com/drive/download

2. **Add the shared folder to your Drive**
   - Open the link above in Chrome while signed in to your FAU Google account
   - Click the folder name → **Organize** → **Add shortcut to Drive**
   - Choose **My Drive** as the destination and confirm

3. **Let Drive for Desktop sync** - the shared folder will now appear inside your
   local `My Drive` folder (usually `G:\My Drive\SVCS\` on Windows).

## Using it in the dashboard

1. Open the SVCS dashboard - the **Save To** field auto-fills with the detected
   Google Drive path (`…\My Drive\SVCS`) on page load
2. Start the pipeline - every saved segment syncs to Google Drive automatically
3. Click **🔗 View in Drive** at any time to open the shared folder in the browser

> **Note:** Files typically appear in Drive within 10-30 seconds of being saved.

## How detection works

The 📁 Drive button calls `/api/gdrive/detect`, which checks the Windows registry
(`HKCU\Software\Google\DriveFS\PerAccountPreferences`) for the mount point path,
then falls back to common default locations (`G:\My Drive`, `%USERPROFILE%\Google Drive`,
etc.). If Drive for Desktop is not installed the button shows an install link.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Google Drive for Desktop not found" | Install from the link above |
| Path fills but files don't appear in Drive | Check Drive for Desktop is running (system tray) |
| Wrong Google account synced | Sign in to your FAU account in Drive for Desktop |
| Subfolder missing in sponsor view | Make sure you added a shortcut from the shared folder link |
