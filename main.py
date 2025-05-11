from flask import Flask, request, jsonify, Response, send_from_directory, url_for
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter
from pytube import YouTube as PytubeYouTube # Alias to avoid confusion
from pytube.exceptions import PytubeError as PytubeLibError # Specific Pytube errors
import os
import tempfile 
import uuid 
import logging
import traceback # For more detailed error logging

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# --- Configuration for Temporary Transcript Text Files ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEXT_TRANSCRIPTS_TEMP_DIR = os.path.join(BASE_DIR, "api_text_transcripts_temp")

if not os.path.exists(TEXT_TRANSCRIPTS_TEMP_DIR):
    os.makedirs(TEXT_TRANSCRIPTS_TEMP_DIR)
    app.logger.info(f"Created temporary text transcripts directory: {TEXT_TRANSCRIPTS_TEMP_DIR}")

# --- Read Proxy from Environment Variable ---
PROXY_URL_FROM_ENV = os.environ.get('PROXY_URL')
if PROXY_URL_FROM_ENV:
    proxy_display = PROXY_URL_FROM_ENV.split('@')[-1] if '@' in PROXY_URL_FROM_ENV else PROXY_URL_FROM_ENV
    app.logger.info(f"Proxy URL found in environment: {proxy_display}")
else:
    app.logger.info("No PROXY_URL environment variable set. Operating without proxy.")

# --- Helper Function for Cookie File ---
def get_cookie_file_path():
    cookie_content = os.environ.get('YOUTUBE_COOKIES_CONTENT')
    if cookie_content:
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt', dir=TEXT_TRANSCRIPTS_TEMP_DIR) as tmp_cookie_file:
                tmp_cookie_file.write(cookie_content)
                app.logger.info(f"Temporary cookie file created at: {tmp_cookie_file.name}")
                return tmp_cookie_file.name
        except Exception as e:
            app.logger.error(f"Error creating temporary cookie file: {e}")
            return None
    return None

# --- Helper Function to delete files safely ---
def safe_delete_file(file_path):
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            app.logger.info(f"Successfully deleted temporary file: {file_path}")
        except Exception as e_del:
            app.logger.error(f"Error deleting temporary file {file_path}: {e_del}")

@app.route('/')
def home():
    return "Welcome to the YouTube Info API! Use /api/video_info?video_id=YOUR_VIDEO_ID"

