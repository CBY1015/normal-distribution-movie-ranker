# backend.py (部署版)
import json
import os
import requests
from scipy.stats import norm
from flask import Flask, request, jsonify
from flask_cors import CORS
import random
import re

API_KEY = 'c2a2b97dd7fbdf369708b6ae94e46def'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
DATA_DIR = 'user_data' 

# ===== 修改處 =====
# 告訴 Flask 靜態檔案 (如 index.html) 在 'static' 資料夾
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# ===== 新增端點 =====
@app.route('/')
def index():
    # 當使用者訪問根目錄時，回傳 index.html
    return app.send_static_file('index.html')

# --- (以下所有輔助函式和 API 端點與前一版完全相同) ---
def is_valid_username(username):
    return username and re.match(r'^[a-zA-Z0-9]+$', username)

def get_user_data_path(username):
    if not is_valid_username(username): return None
    # 在 Render 平台上，我們使用 /var/data 來儲存可寫入的檔案
    # 這樣可以確保重啟後資料不會遺失
    persistent_data_dir = os.path.join('/var/data', DATA_DIR)
    if not os.path.exists(persistent_data_dir):
        os.makedirs(persistent_data_dir)
    return os.path.join(persistent_data_dir, f"{username}.json")

def load_ranked_movies(username):
    filepath = get_user_data_path(username)
    if not filepath or not os.path.exists(filepath): return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(); return json.loads(content) if content else []
    except (json.JSONDecodeError, IOError): return []

def save_ranked_movies(username, movies):
    filepath = get_user_data_path(username)
    if not filepath: return False
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(movies, f, ensure_ascii=False, indent=4)
        return True
    except IOError: 
        print(f"為使用者 {username} 儲存失敗"); return False

def search_movie_from_tmdb(title):
    search_url = f"{TMDB_BASE_URL}/search/movie"
    params = {'api_key': API_KEY, 'query': title, 'language': 'zh-TW'}
    try:
        response = requests.get(search_url, params=params); response.raise_for_status()
        return response.json()['results']
    except requests.exceptions.RequestException: return None

def get_random_movie_from_tmdb():
    discover_url = f"{TMDB_BASE_URL}/discover/movie"
    random_page = random.randint(1, 500) 
    params = {'api_key': API_KEY, 'language': 'zh-TW', 'sort_by': 'popularity.desc', 'page': random_page, 'include_adult': 'false', 'vote_count.gte': 100}
    try:
        response = requests.get(discover_url, params=params); response.raise_for_status()
        results = response.json()['results']
        return random.choice(results) if results else None
    except requests.exceptions.RequestException: return None

def recalculate_ratings_and_ranks(ranked_list, mode='normal'):
    n = len(ranked_list)
    if n == 0: return []
    for i, movie in enumerate(ranked_list):
        movie['my_rank'] = i + 1
        score = 3.0
        if n == 1: score = 3.0
        elif mode == 'linear':
            raw_score = 5.0 - (4.5 * i / (n - 1)); score = round(raw_score * 2) / 2
        else:
            percentile = (n - 1 - i + 0.5) / n; z_score = norm.ppf(percentile)
            raw_score = 2.75 + z_score * 1.0; clamped_score = max(0.5, min(5.0, raw_score))
            score = round(clamped_score * 2) / 2
        movie['my_rating'] = score
    return ranked_list

# (以下所有 API 端點完全不變)
@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.json; username = data.get('username')
    if not is_valid_username(username): return jsonify({'error': '無效的使用者名稱，只能使用英文字母和數字。'}), 400
    filepath = get_user_data_path(username)
    if os.path.exists(filepath): return jsonify({'error': '此使用者名稱已被註冊。'}), 409
    if save_ranked_movies(username, []): return jsonify({'success': True, 'username': username})
    else: return jsonify({'error': '無法創建使用者檔案。'}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.json; username = data.get('username')
    if not is_valid_username(username): return jsonify({'error': '無效的使用者名稱。'}), 400
    filepath = get_user_data_path(username)
    if not os.path.exists(filepath): return jsonify({'error': '使用者不存在。'}), 404
    return jsonify({'success': True, 'username': username})

def get_username_from_header(): return request.headers.get('X-Username')

@app.route('/api/movies', methods=['GET', 'DELETE'])
def handle_movies():
    username = get_username_from_header()
    if not username: return jsonify({'error': '未提供使用者資訊'}), 401
    if request.method == 'GET': return jsonify(load_ranked_movies(username))
    elif request.method == 'DELETE':
        if save_ranked_movies(username, []): return jsonify({'success': True})
        else: return jsonify({'error': 'Failed to clear movies'}), 500

@app.route('/api/movies/<int:movie_id>', methods=['DELETE'])
def delete_movie(movie_id):
    username = get_username_from_header()
    if not username: return jsonify({'error': '未提供使用者資訊'}), 401
    mode = request.args.get('mode', 'normal')
    movies = load_ranked_movies(username)
    movies_to_keep = [m for m in movies if m.get('id') != movie_id]
    if len(movies_to_keep) == len(movies): return jsonify({'error': 'Movie not found'}), 404
    recalculated_list = recalculate_ratings_and_ranks(movies_to_keep, mode)
    if save_ranked_movies(username, recalculated_list): return jsonify(recalculated_list)
    else: return jsonify({'error': 'Failed to save updated list'}), 500

@app.route('/api/search', methods=['GET'])
def search_movies():
    title = request.args.get('title')
    if not title: return jsonify({'error': 'Title parameter is required'}), 400
    results = search_movie_from_tmdb(title)
    if results is None: return jsonify({'error': 'Failed to fetch from TMDB'}), 500
    return jsonify(results)

@app.route('/api/rank', methods=['POST'])
def rank_movies():
    username = get_username_from_header()
    if not username: return jsonify({'error': '未提供使用者資訊'}), 401
    data = request.json; new_ranked_list = data.get('list'); mode = data.get('mode', 'normal')
    if not isinstance(new_ranked_list, list): return jsonify({'error': 'Invalid data format'}), 400
    recalculated_list = recalculate_ratings_and_ranks(new_ranked_list, mode)
    if save_ranked_movies(username, recalculated_list): return jsonify(recalculated_list)
    else: return jsonify({'error': 'Failed to save rankings'}), 500

@app.route('/api/review', methods=['POST'])
def save_review():
    username = get_username_from_header()
    if not username: return jsonify({'error': '未提供使用者資訊'}), 401
    data = request.json; movie_id = data.get('id'); review_text = data.get('review')
    if not movie_id: return jsonify({'error': 'Movie ID is required'}), 400
    movies = load_ranked_movies(username); movie_found = False
    for movie in movies:
        if movie['id'] == movie_id: movie['my_review'] = review_text; movie_found = True; break
    if not movie_found: return jsonify({'error': 'Movie not found'}), 404
    if save_ranked_movies(username, movies): return jsonify({'success': True})
    else: return jsonify({'error': 'Failed to save review'}), 500

@app.route('/api/random', methods=['GET'])
def get_random_movie():
    existing_ids_str = request.args.get('existing_ids', ''); existing_ids = {int(id) for id in existing_ids_str.split(',') if id}
    for _ in range(10):
        movie = get_random_movie_from_tmdb()
        if movie and movie.get('id') not in existing_ids: return jsonify(movie)
    return jsonify({'error': 'Could not find a new random movie'}), 500

# 移除 if __name__ == '__main__' 區塊，因為伺服器會用 Gunicorn 啟動