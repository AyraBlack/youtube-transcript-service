from flask import Flask, request, jsonify, Response, send_from_directory, url_for
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter
from pytube import YouTube as PytubeYouTube # Alias to avoid confusion with YouTubeTranscriptApi
from pytube.exceptions import PytubeError as PytubeLibError
import os
import tempfile # For handling temporary cookie file
import uuid # For unique temporary transcript file names
import logging

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# --- Configuration for Temporary Transcript Text Files ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Directory to store temporary plain text transcript files before they are served and deleted
TEXT_TRANSCRIPTS_TEMP_DIR = os.path.join(BASE_DIR, "api_text_transcripts_temp")

if not os.path.exists(TEXT_TRANSCRIPTS_TEMP_DIR):
    os.makedirs(TEXT_TRANSCRIPTS_TEMP_DIR)
    app.logger.info(f"Created temporary text transcripts directory: {TEXT_TRANSCRIPTS_TEMP_DIR}")

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

    video_url = f"https://www.google.com/url?sa=E&source=gmail&q=https://youtube-audio-transcriber-production.up.railway.app/api/extract_audio?url=https://youtu.be/mG4XXtpuSlk?si=j1Cj0bw5Muo_xuhI" # Construct full URL for pytube

    response_data = {
        "video_id": video_id,
        "video_title": None,
        "channel_name": None,
        "transcript_download_url": None,
        "error": None
    }
    
    temp_cookie_file_path = None
    temp_transcript_text_file_path = None

    try:
        # 1. Get Title and Channel using Pytube
        try:
            app.logger.info(f"Fetching metadata with Pytube for video ID: {video_id}")
            yt_pytube = PytubeYouTube(video_url)
            response_data["video_title"] = yt_pytube.title
            response_data["channel_name"] = yt_pytube.author
            app.logger.info(f"Pytube fetched Title: '{yt_pytube.title}', Channel: '{yt_pytube.author}'")
        except PytubeLibError as pe:
            app.logger.warning(f"Pytube error fetching metadata for {video_id}: {pe}. Transcript fetching will proceed.")
            # Not a fatal error for transcript, but good to note.
            # response_data["error"] = f"Pytube metadata error: {str(pe)}" # Optionally report this
        except Exception as e_pytube:
            app.logger.warning(f"Unexpected error with Pytube for {video_id}: {e_pytube}. Transcript fetching will proceed.")


        # 2. Get Transcript using YouTubeTranscriptApi
        temp_cookie_file_path = get_cookie_file_path()
        
        if temp_cookie_file_path:
            app.logger.info(f"Attempting to list transcripts for {video_id} using cookies from: {temp_cookie_file_path}")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, cookies=temp_cookie_file_path)
        else:
            app.logger.info(f"Attempting to list transcripts for {video_id} without cookies.")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        preferred_languages = ['ro', 'en'] # Prioritize Romanian, then English
        transcript_to_fetch = None
        fetched_lang = None

        for lang in preferred_languages:
            try:
                app.logger.info(f"Trying to find '{lang}' transcript for {video_id}...")
                transcript = transcript_list.find_transcript([lang])
                transcript_to_fetch = transcript.fetch()
                fetched_lang = lang
                app.logger.info(f"Found and fetched '{lang}' transcript for {video_id}.")
                break # Found a preferred language
            except NoTranscriptFound:
                app.logger.info(f"No '{lang}' transcript found for {video_id}.")
                continue # Try next preferred language
        
        if not transcript_to_fetch: # If neither preferred lang found, try auto-generated in preferred order
            app.logger.info(f"No manual transcript in {preferred_languages}. Trying auto-generated for {video_id}...")
            for lang in preferred_languages:
                try:
                    transcript = transcript_list.find_generated_transcript([lang])
                    transcript_to_fetch = transcript.fetch()
                    fetched_lang = f"{lang} (auto-generated)"
                    app.logger.info(f"Found and fetched auto-generated '{lang}' transcript for {video_id}.")
                    break
                except NoTranscriptFound:
                    app.logger.info(f"No auto-generated '{lang}' transcript for {video_id}.")
                    continue
        
        if not transcript_to_fetch:
            response_data["error"] = "No transcript found in Romanian or English (manual or auto-generated)."
            app.logger.warning(response_data["error"] + f" for video ID: {video_id}")
            # No need to delete temp_cookie_file_path here as it's handled in finally
            return jsonify(response_data), 404

        # 3. Format to plain text and save to a temporary file
        formatter = TextFormatter()
        plain_text_transcript = formatter.format_transcript(transcript_to_fetch)
        
        temp_transcript_filename = f"transcript_{video_id}_{uuid.uuid4().hex[:8]}.txt"
        temp_transcript_text_file_path = os.path.join(TEXT_TRANSCRIPTS_TEMP_DIR, temp_transcript_filename)
        
        with open(temp_transcript_text_file_path, 'w', encoding='utf-8') as f:
            f.write(plain_text_transcript)
        app.logger.info(f"Plain text transcript saved to temporary file: {temp_transcript_text_file_path}")

        # 4. Generate download URL for the plain text transcript
        response_data["transcript_download_url"] = url_for('serve_plain_text_transcript', 
                                                           filename=temp_transcript_filename, 
                                                           _external=True)
        response_data["language_detected"] = fetched_lang
        
        return jsonify(response_data), 200

    except TranscriptsDisabled:
        response_data["error"] = "Transcripts are disabled for this video."
        app.logger.warning(response_data["error"] + f" for video ID: {video_id}")
        return jsonify(response_data), 403
    except NoTranscriptFound: # Fallback, though specific language checks are done above
        response_data["error"] = "No transcript available for this video ID."
        app.logger.warning(response_data["error"] + f" for video ID: {video_id}")
        return jsonify(response_data), 404
    except Exception as e:
        app.logger.error(f"Unexpected error in get_video_info_api for {video_id}: {e}", exc_info=True)
        response_data["error"] = f"An unexpected server-side error occurred: {str(e)}"
        return jsonify(response_data), 500
    finally:
        safe_delete_file(temp_cookie_file_path)
        # DO NOT delete temp_transcript_text_file_path here. It will be deleted after serving.

