from flask import Flask, request, jsonify, Response
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter
import os
import tempfile # For handling temporary cookie file
import logging # For better logging

app = Flask(__name__)
# Configure logging for Flask app (Gunicorn will also capture this)
app.logger.setLevel(logging.INFO)
app.logger.info("Flask app initialized.")

# --- Read Proxy from Environment Variable ---
PROXY_URL_FROM_ENV = os.environ.get('PROXY_URL')
if PROXY_URL_FROM_ENV:
    # Log only the host part for security if it's a full URL with auth
    proxy_display = PROXY_URL_FROM_ENV.split('@')[-1] if '@' in PROXY_URL_FROM_ENV else PROXY_URL_FROM_ENV
    app.logger.info(f"Proxy URL found in environment: {proxy_display}")
else:
    app.logger.info("No PROXY_URL environment variable set. Operating without proxy.")

# --- Helper Function to Create a Temporary Cookie File ---
def get_cookie_file_path():
    """
    Checks for cookie content in an environment variable,
    writes it to a temporary file, and returns the file path.
    Returns None if no cookie content is found.
    """
    cookie_content = os.environ.get('YOUTUBE_COOKIES_CONTENT')
    if cookie_content:
        try:
            # Create a named temporary file so we can pass its path
            # delete=False means we handle deletion manually in a finally block
            # Ensure the temp directory is writable on Railway (default temp dir should be)
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as tmp_cookie_file:
                tmp_cookie_file.write(cookie_content)
                app.logger.info(f"Temporary cookie file created at: {tmp_cookie_file.name}")
                return tmp_cookie_file.name # Return the path to the temp file
        except Exception as e:
            app.logger.error(f"Error creating temporary cookie file: {e}", exc_info=True)
            return None
    return None

# --- Helper Function to delete files safely ---
def safe_delete_file(file_path):
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            app.logger.info(f"Successfully deleted temporary file: {file_path}")
        except Exception as e_del:
            app.logger.error(f"Error deleting temporary file {file_path}: {e_del}", exc_info=True)

@app.route('/')
def home():
    return "Welcome to the YouTube Transcript API service! Use /api/transcript?video_id=YOUR_VIDEO_ID to get a transcript. Add &format=text for plain text."

