from flask import Flask, request, jsonify, Response
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter
import os
import tempfile # For handling temporary cookie file

app = Flask(__name__)

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
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as tmp_cookie_file:
                tmp_cookie_file.write(cookie_content)
                app.logger.info(f"Temporary cookie file created at: {tmp_cookie_file.name}")
                return tmp_cookie_file.name # Return the path to the temp file
        except Exception as e:
            app.logger.error(f"Error creating temporary cookie file: {e}")
            return None
    return None

@app.route('/')
def home():
    return "Welcome to the YouTube Transcript API service! Use /api/transcript?video_id=YOUR_VIDEO_ID to get a transcript. Add &format=text for plain text."

@app.route('/api/transcript', methods=['GET'])
def get_transcript_api():
    video_id = request.args.get('video_id')
    output_format = request.args.get('format', 'json').lower()

    if not video_id:
        return jsonify({"error": "Missing 'video_id' parameter in the URL"}), 400

    temp_cookie_file_path = None # Initialize
    try:
        temp_cookie_file_path = get_cookie_file_path() # Get path to temp cookie file if env var is set
        
        if temp_cookie_file_path:
            app.logger.info(f"Attempting to use cookies from: {temp_cookie_file_path}")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, cookies=temp_cookie_file_path)
        else:
            app.logger.info("No YOUTUBE_COOKIES_CONTENT found, proceeding without cookies.")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        preferred_languages = ['en', 'ro', 'es', 'de', 'fr', 'pt', 'it', 'nl', 'ja', 'ko', 'ru', 'zh-Hans', 'zh-Hant', 'hi', 'ar']

        transcript_to_fetch = None
        try:
            transcript_to_fetch = transcript_list.find_manually_created_transcript(preferred_languages)
        except NoTranscriptFound:
            try:
                transcript_to_fetch = transcript_list.find_generated_transcript(preferred_languages)
            except NoTranscriptFound:
                return jsonify({"error": "No transcript found in the preferred languages for this video.", "video_id": video_id}), 404
        
        transcript_data = transcript_to_fetch.fetch() 
        
        if output_format == 'text':
            formatter = TextFormatter()
            plain_text_transcript = formatter.format_transcript(transcript_data)
            # Ensure the temporary cookie file is deleted if it was created
            if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
                try:
                    os.remove(temp_cookie_file_path)
                    app.logger.info(f"Temporary cookie file deleted: {temp_cookie_file_path}")
                except Exception as e_del:
                    app.logger.error(f"Error deleting temp cookie file {temp_cookie_file_path}: {e_del}")
            return Response(plain_text_transcript, mimetype='text/plain; charset=utf-8')
        else: 
            # Ensure the temporary cookie file is deleted if it was created
            if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
                try:
                    os.remove(temp_cookie_file_path)
                    app.logger.info(f"Temporary cookie file deleted: {temp_cookie_file_path}")
                except Exception as e_del:
                    app.logger.error(f"Error deleting temp cookie file {temp_cookie_file_path}: {e_del}")
            return jsonify({
                "video_id": video_id,
                "transcript_format": "structured_json",
                "transcript": transcript_data 
            })

    except TranscriptsDisabled:
        return jsonify({"error": "Transcripts are disabled for this video.", "video_id": video_id}), 403
    except NoTranscriptFound:
        return jsonify({"error": "No transcript available for this video ID (it might be invalid, private, deleted, or have no captions for specified languages).", "video_id": video_id}), 404
    except Exception as e:
        app.logger.error(f"An unexpected error occurred in get_transcript_api: {e}", exc_info=True)
        return jsonify({"error": f"An server-side error occurred: {str(e)}", "video_id": video_id}), 500
    finally:
        # Final cleanup attempt for the temporary cookie file, in case of early exit or error
        if temp_cookie_file_path and os.path.exists(temp_cookie_file_path):
            try:
                os.remove(temp_cookie_file_path)
                app.logger.info(f"Temporary cookie file deleted in finally block: {temp_cookie_file_path}")
            except Exception as e_del_finally:
                app.logger.error(f"Error deleting temp cookie file {temp_cookie_file_path} in finally block: {e_del_finally}")


if __name__ == "__main__":
    # For local testing, you might want to set the YOUTUBE_COOKIES_CONTENT env var
    # or simulate it for testing the cookie logic.
    # Example: os.environ['YOUTUBE_COOKIES_CONTENT'] = "..." (paste your cookie content here for local test)
    
    # Configure basic logging for local Flask development server
    # Gunicorn will handle logging in production on Railway
    if not app.debug: # Only configure basicConfig if not in debug mode (Gunicorn might set its own)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    app.logger.info("--- Starting YouTube Transcript API (Flask Development Server) ---")
    port = int(os.environ.get("PORT", 8081)) # Use a different port if 5001 is for the other API
    app.run(host='0.0.0.0', port=port, debug=True)
