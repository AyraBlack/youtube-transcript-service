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
    # Get the 'video_id' from the URL (e.g., ...?video_id=VIDEO_ID_HERE)
    video_id = request.args.get('video_id')

    # If no video_id is provided in the URL, return an error
    if not video_id:
        return jsonify({"error": "Missing 'video_id' parameter in the URL"}), 400 # Bad Request

    try:
        # Get a list of available transcripts for the given video_id
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # We'll try to find a manually created transcript first, then a generated one.
        # You can also specify languages here if needed, e.g., transcript_list.find_manually_created_transcript(['en', 'es'])
        
        transcript_to_fetch = None
        try:
            # Try for a manually created transcript (often higher quality)
            transcript_to_fetch = transcript_list.find_manually_created_transcript()
        except NoTranscriptFound:
            # If no manual one, try for an auto-generated one
            try:
                transcript_to_fetch = transcript_list.find_generated_transcript()
            except NoTranscriptFound:
                # If neither is found
                return jsonify({"error": "No transcript found for this video.", "video_id": video_id}), 404 # Not Found
        
        # Fetch the actual transcript data (list of dictionaries with 'text', 'start', 'duration')
        transcript_data = transcript_to_fetch.fetch()
        
        # Return the video_id and the transcript data as a JSON response
        return jsonify({"video_id": video_id, "transcript": transcript_data})

    except TranscriptsDisabled:
        # Handle cases where transcripts are disabled for the video
        return jsonify({"error": "Transcripts are disabled for this video.", "video_id": video_id}), 403 # Forbidden
    except NoTranscriptFound:
        # This can also mean the video ID is invalid, private, or deleted.
        return jsonify({"error": "No transcript available for this video ID. It might be invalid, private, deleted, or have no captions.", "video_id": video_id}), 404 # Not Found
    except Exception as e:
        # Catch any other unexpected errors and return a generic server error
        # It's good to log the actual error for debugging on Railway's side
        print(f"An unexpected error occurred: {str(e)}")
        return jsonify({"error": f"An server-side error occurred: {str(e)}", "video_id": video_id}), 500 # Internal Server Error

# This part is needed for Railway to run the app.
# Gunicorn (our web server) will use this 'app' object.
# Railway sets the PORT environment variable.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080)) # Default to 8080 if PORT not set
    # For local testing, you might run this. On Railway, Gunicorn runs it.
    # host='0.0.0.0' makes it accessible externally (needed for Railway)
    app.run(host='0.0.0.0', port=port)
