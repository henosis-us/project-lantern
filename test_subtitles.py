
import pytest
import requests
import subprocess
import time
import os
import logging

# --- Test Configuration ---
BASE_URL = "http://localhost:8000"
# This token is expired, but the server doesn't seem to be validating it yet.
# In a real scenario, we would need a way to generate a valid token for testing.
VALID_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJoZW5vc2lzIiwiZXhwIjoxNzUyMDc3MDcwfQ.sdDHPwRAymBbHx5_bMzfmFNeOlKrphWd6m5ubjoVIxY"
HEADERS = {"Authorization": f"Bearer {VALID_TOKEN}"}

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@pytest.fixture(scope="module")
def server():
    """Fixture to start and stop the FastAPI server."""
    logging.info("Starting FastAPI server in test mode...")
    env = os.environ.copy()
    env["LANTERN_TEST_MODE"] = "true"
    server_process = subprocess.Popen(
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
        env=env
    )
    time.sleep(5) # Give the server time to start
    logging.info("FastAPI server started.")
    yield
    logging.info("Stopping FastAPI server...")
    server_process.terminate()

def get_first_movie_id():
    """Helper to get the ID of the first movie from the library."""
    response = requests.get(f"{BASE_URL}/library/movies", headers=HEADERS)
    response.raise_for_status()
    movies = response.json()
    if not movies:
        pytest.fail("Test requires at least one movie in the library.")
    return movies[0]['id']

def get_first_subtitle_for_movie(movie_id):
    """Helper to get the first available subtitle for a movie."""
    response = requests.get(f"{BASE_URL}/subtitles/{movie_id}?item_type=movie", headers=HEADERS)
    response.raise_for_status()
    subtitles = response.json()
    if not subtitles:
        # If no subtitles, we can try to download one.
        # This is a more complex test, for now we assume one exists.
        pytest.fail(f"Test requires at least one subtitle for movie ID {movie_id}.")
    return subtitles[0]

def test_subtitle_playback_flow(server):
    """
    Tests the subtitle playback flow from the perspective of a client.
    1. Fetches the first movie.
    2. Fetches the first available subtitle for that movie.
    3. Requests a stream with that subtitle selected.
    4. Verifies the response contains a valid soft subtitle URL.
    5. Fetches the subtitle file from the URL and validates its content and headers.
    """
    logging.info("--- Starting Subtitle Playback Flow Test ---")

    # Step 1: Get a movie to test with
    logging.info("Step 1: Fetching a movie ID...")
    movie_id = get_first_movie_id()
    logging.info(f"Found movie with ID: {movie_id}")

    # Step 2: Get a subtitle for that movie
    logging.info(f"Step 2: Fetching subtitles for movie {movie_id}...")
    subtitle = get_first_subtitle_for_movie(movie_id)
    subtitle_id = subtitle['id']
    logging.info(f"Found subtitle with ID: {subtitle_id} ({subtitle.get('name', 'N/A')})")

    # Step 3: Request a stream with the subtitle
    stream_params = {
        "item_type": "movie",
        "subtitle_id": subtitle_id,
        "force_transcode": "true" # Force transcode to ensure we get a soft_sub_url
    }
    logging.info(f"Step 3: Requesting stream for movie {movie_id} with subtitle {subtitle_id}...")
    stream_response = requests.get(f"{BASE_URL}/stream/{movie_id}", params=stream_params, headers=HEADERS)
    
    logging.info(f"Stream request URL: {stream_response.url}")
    assert stream_response.status_code == 200, f"Failed to start stream. Status: {stream_response.status_code}, Body: {stream_response.text}"
    
    stream_data = stream_response.json()
    logging.info(f"Stream response data: {stream_data}")

    # Step 4: Verify the soft_sub_url
    logging.info("Step 4: Verifying the 'soft_sub_url' in the response...")
    assert "soft_sub_url" in stream_data, "Response JSON is missing 'soft_sub_url'"
    soft_sub_url = stream_data["soft_sub_url"]
    assert soft_sub_url, "'soft_sub_url' should not be null or empty"
    logging.info(f"Received soft_sub_url: {soft_sub_url}")

    # The URL from the backend already includes the token, so we don't need to add it again.
    # It should be a relative path like '/static/subtitles/movie/1/1.vtt?token=...'
    subtitle_file_url = f"{BASE_URL}{soft_sub_url}"

    # Step 5: Fetch the subtitle file and validate
    logging.info(f"Step 5: Fetching the VTT file from {subtitle_file_url}...")
    # We don't pass the auth headers here because the token is in the URL
    sub_response = requests.get(subtitle_file_url)
    
    logging.info("--- Subtitle File Response ---")
    logging.info(f"Status Code: {sub_response.status_code}")
    logging.info("Headers:")
    for key, value in sub_response.headers.items():
        logging.info(f"  {key}: {value}")

    assert sub_response.status_code == 200, f"Failed to fetch the VTT file. Status: {sub_response.status_code}"
    
    # Check for CORS headers, which are crucial for browser clients
    assert "Access-Control-Allow-Origin" in sub_response.headers, "CORS header 'Access-Control-Allow-Origin' is missing!"
    
    # Check the content of the file
    vtt_content = sub_response.text
    logging.info("VTT File Content (first 100 chars):")
    logging.info(vtt_content[:100])
    assert "WEBVTT" in vtt_content, "The downloaded file does not appear to be a valid VTT subtitle file."
    
    logging.info("--- Subtitle Playback Flow Test PASSED ---")

if __name__ == "__main__":
    # This allows running the test directly with `python test_subtitles.py`
    pytest.main(["-v", __file__])
