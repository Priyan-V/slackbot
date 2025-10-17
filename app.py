import os
import json
import tempfile
import base64
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock, DividerBlock
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import sendgrid
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition


# Environment setup

load_dotenv()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
VERIFIED_SENDER = os.getenv("VERIFIED_SENDER")

# Initialize Slack and Supabase

app = App(token=SLACK_BOT_TOKEN, signing_secret=os.getenv("SLACK_SIGNING_SECRET"))
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
model = SentenceTransformer("all-MiniLM-L6-v2")


def generate_pdf(results):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    c = canvas.Canvas(temp_file.name, pagesize=letter)
    width, height = letter
    y = height - 50

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, "Slackbot Content Report")
    y -= 40

    for res in results:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, f"Group: {res['group']}")
        y -= 20
        c.setFont("Helvetica", 12)
        c.drawString(60, y, f"Post Idea: {res['idea']}")
        y -= 20
        c.setFont("Helvetica", 11)
        text = c.beginText(60, y)
        for line in res['outline'].split("\n"):
            text.textLine(line)
            y -= 12
        c.drawText(text)
        y -= 30
        if y < 100:
            c.showPage()
            y = height - 50
    c.save()
    return temp_file.name


# Slack Commands
@app.command("/keywords")
def handle_keywords(ack, body, say):
    ack("Processing your keywords...")
    user = body["user_name"]
    say(f"👋 Hi {user}! Please upload a CSV or paste your keywords below.")

@app.event("message")
def handle_text_keywords(event, say):
    text = event.get("text", "")
    user = event.get("user")
    if "bot_id" in event or not text:
        return
    keywords = list(set([kw.strip().lower() for kw in text.split(",") if kw.strip()]))
    supabase.table("keywords").insert({"user_id": user, "raw_keywords": keywords, "cleaned_keywords": keywords}).execute()
    say(f"✅ Saved {len(keywords)} keywords for processing!")

@app.command("/groupkeywords")
def group_keywords(ack, say):
    ack("🔍 Grouping keywords...")
    try:
        response = supabase.table("keywords").select("cleaned_keywords").execute()
        all_keywords = [kw for r in response.data for kw in r.get("cleaned_keywords", [])]
        if not all_keywords:
            say("⚠️ No keywords found. Please run /keywords first.")
            return
        embeddings = model.encode(all_keywords, show_progress_bar=True)
        kmeans = KMeans(n_clusters=min(5, len(all_keywords)), random_state=42)
        labels = kmeans.fit_predict(embeddings)

        clusters = {}
        for i, label in enumerate(labels):
            clusters.setdefault(label, []).append(all_keywords[i])

        msg = "*🔗 Keyword Groups:*\n" + "\n".join([f"\n*Group {k + 1}:* {', '.join(v)}" for k, v in clusters.items()])
        say(msg)

        supabase.table("keyword_groups").insert({
            "groups": {str(k): v for k, v in clusters.items()},
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        say("✅ Keyword groups saved!")
    except Exception as e:
        say(f"⚠️ Error: {e}")

@app.command("/setemail")
def set_email(ack, body, say):
    ack("📧 Saving your email...")
    user_id = body["user_id"]
    email = body.get("text", "").strip()
    if "@" not in email:
        say("⚠️ Provide a valid email: `/setemail your_email@example.com`")
        return
    try:
        supabase.table("users").upsert({"user_id": user_id, "email": email}, on_conflict="user_id").execute()
        say(f"✅ Email `{email}` saved!")
    except Exception as e:
        say(f"⚠️ Failed to save email: {e}")

@app.command("/generateoutlines")
def generate_outlines(ack, body, say):
    ack("🧩 Generating outlines...")
    user_id = body["user_id"]

   
    response = supabase.table("keyword_groups").select("groups").order("created_at", desc=True).limit(1).execute()
    if not response.data:
        say("⚠️ No keyword groups found. Run /groupkeywords first.")
        return

    groups = response.data[0]["groups"]
    results = []

    for _, keywords in groups.items():
        topic = keywords[0]
        outline = f"""1. Introduction — Why {topic} matters
2. Key Benefits
3. Common Challenges
4. Best Practices
5. Conclusion — Next Steps"""
        idea = f"Create a blog post titled: 'Mastering {topic} — The Complete Guide'"
        results.append({"group": ", ".join(keywords), "outline": outline, "idea": idea})


    say("📘 *Generated Outlines:*")
    for res in results:
        outline_text = f"*Group:* {res['group']}\n🧠 *Idea:* {res['idea']}\n📄 *Outline:*\n{res['outline']}"
        say(text=outline_text)

    pdf_path = generate_pdf(results)
    say("📄 PDF report generated!")

    #Upload PDF to Slack DM
    try:
        dm = WebClient(token=SLACK_BOT_TOKEN).conversations_open(users=user_id)
        channel_id = dm["channel"]["id"]
        WebClient(token=SLACK_BOT_TOKEN).files_upload_v2(
            channel=channel_id,
            file=pdf_path,
            title="Content Report",
            initial_comment="Here’s your content report 📄"
        )
        say("✅ PDF uploaded to your Slack DM!")
    except Exception as e:
        say(f"⚠️ PDF upload error: {e}")

    # Send PDF via SendGrid email
    if SENDGRID_API_KEY and VERIFIED_SENDER:
        try:
            record = supabase.table("users").select("email").eq("user_id", user_id).execute()
            user_email = record.data[0]["email"] if record.data else None

            if not user_email:
                say("📧 No email found for this user. Please run `/setemail your_email@example.com` first.")
            else:
                import sendgrid
                from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition

                sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)

               
                with open(pdf_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode()

                
                attachment = Attachment()
                attachment.file_content = FileContent(encoded)
                attachment.file_type = FileType("application/pdf")
                attachment.file_name = FileName("ContentReport.pdf")
                attachment.disposition = Disposition("attachment")

                
                msg = Mail(
                    from_email=VERIFIED_SENDER,
                    to_emails=user_email,
                    subject="Your Content Report",
                    html_content="<strong>Your content report is attached.</strong>"
                )
                msg.attachment = attachment

                
                response = sg.send(msg)
                say(f"✉️ Email successfully sent to {user_email} (Status: {response.status_code})")

        except Exception as e:
            say(f"⚠️ Email send error: {e}")
    else:
        say("⚠️ SendGrid API key or sender email not configured — skipping email delivery.")

    supabase.table("outlines").insert({
        "results": results,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    print("[INFO] Outlines saved to Supabase.")



@app.command("/history")
def history(ack, body, say):
    ack("📜 Fetching your history...")
    response = supabase.table("outlines").select("results", "created_at").order("created_at", desc=True).limit(10).execute()
    if not response.data:
        say("⚠️ No history found.")
        return
    message = "*📄 Last 10 keyword batches:*\n"
    for r in response.data:
        message += f"\n• {r['created_at']}: {', '.join([x['group'] for x in r['results']])}"
    say(message)

# Entry point
if __name__ == "__main__":
    print("🚀 Starting Slackbot...")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
