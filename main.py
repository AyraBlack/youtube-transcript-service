from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import os

# Initialize our Flask application
app = Flask(__name__)

# This is a simple route for the home page of our API
@app.route('/')
def home():
    return "Welcome to the YouTube Transcript API service! Use /api/transcript?video_id=YOUR_VIDEO_ID to get a transcript."

# This is the main API endpoint that will return the transcript
@app.route('/api/transcript', methods=['GET'])
def get_transcript_api():
    video_id = request.args.get('video_id')

    if not video_id:
        return jsonify({"error": "Missing 'video_id' parameter in the URL"}), 400

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # --- ADDED BLOCK: Define a list of preferred languages ---
        # You can customize this list. It will try them in order.
        # Common language codes: 'en' (English), 'es' (Spanish), 'fr' (French), 'de' (German), 'ja' (Japanese), 'ko' (Korean), 'ru' (Russian), 'zh-Hans' (Simplified Chinese)
        # For the video dQw4w9WgXcQ, English ('en') is available.
        preferred_languages = ['en', 'es', 'de', 'fr', 'pt', 'it', 'nl', 'ja', 'ko', 'ru', 'zh-Hans', 'zh-Hant', 'hi', 'ar']
        # --- END OF ADDED BLOCK ---

        transcript_to_fetch = None
        try:
            # Try for a manually created transcript in preferred languages
            transcript_to_fetch = transcript_list.find_manually_created_transcript(preferred_languages) # CHANGED LINE
        except NoTranscriptFound:
            # If no manual one, try for an auto-generated one in preferred languages
            try:
                transcript_to_fetch = transcript_list.find_generated_transcript(preferred_languages) # CHANGED LINE
            except NoTranscriptFound:
                return jsonify({"error": "No transcript found in the preferred languages for this video.", "video_id": video_id}), 404
        
        transcript_data = transcript_to_fetch.fetch()
        
        return jsonify({"video_id": video_id, "transcript": transcript_data})

    except TranscriptsDisabled:
        return jsonify({"error": "Transcripts are disabled for this video.", "video_id": video_id}), 403
    except NoTranscriptFound: # This might be redundant due to earlier checks but good as a fallback.
        return jsonify({"error": "No transcript available for this video ID (it might be invalid, private, deleted, or have no captions for specified languages).", "video_id": video_id}), 404
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")
        return jsonify({"error": f"An server-side error occurred: {str(e)}", "video_id": video_id}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
