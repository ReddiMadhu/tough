import urllib.request
import urllib.parse
import json
import time
import mimetypes
import uuid
from pathlib import Path

def encode_multipart_formdata(files):
    boundary = uuid.uuid4().hex
    CRLF = '\r\n'
    L = []
    for field_name, file_path in files:
        file_path = Path(file_path)
        L.append('--' + boundary)
        L.append(f'Content-Disposition: form-data; name="files"; filename="{file_path.name}"')
        content_type = mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
        L.append(f'Content-Type: {content_type}')
        L.append('')
        with open(file_path, 'rb') as f:
            L.append(f.read())
    L.append('--' + boundary + '--')
    L.append('')
    body = b''
    for item in L:
        if isinstance(item, str):
            body += item.encode('utf-8') + CRLF.encode('utf-8')
        else:
            body += item + CRLF.encode('utf-8')
    content_type = f'multipart/form-data; boundary={boundary}'
    return content_type, body

def run_test():
    url = "http://127.0.0.1:8000/api/v1/ts-migration/upload"
    
    # Upload demo TML files
    demo_dir = Path("demo_data")
    file_names = [
        "Table_Customers.tml",
        "Table_Products.tml",
        "Table_Sales.tml",
        "Model_SalesAnalysis.tml",
        "Liveboard_ExecutiveDashboard.tml"
    ]
    files = [("files", str(demo_dir / name)) for name in file_names]
    
    content_type, body = encode_multipart_formdata(files)
    
    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', content_type)
    
    print("Uploading TML files to API...")
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode('utf-8')
            res_json = json.loads(res_data)
            print("Upload response:", json.dumps(res_json, indent=2))
            migration_id = res_json["migration_id"]
    except Exception as e:
        print("Upload failed:", e)
        return

    # Poll status
    status_url = f"http://127.0.0.1:8000/api/v1/ts-migration/{migration_id}"
    print(f"Polling migration status for: {migration_id}...")
    for _ in range(10):
        req = urllib.request.Request(status_url)
        try:
            with urllib.request.urlopen(req) as response:
                res_data = response.read().decode('utf-8')
                res_json = json.loads(res_data)
                print(f"Status: {res_json['status']} ({res_json.get('elapsed_seconds')}s)")
                if res_json["status"] in ("completed", "failed"):
                    if res_json["status"] == "failed":
                        print("Error:", res_json.get("error_message"))
                    break
        except Exception as e:
            print("Poll status failed:", e)
        time.sleep(1)

    # Fetch conversions
    conv_url = f"http://127.0.0.1:8000/api/v1/ts-migration/{migration_id}/conversions"
    req = urllib.request.Request(conv_url)
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode('utf-8')
            res_json = json.loads(res_data)
            print(f"Found {len(res_json.get('conversions', []))} conversions.")
    except Exception as e:
        print("Failed to fetch conversions:", e)

if __name__ == "__main__":
    run_test()
