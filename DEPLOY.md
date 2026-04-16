# Deploying Cobblestone Pub Manager to Render

Follow these steps in order. Budget ~30 minutes.

## What you'll need
- A GitHub account (free) — to store the code
- A Render account (free to sign up) — to host it
- Your Square access token (already in your local `.env`)
- A username + password you want to use to log in

---

## Step 1 — Create a GitHub account and repo (5 min)

1. Go to https://github.com/signup — create account if you don't have one
2. Go to https://github.com/new — create a new repository
   - **Name:** `cobblestone-pub` (or anything you like)
   - **Visibility:** **Private** (critical — code has no secrets in it, but better to keep it private)
   - Don't add README, .gitignore, or license
   - Click "Create repository"
3. **Leave the page open** — you'll need the URL in the next step

---

## Step 2 — Push the code to GitHub (5 min)

Open Terminal on your Mac and run:

```bash
cd "/Users/sorayakhaljemcmahon/Documents/Claude/Projects/Cobblestone Work/cobblestone-pub"
git init
git add .
git commit -m "Initial deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/cobblestone-pub.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your actual GitHub username.

If git prompts for username/password, use your GitHub username and a **personal access token** (not your password). Generate one at https://github.com/settings/tokens → "Generate new token (classic)" → check `repo` scope → copy the token and paste it as the password.

---

## Step 3 — Create Render account + connect GitHub (5 min)

1. Go to https://render.com → sign up (easiest: "Sign up with GitHub")
2. Once signed in, click **"New +"** → **"Blueprint"**
3. Connect your GitHub account if prompted
4. Select the `cobblestone-pub` repository
5. Render will detect `render.yaml` and show the service configuration — click **"Apply"**

---

## Step 4 — Set your secrets (3 min)

After clicking Apply, Render creates the service but needs three secrets from you. You'll see a form asking for them, OR go to the service's **Environment** tab:

| Variable | Value |
|----------|-------|
| `SQUARE_ACCESS_TOKEN` | Copy from your local `.env` file |
| `AUTH_USERNAME` | Pick any username (e.g. `soraya`) |
| `AUTH_PASSWORD` | Pick a strong password — save it in your password manager |

Click **"Save Changes"**. Render will deploy the app (~3 minutes).

---

## Step 5 — Access your app (1 min)

Once the deploy finishes (green "Live" badge), click the URL at the top of the Render page. It'll look like:

```
https://cobblestone-pub.onrender.com
```

Your browser will prompt for the username/password you set. Enter them → done.

**Bookmark this URL** on every device you want to use (your phone, work computer, etc.).

---

## Optional — Use a custom subdomain (5 min)

If you want `pub.yourdomain.com` instead of `cobblestone-pub.onrender.com`:

1. In Render, go to your service → **Settings** → **Custom Domains** → **Add Custom Domain**
2. Enter e.g. `pub.cobblestonepub.com`
3. Render gives you a CNAME target (something like `cobblestone-pub.onrender.com`)
4. Go to your Squarespace/domain dashboard → DNS settings
5. Add a CNAME record: `pub` → `cobblestone-pub.onrender.com`
6. Wait 5-30 min for DNS to propagate — Render auto-issues SSL

---

## Troubleshooting

**Deploy fails on Render:**
- Check the build logs in Render dashboard
- Most likely: `requirements.txt` missing a package

**Can't log in:**
- Double-check `AUTH_USERNAME` and `AUTH_PASSWORD` in Render's Environment tab (no typos)
- Try incognito/private browsing mode to clear cached credentials

**Database empty after deploy:**
- Render deploys wipe the container but the `/var/data` persistent disk survives
- First deploy starts fresh — your PTO/tips data will build up over time
- If you want to migrate your local database, use Render's shell tab to upload `cobblestone.db`

**Square data not loading:**
- Check `SQUARE_ACCESS_TOKEN` is set in Render environment
- Check Render logs tab for any errors

---

## After deployment

The app auto-deploys when you push new code to GitHub's `main` branch. If I make updates to the app:

```bash
cd "/Users/sorayakhaljemcmahon/Documents/Claude/Projects/Cobblestone Work/cobblestone-pub"
git add .
git commit -m "Describe the change"
git push
```

Render picks it up and redeploys automatically within ~2 minutes.

---

## Cost summary

- GitHub: **Free**
- Render Starter plan: **$7/month** (always-on, fast, 1GB persistent disk)
- Custom domain: **Free** (Render gives free SSL)

**Total: $7/month**