@app.route('/api/video_info', methods=['GET'])
def get_video_info_api():
    video_id = request.args.get('video_id')
    if not video_id:
        return jsonify({"error": "Missing 'video_id' parameter"}), 400

    video_url = f"https://www.google.com/url?sa=E&source=gmail&q=https://youtube-audio-transcriber-production.up.railway.app/api/extract_audio?url=https://youtu.be/mG4XXtpuSlk?si=j1Cj0bw5Muo_xuhI"

    response_data = {
        "video_id": video_id,
        "video_title": None,
        "channel_name": None,
        "transcript_download_url": None,
        "error": None
    }
    
    temp_cookie_file_path = None
    temp_transcript_text_file_path = None
    
    original_http_proxy = os.environ.get('HTTP_PROXY')
    original_https_proxy = os.environ.get('HTTPS_PROXY')

    try:
        pytube_proxies = None
        if PROXY_URL_FROM_ENV:
            pytube_proxies = {'http': PROXY_URL_FROM_ENV, 'https': PROXY_URL_FROM_ENV}
            os.environ['HTTP_PROXY'] = PROXY_URL_FROM_ENV
            os.environ['HTTPS_PROXY'] = PROXY_URL_FROM_ENV
            app.logger.info(f"Set HTTP_PROXY and HTTPS_PROXY for this request using: {PROXY_URL_FROM_ENV.split('@')[-1] if '@' in PROXY_URL_FROM_ENV else PROXY_URL_FROM_ENV}")
        else:
            if 'HTTP_PROXY' in os.environ: del os.environ['HTTP_PROXY']
            if 'HTTPS_PROXY' in os.environ: del os.environ['HTTPS_PROXY']

        # 1. Get Title and Channel using Pytube
        try:
            app.logger.info(f"Attempting to initialize PytubeYouTube with URL: {video_url} and proxies: {pytube_proxies is not None}")
            yt_pytube = PytubeYouTube(video_url, proxies=pytube_proxies)
            
            app.logger.info(f"PytubeYouTube object created. Attempting to fetch title for video ID: {video_id}")
            response_data["video_title"] = yt_pytube.title # This line forces metadata fetch
            app.logger.info(f"Successfully fetched title: '{response_data['video_title']}'. Attempting to fetch author...")
            response_data["channel_name"] = yt_pytube.author
            app.logger.info(f"Pytube fetched Title: '{response_data['video_title']}', Channel: '{response_data['channel_name']}'")
        
        except PytubeLibError as pe: # Catch specific Pytube library errors
            error_msg = f"Pytube library error fetching metadata for {video_id}: {type(pe).__name__} - {str(pe)}"
            app.logger.error(error_msg, exc_info=False) # Log specific Pytube error, no need for full traceback if it's a known type
            # Don't set response_data["error"] here yet, allow transcript fetching to proceed if desired
            # but log that title/channel might be missing.
            app.logger.warning("Pytube metadata fetch failed. Title/Channel may be null.")
        except Exception as e_pytube_general: # Catch other potential errors during Pytube interaction
            # This is where "no element found" might be caught if it's from pytube's internal parsing
            error_msg = f"General error during Pytube metadata fetch for {video_id}: {type(e_pytube_general).__name__} - {str(e_pytube_general)}"
            app.logger.error(error_msg)
            # Log the full traceback for unexpected errors from pytube
            app.logger.error(f"Pytube General Error Traceback: {traceback.format_exc()}")
            app.logger.warning("Pytube metadata fetch failed due to a general error. Title/Channel may be null.")


        # 2. Get Transcript using YouTubeTranscriptApi
        # (The rest of this section remains the same as before)
        temp_cookie_file_path = get_cookie_file_path()
        transcript_api_kwargs = {}
        if temp_cookie_file_path:
            transcript_api_kwargs['cookies'] = temp_cookie_file_path
            app.logger.info(f"Attempting to list transcripts for {video_id} using cookies.")
        else:
            app.logger.info(f"Attempting to list transcripts for {video_id} without cookies.")
        
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, **transcript_api_kwargs)
        
        preferred_languages = ['ro', 'en'] 
        transcript_to_fetch_data = None
        fetched_lang = None

        for lang in preferred_languages:
            try:
                app.logger.info(f"Trying to find '{lang}' transcript for {video_id}...")
                transcript_obj = transcript_list.find_transcript([lang])
                transcript_to_fetch_data = transcript_obj.fetch()
                fetched_lang = lang
                app.logger.info(f"Found and fetched '{lang}' transcript for {video_id}.")
                break 
            except NoTranscriptFound:
                app.logger.info(f"No '{lang}' transcript found for {video_id}.")
                continue 
        
        if not transcript_to_fetch_data: 
            app.logger.info(f"No manual transcript in {preferred_languages}. Trying auto-generated for {video_id}...")
            for lang in preferred_languages:
                try:
                    transcript_obj = transcript_list.find_generated_transcript([lang])
                    transcript_to_fetch_data = transcript_obj.fetch()
                    fetched_lang = f"{lang} (auto-generated)"
                    app.logger.info(f"Found and fetched auto-generated '{lang}' transcript for {video_id}.")
                    break
                except NoTranscriptFound:
                    app.logger.info(f"No auto-generated '{lang}' transcript for {video_id}.")
                    continue
        
        if not transcript_to_fetch_data:
            # If Pytube already had an error, we don't want to overwrite it unless this is a new, more specific error
            if not response_data["error"]: # Only set this if no prior error from Pytube was critical
                 response_data["error"] = "No transcript found in Romanian or English (manual or auto-generated)."
            app.logger.warning(response_data["error"] + f" for video ID: {video_id}")
            # If title/channel was null AND no transcript, then it's a full 404 for useful data
            if response_data["video_title"] is None and response_data["channel_name"] is None:
                 return jsonify(response_data), 404
            else: # Still return data we have, but with error for transcript part
                 return jsonify(response_data), 200 # Or 206 Partial Content if preferred

        formatter = TextFormatter()
        plain_text_transcript = formatter.format_transcript(transcript_to_fetch_data)
        
        temp_transcript_filename = f"transcript_{video_id}_{uuid.uuid4().hex[:8]}.txt"
        temp_transcript_text_file_path = os.path.join(TEXT_TRANSCRIPTS_TEMP_DIR, temp_transcript_filename)
        
        with open(temp_transcript_text_file_path, 'w', encoding='utf-8') as f:
            f.write(plain_text_transcript)
        app.logger.info(f"Plain text transcript saved to temporary file: {temp_transcript_text_file_path}")

        response_data["transcript_download_url"] = url_for('serve_plain_text_transcript', 
                                                           filename=temp_transcript_filename, 
                                                           _external=True)
        response_data["language_detected"] = fetched_lang
        
        return jsonify(response_data), 200

    except TranscriptsDisabled:
        response_data["error"] = "Transcripts are disabled for this video."
        app.logger.warning(response_data["error"] + f" for video ID: {video_id}")
        return jsonify(response_data), 403 # Use 403 as it's a specific "forbidden" like state
    except NoTranscriptFound: 
        response_data["error"] = "No transcript available for this video ID (overall)."
        app.logger.warning(response_data["error"] + f" for video ID: {video_id}")
        return jsonify(response_data), 404
    except Exception as e: # Catch-all for other unexpected errors
        # This is where the "no element found" might end up if it's not caught by Pytube specific exceptions
        # and if it happens after Pytube init but before youtube-transcript-api calls.
        error_msg_final = f"An unexpected server-side error occurred: {type(e).__name__} - {str(e)}"
        app.logger.error(f"Unexpected error in get_video_info_api for {video_id}: {e}", exc_info=True)
        response_data["error"] = error_msg_final
        return jsonify(response_data), 500
    finally:
        safe_delete_file(temp_cookie_file_path)
        if PROXY_URL_FROM_ENV: 
            if original_http_proxy: os.environ['HTTP_PROXY'] = original_http_proxy
            elif 'HTTP_PROXY' in os.environ: del os.environ['HTTP_PROXY']
            if original_https_proxy: os.environ['HTTPS_PROXY'] = original_https_proxy
            elif 'HTTPS_PROXY' in os.environ: del os.environ['HTTPS_PROXY']
            app.logger.info("Restored original HTTP_PROXY/HTTPS_PROXY environment variables.")


