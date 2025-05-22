# blp = Blueprint('chat', __name__, url_prefix='/chat')

import dataclasses
from io import BytesIO
import json
import os
import queue
import threading
import time
import uuid
from flask import Blueprint, Response, current_app, jsonify, render_template, request, stream_with_context

from app.classes.chat_studio import ChatStudio
from app.classes.ollama_service import OllamaService

blp = Blueprint('chat', __name__)

active_requests = {}

@blp.route('/')
def chatbot():
    return render_template('zpt.html', models=get_models(), response_styles = set_style('normal'))


@blp.route('/bot', methods=['POST'])
def bot():
    """Chatbot endpoint"""
    json_data = request.get_json()
    file_path = ''
    if not json_data:
        return jsonify({"error": "Invalid JSON"}), 400
    if 'model' not in json_data:
        return jsonify({"error": "Model is required"}), 400
    if 'message' not in json_data:
        return jsonify({"error": "Message is required"}), 400
    if 'style' not in json_data:
        return jsonify({"error": "Style is required"}), 400
    
    model = json_data['model']
    message = json_data['message']
    style = json_data['style']
    fileName = json_data.get('fileName', None)
    file_path = current_app.config['UPLOAD_FOLDER'] + '/' + fileName if fileName else None
    
    # Create a unique ID for this request
    request_id = str(uuid.uuid4())
    
    # Store this request in our active requests
    active_requests[request_id] = {
        "message": message,
        "timestamp": time.time(),
        "cancelled": False
    }
    
    chat_studio = ChatStudio(model=model, style=style, file_path=file_path or "")
    
    def generate():
        if file_path:
            for chunk in chat_studio.get_bot_response(message=message, file_path=file_path):
                if request_id in active_requests and active_requests[request_id]["cancelled"]:
                    yield f"\n\n_{request_id}: {json.dumps({'type': 'cancelled', 'message': 'Response cancelled by user'})}\n\n"
                    break
                value = None
                if isinstance(chunk.__dict__, dict) and 'response' in chunk:
                    value = chunk.get('response') # type: ignore
                elif isinstance(chunk, (list, tuple)) and len(chunk) > 0:
                    value = chunk[0]
                if value is not None:
                    yield str(value)
        else:
            for chunk in chat_studio.get_bot_response(message=message):
                if request_id in active_requests and active_requests[request_id]["cancelled"]:
                    yield f"\n\n_{request_id}: {json.dumps({'type': 'cancelled', 'message': 'Response cancelled by user'})}\n\n"
                    break
                value = None
                if isinstance(chunk.__dict__, dict) and 'message' in chunk: 
                    chunk_message = chunk.get('message', {}) # type: ignore
                    if isinstance(chunk_message.__dict__, dict) and 'content' in chunk_message:
                        value = chunk_message.get('content')
                if value is not None:
                    yield str(value)
            
        # Clean up this request
        if request_id in active_requests:
            del active_requests[request_id]
    
    return Response(stream_with_context(generate()), content_type='text/event-stream'), 200, {
        'X-Request-ID': request_id,
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive'
    }

@blp.route('/stop', methods=['POST'])
def stop():
    """
    Endpoint to stop an in-progress response.
    """
    data = request.json
    if not data or 'request_id' not in data:
        return jsonify({'error': 'Invalid request ID'}), 400
    request_id = data.get('request_id')
    
    if not request_id or request_id not in active_requests:
        return jsonify({'error': 'Invalid request ID'}), 400
    
    # Mark this request as cancelled
    active_requests[request_id]["cancelled"] = True
    return jsonify({'success': True, 'message': 'Response cancellation requested'}), 200

@blp.route('/upload', methods=['POST'])
def upload_file():
    if "file" not in request.files:
        return jsonify({"message":"No file part"}), 400
    
    file = request.files['file']
    if file.filename =="":
        return jsonify({"message": "No selected file"}), 400
    
    # Save the file in the upload folder
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    if not upload_folder:
        return jsonify({"message": "Upload folder is not configured"}), 500
    file_path = os.path.join(str(upload_folder), str(file.filename))
    # file_path = f"{current_app.config['UPLOAD_FOLDER']}/{file.filename}"
    file.save(file_path)
    
    # Return the task ID to the client
    return jsonify({"message": 'File uploaded successfully'}), 200

@blp.route('/delete', methods=['POST'])
def delete_file():
    """
    Delete a file from the server's upload folder
    
    Expected JSON body:
    {
        "filename": "file_to_delete.pdf"
    }
    """
    # Get filename from request JSON
    data = request.get_json()
    
    if not data or 'file_name' not in data:
        return jsonify({"error": "Filename is required"}), 400
    
    filename = data['file_name']
    
    # Prevent directory traversal attacks
    if '..' in filename or filename.startswith('/'):
        return jsonify({"error": "Invalid filename"}), 400
    
    # Construct full file path
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    
    # Check if file exists
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    
    try:
        # Delete the file
        os.remove(file_path)
        return jsonify({"message": f"File {filename} deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to delete file: {str(e)}"}), 500

def set_style(selected_style: str):
    styles_json = [
        {"name":'Normal', "value":'normal',"isSelected":False},
        {"name":'Concise', "value":'concise',"isSelected":False},
        {"name":'Explanatory', "value":'explanatory',"isSelected":False},
        {"name":'Formal', "value":'formal',"isSelected":False}]
    
    for item in styles_json:
        if item['value']==selected_style.lower():
            item['isSelected']=True
    return styles_json

# Clean up old requests periodically
def cleanup_old_requests():
    while True:
        current_time = time.time()
        to_remove = []
        
        for req_id, req_data in active_requests.items():
            # Remove requests older than 5 minutes
            if current_time - req_data["timestamp"] > 300:
                to_remove.append(req_id)
        
        for req_id in to_remove:
            if req_id in active_requests:
                del active_requests[req_id]
        
        time.sleep(60)  # Check every minute

# Start the cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_requests, daemon=True)
cleanup_thread.start()

def get_models():
    # ollama_service = OllamaService()
    custom_model_names = [{'model':'qwen2.5:latest', 'description':'latest and powerful', 'name':'qwen2.5'},
                          {'model':'gemma3:12b', 'description':'smart and talkative', 'name':'gemma3'},
                          {'model':'deepseek-r1:8b', 'description':'reasoning model', 'name':'deepseek-r1'},
                          {'model':'llama3:latest', 'description':'matured and robust', 'name':'llama3'},
                          {'model':'mistral:latest', 'description':'sincere and descriptive', 'name':'mistral'}]
    # models = ollama_service.get_models()
    # for model in models:
    #     if model.model.startswith('llama')
    return custom_model_names