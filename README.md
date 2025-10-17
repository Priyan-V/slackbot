# Slackbot Content Assistant

A Python-based Slackbot that helps users generate content ideas and outlines based on keywords, group them intelligently, and receive PDF reports via Slack or email.

# Features

- `/keywords` – Add keywords for content ideas
- `/groupkeywords` – Groups keywords using embeddings + KMeans
- `/generateoutlines` – Generates blog post outlines and ideas
- PDF report generation
- Slack DM delivery of reports
- Optional email delivery using SendGrid
- View history of generated outlines

# Prerequisites

- Python 3.10+
- Slack App with bot token and app token
- Supabase project
- SendGrid account (optional)
- Optional: Docker
# Architecture

1. **Slack Bot Commands** → Triggers Python backend
2. **Supabase** → Stores user keywords, groups, and outlines
3. **Sentence Transformers + KMeans** → Groups keywords intelligently
4. **ReportLab** → Generates PDF reports
5. **Slack SDK** → Uploads PDFs to user DM
6. **SendGrid** → Sends PDF via email

# Environment Variables (`.env`)

SLACK_BOT_TOKEN=your-slack-bot-token
SLACK_APP_TOKEN=your-slack-app-token
SLACK_SIGNING_SECRET=your-signing-secret
SUPABASE_URL=your-supabase-url
SUPABASE_KEY=your-supabase-key
SENDGRID_API_KEY=your-sendgrid-api-key
VERIFIED_SENDER=verified-email@example.com
