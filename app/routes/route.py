from io import BytesIO
import io
import json
import os
import queue
import threading
import time
import uuid
from flask import Blueprint, Response, current_app, jsonify, render_template, request, send_file, stream_with_context
from app.classes.document_ops import DocumentOperations
# from app.classes.langchain_llama import langchain_llama
# from app.classes.tts import synthesizer
from app.classes.ollama_service import OllamaService
from app.classes.orchestrator import Orchestrator


blp = Blueprint('route','route', url_prefix='/tools')

# Dictionary to store progress for each task
progress_data = {}
# Queue for each task to communicate progress
progress_queues = {}


@blp.route("/tor", methods=['POST','GET'])
def generate_tor():
    if request.method == 'POST':
        try:
            json_data = request.get_json()
            if not json_data:
                return jsonify({"error": "Invalid JSON"}), 400
            if 'message' not in json_data:
                return jsonify({"error": "Message is required"}), 400
            if 'model' not in json_data:
                return jsonify({"error": "Model is required"}), 400
            context = json_data.get('message')
            model = json_data.get('model')
            # orchestrator = Orchestrator()
            
            # Check context length
            if len(context) > 15000:
                return jsonify({"error": "Context too large. Please limit to 5000 words."}), 400
            
            # Process asynchronously
            task_id = str(uuid.uuid4())
            
            # Initialize progress tracking for this task
            progress_data[task_id] = {"progress": 0, "status": "Starting processing..."}
            progress_queues[task_id] = queue.Queue()
            # progress_queues.put((task_id, context))
            
            thread = threading.Thread(
                target=process_task_queue,
                args=(task_id, context, current_app._get_current_object()) # type: ignore
            )
            
            thread.daemon = True
            thread.start()
            
            return jsonify({
                "task_id": task_id,
                "status": "processing",
                "message": "Your proposal is being generated."
            })
        
        except Exception as e:
            # logger.error(f"API error: {str(e)}")
            return jsonify({"error": str(e)}), 500
        
        # def generate():
        #     for chunk in orchestrator.generate_proposal(context=context, model=model, stream=True):
        #         if 'response' in chunk:
        #                 yield chunk['response']
                
        # return stream_with_context(generate())
    
    return render_template('tor.html', models = get_models())


@blp.route('/chat', methods= ['POST'])
def chat():
    json_data = request.get_json()
    if not json_data:   
        return jsonify({"error": "Invalid JSON"}), 400
    if 'message' not in json_data:
        return jsonify({"error": "Message is required"}), 400
    if 'model' not in json_data:
        return jsonify({"error": "Model is required"}), 400
    query = json_data.get('message')
    model = json_data.get('model')
    ollama_service = OllamaService()
    def generate():
        for chunk in ollama_service.chat(user_input=query, model_name=model, stream=True):
            if 'message' in chunk and 'content' in chunk['message']: # type: ignore
                    yield chunk['message']['content'] # type: ignore
            
    return stream_with_context(generate())


@blp.route('/',methods=['POST','GET'])
def home():
    return render_template('chatbot.html', models = get_models())


@blp.route('/proofread')
def proofread():
    return render_template('proofread.html',models = get_models())


@blp.route('/upload', methods=['POST'])
def upload_file():
    if "file" not in request.files:
        return jsonify({"message":"No file part"}), 400
    
    file = request.files['file']
    if file.filename =="":
        return jsonify({"message": "No selected file"}), 400
    
    # Generate a unique task ID
    task_id = str(uuid.uuid4())
    
    # Initialize progress tracking for this task
    progress_data[task_id] = {"progress": 0, "status": "Starting upload..."}
    progress_queues[task_id] = queue.Queue()
    
    # Read file data
    file_data = file.read()
    
     # Start processing in a background thread
    thread = threading.Thread(
        target=process_document_task,
        args=(file_data, file.filename, task_id, current_app._get_current_object()) # type: ignore
    )
    thread.daemon = True
    thread.start()
    
    # Return the task ID to the client
    return jsonify({"task_id": task_id})


@blp.route('/progress/<task_id>', methods=['GET'])
def progress(task_id):
    """Stream progress events to the client"""
    def generate():
        try:
            while True:
                # Check if we have any progress updates in the queue
                try:
                    # Non-blocking queue check
                    update = progress_queues[task_id].get(block=False)
                    
                    # Update the stored progress data
                    if "error" in update:
                        progress_data[task_id]["error"] = update["error"]
                    else:
                        if "progress" in update:
                            progress_data[task_id]["progress"] = update["progress"]
                        if "status" in update:
                            progress_data[task_id]["status"] = update["status"]
                    
                    # Send the update to the client
                    yield f"data: {json.dumps(update)}\n\n"
                    
                    # Check if we're done
                    if "progress" in update and update["progress"] == 100:
                        break
                    if "error" in update:
                        break
                        
                except queue.Empty:
                    # No updates yet, send a heartbeat
                    pass
                
                time.sleep(0.5)  # Short sleep to prevent busy waiting
                
        except GeneratorExit:
            # Client disconnected
            pass
    
    return Response(generate(), mimetype='text/event-stream')


