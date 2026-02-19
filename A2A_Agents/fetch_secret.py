
from google.cloud import secretmanager
import os

# Set project ID (ensure you are authenticated via gcloud auth application-default login)
PROJECT_ID = "kpmgpoc"
SECRET_ID = "remote-agent-api-key"
VERSION_ID = "latest"

def access_secret_version(project_id, secret_id, version_id="latest"):
    """
    Access the payload for the given secret version if one exists.
    """
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    
    try:
        response = client.access_secret_version(request={"name": name})
        payload = response.payload.data.decode("UTF-8")
        print(f"✅ Successfully accessed secret '{secret_id}' (version {version_id})")
        print(f"🔑 Secret Value: {payload}")
        return payload
    except Exception as e:
        print(f"❌ Failed to access secret: {e}")
        return None

if __name__ == "__main__":
    print(f"[*] Attempting to fetch secret '{SECRET_ID}' from project '{PROJECT_ID}'...")
    access_secret_version(PROJECT_ID, SECRET_ID, VERSION_ID)
