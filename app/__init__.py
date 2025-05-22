import os
from flask import Flask, render_template
from app.routes.route import blp as blproute
from app.routes.chat import blp as blpchat

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = '92927b79f2712a5c93f9171a81cc9e82fa4e4b6d9228e39740a12bc2159e9a17'
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
	# app.config['UPLOAD_FOLDER'] = os.path.abspath("app/static/uploads")
	# Configure app from environment variables
    app.config.update(
  		MODEL_NAME=os.getenv("OLLAMA_MODEL", "llama3"),
		PROPOSALS_DIR=os.path.abspath("app/static/proposal_formats"),
		CACHE_DIR=os.path.abspath("app/static/cache"),
		TEMPERATURE=float(os.getenv("TEMPERATURE", "0.7")),
		DEBUG=os.getenv("DEBUG", "False").lower() == "true",
		# SECRET_KEY=os.getenv("SECRET_KEY", os.urandom(24).hex())
	)
    app.register_blueprint(blproute)
    app.register_blueprint(blpchat)
    for directory in [app.config['UPLOAD_FOLDER'],app.config['PROPOSALS_DIR'],app.config['CACHE_DIR']]:
        if not os.path.exists(directory):
            os.makedirs(directory)
 
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def server_error(e):
        return render_template('500.html', error=str(e) if app.config["DEBUG"] else None), 500
    
    return app
