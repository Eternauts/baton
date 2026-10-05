import sys
import requests

def test_endpoint(url: str, filepath: str, api_key: str):
    print(f"Testing URL: {url} with file: {filepath}")
    
    try:
        with open(filepath, 'rb') as f:
            files = {'audio': (filepath, f)}
            headers = {'X-Aegis-Key': api_key}
            
            # optional form data
            data = {
                'client_request_id': 'local-test-01',
                'languages': 'auto',
                'asset_hints': 'P-201B'
            }
            
            response = requests.post(url, headers=headers, files=files, data=data)
            print(f"Status Code: {response.status_code}")
            
            try:
                print("Response Body:")
                print(response.json())
            except Exception:
                print(response.text)
                
    except FileNotFoundError:
        print(f"Error: File {filepath} not found.")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python test_script.py <URL> <path_to_audio_file> <aegis_api_key>")
        sys.exit(1)
        
    test_endpoint(sys.argv[1], sys.argv[2], sys.argv[3])
