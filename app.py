import os
import io
import json
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
from slack_sdk.models.blocks import SectionBlock, DividerBlock

# Optional Google Sheets logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# PDF & Email
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import tempfile
import sendgrid
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
import base64

# -----------------------------
# Load env vars
# -----------------------------
load_dotenv()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
VERIFIED_SENDER = os.getenv("VERIFIED_SENDER")  # Must be verified in SendGrid

# -----------------------------
# Initialize Slack
# -----------------------------
app = App(token=SLACK_BOT_TOKEN, signing_secret=os.getenv("SLACK_SIGNING_SECRET"))

# -----------------------------
# Connect Supabase
# -----------------------------
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# -----------------------------
# Embedding model
# -----------------------------
model = SentenceTransformer("all-MiniLM-L6-v2")

# -----------------------------
# Google Sheets (optional)
# -----------------------------
GOOGLE_SHEET = None
if os.path.exists("service_account.json"):
    scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    client_gs = gspread.authorize(creds)
    GOOGLE_SHEET = client_gs.open("Slackbot_Content_Report").sheet1

# -----------------------------
# PDF Generation
# -----------------------------
def generate_pdf(results):
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    c = canvas.Canvas(tmp_file.name, pagesize=letter)
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
        y -= 20
        if y < 100:
            c.showPage()
            y = height - 50
    c.save()
    return tmp_file.name

# -----------------------------
# /keywords command
# -----------------------------
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

    keywords = [kw.strip().lower() for kw in text.split(",") if kw.strip()]
    keywords = list(set(keywords))  # Deduplicate

    supabase.table("keywords").insert({
        "user_id": user,
        "raw_keywords": keywords,
        "cleaned_keywords": keywords
    }).execute()
    say(f"✅ Saved {len(keywords)} cleaned keywords for processing!")