@app.route('/api/transcript', methods=['GET'])
def get_transcript_api():
    video_id = request.args.get('video_id')
    output_format = request.args.get('format', 'json').lower()

    if not video_id:
        app.logger.warning("Missing 'video_id' parameter in request.")
        return jsonify({"error": "Missing 'video_id' parameter in the URL"}), 400

    app.logger.info(f"Request received for video_id: {video_id}, format: {output_format}")

    temp_cookie_file_path = None
    # Store original proxy env vars if they exist, to restore later
    original_http_proxy = os.environ.get('HTTP_PROXY')
    original_https_proxy = os.environ.get('HTTPS_PROXY')
    proxies_set_by_this_request = False

    try:
        # --- Apply Proxy Settings if PROXY_URL_FROM_ENV is set ---
        if PROXY_URL_FROM_ENV:
            os.environ['HTTP_PROXY'] = PROXY_URL_FROM_ENV
            os.environ['HTTPS_PROXY'] = PROXY_URL_FROM_ENV
            proxies_set_by_this_request = True
            proxy_display = PROXY_URL_FROM_ENV.split('@')[-1] if '@' in PROXY_URL_FROM_ENV else PROXY_URL_FROM_ENV
            app.logger.info(f"Set HTTP_PROXY and HTTPS_PROXY for this request using: {proxy_display}")
        else:
            # Ensure they are unset if no proxy is configured for this app
            # This prevents a previous request's proxy from lingering if PROXY_URL_FROM_ENV was removed
            if 'HTTP_PROXY' in os.environ: del os.environ['HTTP_PROXY']
            if 'HTTPS_PROXY' in os.environ: del os.environ['HTTPS_PROXY']
            app.logger.info("Proceeding without setting HTTP_PROXY/HTTPS_PROXY environment variables for this request.")


        # --- Get Transcript using YouTubeTranscriptApi ---
        temp_cookie_file_path = get_cookie_file_path() # Get path to temp cookie file if env var is set
        
        transcript_api_kwargs = {}
        if temp_cookie_file_path:
            transcript_api_kwargs['cookies'] = temp_cookie_file_path
            app.logger.info(f"Attempting to list transcripts for {video_id} using cookies from: {temp_cookie_file_path}")
        else:
            app.logger.info(f"Attempting to list transcripts for {video_id} without cookies.")
        
        # youtube-transcript-api should now pick up the HTTP_PROXY/HTTPS_PROXY env vars if set
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, **transcript_api_kwargs)
        
        # Using your preferred languages list from the original script
        preferred_languages = ['en', 'ro', 'es', 'de', 'fr', 'pt', 'it', 'nl', 'ja', 'ko', 'ru', 'zh-Hans', 'zh-Hant', 'hi', 'ar']
        # Prioritize RO then EN as discussed for the other API
        # preferred_languages_ordered = ['ro', 'en'] 
        # For this API, we'll stick to your original broader list for now, but ordered for preference
        # You can adjust this order if needed. Let's try RO, EN first.
        search_langs_manual = ['ro', 'en'] + [lang for lang in preferred_languages if lang not in ['ro', 'en']]
        search_langs_auto = ['ro', 'en'] + [lang for lang in preferred_languages if lang not in ['ro', 'en']]


        transcript_to_fetch_obj = None # To store the transcript object
        fetched_lang_type = None

        try:
            app.logger.info(f"Trying to find manually created transcript in {search_langs_manual} for {video_id}...")
            transcript_to_fetch_obj = transcript_list.find_manually_created_transcript(search_langs_manual)
            fetched_lang_type = "manual"
            app.logger.info(f"Found manually created transcript in language: {transcript_to_fetch_obj.language}")
        except NoTranscriptFound:
            app.logger.info(f"No manually created transcript found in preferred languages for {video_id}. Trying auto-generated...")
            try:
                transcript_to_fetch_obj = transcript_list.find_generated_transcript(search_langs_auto)
                fetched_lang_type = "auto-generated"
                app.logger.info(f"Found auto-generated transcript in language: {transcript_to_fetch_obj.language}")
            except NoTranscriptFound:
                app.logger.warning(f"No transcript found (manual or auto) in preferred languages for video: {video_id}")
                return jsonify({"error": "No transcript found in the preferred languages for this video.", "video_id": video_id}), 404
        
        transcript_data_segments = transcript_to_fetch_obj.fetch()
        detected_language = transcript_to_fetch_obj.language + (f" ({fetched_lang_type})" if fetched_lang_type else "")
        
        if output_format == 'text':
            formatter = TextFormatter()
            plain_text_transcript = formatter.format_transcript(transcript_data_segments)
            return Response(plain_text_transcript, mimetype='text/plain; charset=utf-8')
        else: 
            return jsonify({
                "video_id": video_id,
                "language_detected": detected_language,
                "transcript_format": "structured_json",
                "transcript": transcript_data_segments
            })

    except TranscriptsDisabled:
        app.logger.warning(f"Transcripts are disabled for video: {video_id}")
        return jsonify({"error": "Transcripts are disabled for this video.", "video_id": video_id}), 403
    except NoTranscriptFound: # General fallback if specific searches fail unexpectedly
        app.logger.warning(f"NoTranscriptFound (general) for video: {video_id}")
        return jsonify({"error": "No transcript available for this video ID (it might be invalid, private, deleted, or have no captions for specified languages).", "video_id": video_id}), 404
    except Exception as e:
        app.logger.error(f"An unexpected error occurred in get_transcript_api for {video_id}: {e}", exc_info=True)
        return jsonify({"error": f"An server-side error occurred: {str(e)}", "video_id": video_id}), 500
    finally:
        safe_delete_file(temp_cookie_file_path) # Clean up temp cookie file if it was created
        # Restore original proxy settings or unset if they were set by this request
        if proxies_set_by_this_request: # Only if we modified them
            if original_http_proxy:
                os.environ['HTTP_PROXY'] = original_http_proxy
            elif 'HTTP_PROXY' in os.environ: # If it was set by us and not originally
                del os.environ['HTTP_PROXY']
            
            if original_https_proxy:
                os.environ['HTTPS_PROXY'] = original_https_proxy
            elif 'HTTPS_PROXY' in os.environ: # If it was set by us and not originally
                del os.environ['HTTPS_PROXY']
            app.logger.info("Restored original HTTP_PROXY/HTTPS_PROXY environment variables for this request.")

if __name__ == "__main__":
    # For local testing, you might want to set YOUTUBE_COOKIES_CONTENT and PROXY_URL
    # Example: 
    # os.environ['YOUTUBE_COOKIES_CONTENT'] = "..." 
    # os.environ['PROXY_URL'] = "http://user:pass@host:port"
    
    app.logger.info("--- Starting YouTube Transcript API (Flask Development Server) ---")
    port = int(os.environ.get("PORT", 8081)) # Use a different port if 5001 is for the other API
    app.run(host='0.0.0.0', port=port, debug=True)
