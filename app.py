from flask import Flask, request, render_template, redirect, url_for, jsonify
import os, shutil
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
from docx import Document
import requests
import json
import re

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
ORG_FOLDER = 'organized'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ORG_FOLDER, exist_ok=True)

# Global var to hold AI suggestions between requests
file_structure = {}

# Extract text preview
def extract_preview(filepath, pages=2):
	ext = filepath.lower()
	text = ""
	cap_text = pages * 500
	try:
		if ext.endswith(".pdf"):
			doc = fitz.open(filepath)
			for i in range(min(pages, len(doc))):
				text += doc[i].get_text()
		elif ext.endswith(".docx"):
			paragraphs = pages * 3
			doc = Document(filepath)
			for para in doc.paragraphs[:paragraphs]:
				text += para.text + "\n"
		elif ext.endswith(".txt"):
			characters = pages * 500
			with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
				text = f.read(characters)
	except Exception as e:
		text = f"(Error reading file: {e})"
	return text.strip()[:cap_text]

# Ask Ollama
def ask_ollama(prompt, model="mistral:7b-instruct-q4_K_M"):
	response = requests.post("http://localhost:11434/api/generate", json={
		"model": model,
		"prompt": prompt,
		"stream": False
	})

	try:
		result = response.json()
	except Exception:
		raise RuntimeError("Could not decode JSON from Ollama response:\n" + response.text)

	if 'response' in result:
		return result["response"]
	else:
		raise RuntimeError(f"Ollama did not return a 'response':\n{json.dumps(result, indent=4)}")

@app.route('/ask_ai', methods=['POST'])
def ask_ai():
	data = request.get_json()
	prompt = data.get('prompt', '')
	if not prompt:
		return "No prompt provided", 400
	try:
		response = ask_ollama(prompt)
		return jsonify({"response": response})
	except Exception as e:
		return jsonify({"error": str(e)}), 500

# Build prompt from previews
def build_prompt(file_previews):
	prompt = "Categorize and then organize a file system for the documents previewed. Suggest folders in JSON as a tree structure like:\n" \
		"{\n\t\"Folder\":\n\t{\n\t\t\"Subfolder\":\n\t\t{\n\t\t\t\"<file name>\":\"<brief synopsis>\"\n\t\t}\n\t}\n}"
	for filename, preview in file_previews.items():
		trimmed = preview.replace("\n", " ")[:1000]
		prompt += f"Filename: {filename}\nContent: {trimmed}\n\n"
	return prompt

@app.route('/', methods=['GET'])
def index():
	return render_template('index.html')

def normalize_response(response):
	try:
		start = response.index('{')
		end = response.rindex('}') + 1
		response = response[start:end].strip()
		response = re.sub(r'//.*|/\*.*?\*/', '', response, flags=re.DOTALL)
		response = response.replace('[', '').replace(']', '')
		return response
	except ValueError:
		return "{}"

@app.route('/upload', methods=['POST'])
def upload():
	global file_structure
	shutil.rmtree(UPLOAD_FOLDER)
	os.makedirs(UPLOAD_FOLDER)

	file_previews = {}
	for key in request.files:
		file = request.files[key]
		filename = secure_filename(file.filename)
		save_path = os.path.join(UPLOAD_FOLDER, filename)
		os.makedirs(os.path.dirname(save_path), exist_ok=True)
		file.save(save_path)

		preview = extract_preview(save_path)
		file_previews[filename] = preview

	# Ask LLM
	prompt = build_prompt(file_previews)
	response = ask_ollama(prompt)

	try:
		file_structure = json.loads(normalize_response(response))
	except Exception as e:
		return f"<pre>Invalid JSON from AI:\n\n{response}\n\nError: {e}</pre>"

	# Tree structure
	print(file_structure)

	return render_template("structure.html", structure=file_structure)

@app.route('/reorder', methods=['POST'])
def reorder():
	for filename, folder in file_structure.items():
		src_path = os.path.join(UPLOAD_FOLDER, filename)
		dest_dir = os.path.join(ORG_FOLDER, folder)
		os.makedirs(dest_dir, exist_ok=True)
		shutil.move(src_path, os.path.join(dest_dir, filename))
	return "Files moved! Check the 'organized/' folder on your system."

if __name__ == "__main__":
	app.run(debug=True)