from flask import Flask, request, jsonify, Response 
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Welcome to the YouTube Transcript API service! Use /api/transcript?video_id=YOUR_VIDEO_ID to get a transcript. Add &format=text for plain text."

@app.route('/api/transcript', methods=['GET'])
def get_transcript_api():
    video_id = request.args.get('video_id')
    output_format = request.args.get('format', 'json').lower()

    if not video_id:
        return jsonify({"error": "Missing 'video_id' parameter in the URL"}), 400 

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # --- MODIFIED LINE: Added 'ro' (Romanian) ---
        preferred_languages = ['en', 'ro', 'es', 'de', 'fr', 'pt', 'it', 'nl', 'ja', 'ko', 'ru', 'zh-Hans', 'zh-Hant', 'hi', 'ar']
        # --- END OF MODIFIED LINE ---

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
            return Response(plain_text_transcript, mimetype='text/plain; charset=utf-8')
        else: 
            return jsonify({
                "video_id": video_id,
                "transcript_format": "structured_json",
                "transcript": transcript_data 
            })

    except TranscriptsDisabled:
        return jsonify({"error": "Transcripts are disabled for this video.", "video_id": video_id}), 403
    except NoTranscriptFound: # This specific exception might be caught by the inner try-excepts, but it's a good general fallback.
        return jsonify({"error": "No transcript available for this video ID (it might be invalid, private, deleted, or have no captions for specified languages).", "video_id": video_id}), 404
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}") # For server-side debugging
        return jsonify({"error": f"An server-side error occurred: {str(e)}", "video_id": video_id}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