# -----------------------------
# /groupkeywords command
# -----------------------------
@app.command("/groupkeywords")
def group_keywords(ack, say):
    ack("🔍 Grouping keywords based on semantic similarity...")
    try:
        response = supabase.table("keywords").select("cleaned_keywords").execute()
        all_keywords = []
        for record in response.data:
            if record["cleaned_keywords"]:
                all_keywords.extend(record["cleaned_keywords"])
        if not all_keywords:
            say("⚠️ No keywords found. Please run /keywords first.")
            return
        embeddings = model.encode(all_keywords, show_progress_bar=True)
        n_clusters = min(5, len(all_keywords))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        labels = kmeans.fit_predict(embeddings)
        clusters = {}
        for i, label in enumerate(labels):
            clusters.setdefault(label, []).append(all_keywords[i])

        # Display Slack blocks
        result_msg = "*🔗 Keyword Groups:*\n"
        for group_id, words in clusters.items():
            result_msg += f"\n*Group {group_id + 1}:* {', '.join(words)}"
        say(result_msg)

        # Save to Supabase
        clusters_json_safe = {str(int(k)): v for k, v in clusters.items()}
        supabase.table("keyword_groups").insert({
            "groups": clusters_json_safe,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        say("✅ Keyword groups saved successfully!")
    except Exception as e:
        say(f"⚠️ Error: {e}")

# -----------------------------
# /setemail command
# -----------------------------
@app.command("/setemail")
def set_email(ack, body, say):
    ack("📧 Saving your email...")
    user_id = body["user_id"]
    email_input = body.get("text", "").strip()
    if "@" not in email_input or "." not in email_input:
        say("⚠️ Provide a valid email: `/setemail your_email@example.com`")
        return
    try:
        supabase.table("users").upsert({
            "user_id": user_id,
            "email": email_input
        }, on_conflict="user_id").execute()
        say(f"✅ Your email `{email_input}` has been saved!")
    except Exception as e:
        say(f"⚠️ Failed to save email: {e}")

# -----------------------------
# /generateoutlines command
# -----------------------------
@app.command("/generateoutlines")
def generate_outlines(ack, body, say):
    ack("🧩 Generating outlines and post ideas...")
    user_id = body["user_id"]

    # Fetch latest keyword groups
    response = supabase.table("keyword_groups").select("groups").order("created_at", desc=True).limit(1).execute()
    if not response.data:
        say("⚠️ No keyword groups found. Run /groupkeywords first.")
        return

    groups = response.data[0]["groups"]
    results = []

    for group_id, keywords in groups.items():
        query = ", ".join(keywords)
        outline = f"""
1. Introduction — Why {keywords[0]} matters
2. Key Benefits of {keywords[0]}
3. Common Challenges
4. Best Practices
5. Conclusion — Next Steps
        """
        idea = f"Create a blog post titled: 'Mastering {keywords[0]} — The Complete Guide'"
        results.append({"group": query, "outline": outline.strip(), "idea": idea})

    # Slack blocks
    blocks = [SectionBlock(text="*📘 Generated Outlines & Ideas:*").to_dict(), DividerBlock().to_dict()]
    for res in results:
        blocks.append(SectionBlock(text=f"*Group:* {res['group']}").to_dict())
        blocks.append(SectionBlock(text=f"🧠 *Post Idea:* {res['idea']}").to_dict())
        blocks.append(SectionBlock(text=f"📄 *Outline:*\n{res['outline']}").to_dict())
        blocks.append(DividerBlock().to_dict())
    say(blocks=blocks)

    # PDF
    pdf_path = generate_pdf(results)
    say("📄 Your PDF report has been generated!")

    # Slack DM upload
    from slack_sdk import WebClient
    client = WebClient(token=SLACK_BOT_TOKEN)
    try:
        dm = client.conversations_open(users=user_id)
        dm_channel_id = dm["channel"]["id"]
        client.files_upload_v2(
            channel=dm_channel_id,
            file=pdf_path,
            title="Content Report",
            initial_comment="Here’s your generated content report 📄"
        )
        say("✅ PDF uploaded to your Slack DM!")
    except Exception as e:
        say(f"⚠️ Error uploading PDF: {e}")

    # SendGrid email
    if SENDGRID_API_KEY and VERIFIED_SENDER:
        try:
            user_record = supabase.table("users").select("email").eq("user_id", user_id).execute()
            user_email = user_record.data[0]["email"] if user_record.data else None
            if user_email:
                sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
                with open(pdf_path, "rb") as f:
                    encoded_file = base64.b64encode(f.read()).decode()
                attachment = Attachment(
                    file_content=FileContent(encoded_file),
                    file_type=FileType("application/pdf"),
                    file_name=FileName("ContentReport.pdf"),
                    disposition=Disposition("attachment")
                )
                message = Mail(
                    from_email=VERIFIED_SENDER,
                    to_emails=user_email,
                    subject="Your Slackbot Content Report",
                    html_content="<strong>Your generated content report is attached.</strong>"
                )
                message.attachment = attachment
                response = sg.send(message)
                print("SendGrid response:", response.status_code, response.body, response.headers)
                say(f"✉️ PDF report emailed to {user_email}")
            else:
                say("📧 Set your email using `/setemail your_email@example.com` to receive PDF via email")
        except Exception as e:
            say(f"⚠️ Failed to send email: {e}")

    # Save outlines to Supabase
    try:
        supabase.table("outlines").insert({"results": results, "created_at": datetime.utcnow().isoformat()}).execute()
    except Exception as e:
        say(f"⚠️ Error saving outlines: {e}")

    # Google Sheets logging (optional)
    if GOOGLE_SHEET:
        try:
            GOOGLE_SHEET.append_row([user_id, datetime.utcnow().isoformat(), json.dumps(results)])
        except Exception as e:
            print("Google Sheets log error:", e)

    say("✅ Outline generation complete!")

# -----------------------------
# /refine command
# -----------------------------
@app.command("/refine")
def refine_outline(ack, body, say):
    ack("🔄 Refining your last generated outline...")
    user_id = body["user_id"]

    response = supabase.table("outlines").select("results").order("created_at", desc=True).limit(1).execute()
    if not response.data:
        say("⚠️ No previous outlines found. Run /generateoutlines first.")
        return

    last_results = response.data[0]["results"]
    refined_results = []
    for res in last_results:
        refined_outline = res["outline"] + "\n\n*Refined version: Add more examples and subpoints*"
        refined_results.append({"group": res["group"], "outline": refined_outline, "idea": res["idea"]})

    blocks = [SectionBlock(text="*🔧 Refined Outlines:*").to_dict(), DividerBlock().to_dict()]
    for res in refined_results:
        blocks.append(SectionBlock(text=f"*Group:* {res['group']}").to_dict())
        blocks.append(SectionBlock(text=f"🧠 *Post Idea:* {res['idea']}").to_dict())
        blocks.append(SectionBlock(text=f"📄 *Outline:*\n{res['outline']}").to_dict())
        blocks.append(DividerBlock().to_dict())
    say(blocks=blocks)

    pdf_path = generate_pdf(refined_results)
    say("📄 Refined PDF generated!")

# -----------------------------
# /history command
# -----------------------------
@app.command("/history")
def history(ack, body, say):
    ack("📜 Fetching your history...")
    user_id = body["user_id"]

    response = supabase.table("outlines").select("results", "created_at").order("created_at", desc=True).limit(10).execute()
    if not response.data:
        say("⚠️ No history found.")
        return

    message = "*📄 Last 10 processed keyword batches:*\n"
    for record in response.data:
        created = record["created_at"]
        groups = ", ".join([r["group"] for r in record["results"]])
        message += f"\n• {created}: {groups}"
    say(message)

# -----------------------------
# Start Slackbot
# -----------------------------
if __name__ == "__main__":
    print("🚀 Starting Slackbot...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