@app.route('/serve_text_transcript/<filename>')
def serve_plain_text_transcript(filename):
    app.logger.info(f"Request to serve plain text transcript: {filename}")
    file_path_to_serve = os.path.join(TEXT_TRANSCRIPTS_TEMP_DIR, filename)
    try:
        if not os.path.exists(file_path_to_serve):
            app.logger.error(f"Temporary transcript file not found for serving: {file_path_to_serve}")
            return jsonify({"error": "Transcript file not found or already served."}), 404

        response = send_from_directory(TEXT_TRANSCRIPTS_TEMP_DIR, filename, 
                                       mimetype='text/plain; charset=utf-8', 
                                       as_attachment=False)
        
        @response.call_on_close
        def process_after_request():
            safe_delete_file(file_path_to_serve)
            app.logger.info(f"Attempted deletion of {file_path_to_serve} after serving.")

        return response
        
    except FileNotFoundError: 
        app.logger.error(f"File not found (fallback) for serving: {file_path_to_serve}")
        return jsonify({"error": "File not found."}), 404
    except Exception as e:
        app.logger.error(f"Error serving plain text transcript {filename}: {e}", exc_info=True)
        safe_delete_file(file_path_to_serve) 
        return jsonify({"error": "Could not serve transcript file."}), 500

if __name__ == "__main__":
    if not app.debug:
        pass 
    
    app.logger.info("--- Starting YouTube Info API (Flask Development Server) ---")
    port = int(os.environ.get("PORT", 8081)) 
    app.run(host='0.0.0.0', port=port, debug=True)
