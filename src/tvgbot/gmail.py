# pip install google-auth google-auth-oauthlib google-api-python-client
# https://console.cloud.google.com/marketplace/product/google/gmail.googleapis.com
# https://console.cloud.google.com/auth
# ADD test users: https://console.cloud.google.com/auth/audience
# Create: Desktop App

from dotenv import load_dotenv

assert load_dotenv()
import base64
import os
from email import policy
from email.mime.text import MIMEText
from email.parser import BytesParser

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_credentials(save_file="credentials.json"):
    # TODO: this runs on machine with browser only
    config = {
        "installed": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(config, scopes=SCOPES)
    credentials = flow.run_local_server(port=0)
    with open(save_file, "w") as f:
        f.write(credentials.to_json())
    return credentials


class GmailClient:
    def __init__(self, credentials="credentials.json"):
        credentials = Credentials.from_authorized_user_file(credentials, SCOPES)
        self.service = build("gmail", "v1", credentials=credentials).users().messages()

    def send_email(self, to, subject, body):
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        cmd = self.service.send(userId="me", body={"raw": raw})
        cmd.execute()

    def read_email(self, id):
        cmd = self.service.get(userId="me", id=id, format="raw")
        response = cmd.execute()
        response = base64.urlsafe_b64decode(response["raw"])
        response = BytesParser(policy=policy.default).parsebytes(response)
        if response.is_multipart():
            body = None
            for part in response.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content()
                    break
        else:
            body = part.get_content()

        return {
            "id": id,
            "from": response.get("from"),
            "to": response.get("to"),
            "subject": response.get("subject"),
            "body": body,
        }

    def list_emails(self, query=None, max_results=10):
        cmd = self.service.list(userId="me", q=query, maxResults=max_results)
        print(cmd)
        response = cmd.execute().get("messages", [])
        print(response)
        return [self.read_email(info["id"]) for info in response]