@blp.route('/download/<task_id>')
def download_file(task_id):
    """Download the processed document"""
    if task_id not in progress_data or "file" not in progress_data[task_id]:
        return jsonify({"message": "File not found or processing incomplete"}), 404
    
    file_stream = progress_data[task_id]["file"]
    filename = progress_data[task_id]["filename"]
    
    # Ensure we're at the start of the stream
    file_stream.seek(0)
    
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


@blp.route('/cleanup/<task_id>', methods=['POST'])
def cleanup(task_id):
    """Clean up resources for a task"""
    if task_id in progress_data:
        del progress_data[task_id]
    if task_id in progress_queues:
        del progress_queues[task_id]
    return jsonify({"message": "Cleanup complete"})


@blp.route('/translate',methods=['POST','GET'])
def translate():
    if request.method=='POST':
        json_data = request.get_json()
        if not json_data:  
            return jsonify({"error": "Invalid JSON"}), 400
        if 'message' not in json_data:
            return jsonify({"error": "Message is required"}), 400
        if 'model' not in json_data:
            return jsonify({"error": "Model is required"}), 400
        query = json_data.get('message')
        model = json_data.get('model')
        ollama_service = OllamaService()
        translated_text = ollama_service.translate(user_input=query, model=model, stream=False)
        return jsonify({"translated_text": translated_text['response']}) # type: ignore
        # def generate():
        #     for chunk in ollama_service.translate(user_input=query, model_name=model, stream=True):
        #         if 'response' in chunk:
        #             yield chunk['response']
            
        # return stream_with_context(generate())
    return render_template('translate.html', models = get_models())

# @blp.route('/tts')
# def tts():
#     return render_template('tts.html')

# @blp.route("/audio", methods=['POST'])
# def text_to_audio():
#     if request.method == 'POST':
#         if(request.form["text"]):
#             text = request.form["text"]
#             outputs = synthesizer.tts(text)
#             out = io.BytesIO()
#             synthesizer.save_wav(outputs, out)
#             return send_file(out, mimetype="audio/wav")
#         else:
#             return {"error": "Please provide the text"}, 400 
#     return {"error": "Please check the recaptcha"}, 400 

def get_models():
    custom_model_names = [{'model':'qwen2.5:latest', 'description':'latest and powerful', 'name':'qwen2.5'},
                          {'model':'gemma3:12b', 'description':'smart and talkative', 'name':'gemma3'},
                          {'model':'deepseek-r1:8b', 'description':'reasoning model', 'name':'deepseek-r1'},
                          {'model':'llama3:latest', 'description':'matured and robust', 'name':'llama3'},
                          {'model':'mistral:latest', 'description':'sincere and descriptive', 'name':'mistral'}]
    return custom_model_names


def process_document_task(file_data, file_name, task_id, app):
    """Background task to process document and update progress"""
    with app.app_context():
        try:
            # Update progress to 50% - Upload complete
            progress_queues[task_id].put({"progress": 25, "status": "Upload complete. Processing document..."})

            # Create BytesIO from file data
            file_stream = BytesIO(file_data)

            # Process the document
            read_document = DocumentOperations()
            processed_document = read_document.read_docx(filepath=file_stream, task_id=task_id, progress_queues=progress_queues)

            # Generate output filename
            processed_file_name = file_name.rsplit(".", 1)[0] + "_proofread.docx"

            # Save the processed document to a new BytesIO
            processed_file_stream = BytesIO()
            processed_document.save(processed_file_stream)
            processed_file_stream.seek(0)

            # Store the processed file in memory (in a real app, you might save to disk or database)
            progress_data[task_id]["file"] = processed_file_stream
            progress_data[task_id]["filename"] = processed_file_name

            # Update progress to 100% - Processing complete
            progress_queues[task_id].put({"progress": 100, "status": "Processing complete. Ready for download."})


        except Exception as e:
            # Handle any errors
            progress_queues[task_id].put({"error": str(e)})


def process_task_queue(task_id, context, app):
    """Background worker to process tasks."""
    with app.app_context():
        try:
            # Create service instances
            orchestrator = Orchestrator()
            
            # Generate proposal
            result = orchestrator.generate_proposal(task_id, context, progress_queues=progress_queues)
            progress_data[task_id] = result
            
             # Store the processed file in memory (in a real app, you might save to disk or database)
            progress_data[task_id]["file"] = result["file"]
            progress_data[task_id]["filename"] = result["filename"]
            
            # Update progress to 100% - Processing complete
            progress_queues[task_id].put({"progress": 100, "status": "Processing complete. Ready for download."})
            
            # Clean up old results (keep for 1 hour)
            current_time = time.time()
            for tid in list(progress_data.keys()):
                if progress_data[tid].get("timestamp", current_time) < current_time - 3600:
                    del progress_data[tid]
                    
        except Exception as e:
            progress_data[task_id] = {"progress": 100, "status": f"Error: {str(e)}"}