# --- New Route to Serve Plain Text Transcripts ---
@app.route('/serve_text_transcript/<filename>')
def serve_plain_text_transcript(filename):
    app.logger.info(f"Request to serve plain text transcript: {filename}")
    file_path_to_serve = os.path.join(TEXT_TRANSCRIPTS_TEMP_DIR, filename)
    try:
        if not os.path.exists(file_path_to_serve):
            app.logger.error(f"Temporary transcript file not found for serving: {file_path_to_serve}")
            return jsonify({"error": "Transcript file not found or already served."}), 404

        # Send the file content as plain text
        response = send_from_directory(TEXT_TRANSCRIPTS_TEMP_DIR, filename, 
                                       mimetype='text/plain; charset=utf-8', 
                                       as_attachment=False) # as_attachment=False to display in browser
        
        # Schedule file for deletion after request is complete using Flask's after_this_request
        # This is a common pattern but needs careful handling in some server setups.
        # A simpler approach for now might be to rely on periodic cleanup or short-lived files.
        # For this example, we'll try to delete it immediately after creating the response.
        # However, this might be too soon if the file isn't fully sent.
        # A more robust solution would be a background task or specific cleanup endpoint.
        # For now, let's delete it after creating the response.
        # This is NOT ideal for production as the file might be deleted before fully sent.
        # A better way is to have n8n confirm download and then call a cleanup endpoint, or a timed cleanup.
        # For simplicity now, we delete. If issues, we can remove this immediate delete.
        
        @response.call_on_close
        def process_after_request():
            safe_delete_file(file_path_to_serve)
            app.logger.info(f"Attempted deletion of {file_path_to_serve} after serving.")

        return response
        
    except FileNotFoundError: # Should be caught by os.path.exists above, but as a fallback
        app.logger.error(f"File not found (fallback) for serving: {file_path_to_serve}")
        return jsonify({"error": "File not found."}), 404
    except Exception as e:
        app.logger.error(f"Error serving plain text transcript {filename}: {e}", exc_info=True)
        safe_delete_file(file_path_to_serve) # Attempt cleanup on error too
        return jsonify({"error": "Could not serve transcript file."}), 500

if __name__ == "__main__":
    if not app.debug:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    app.logger.info("--- Starting YouTube Info API (Flask Development Server) ---")
    port = int(os.environ.get("PORT", 8081)) # Use a different port if needed
    app.run(host='0.0.0.0', port=port, debug=True)
